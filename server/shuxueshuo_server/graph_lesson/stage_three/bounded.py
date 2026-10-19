"""Interruptible budgets for trusted, local mathematical computations.

``run_bounded(function, *args, timeout_seconds=...)`` uses a fresh spawn process,
never fork or a background computation thread. Only importable functions and
picklable mathematical inputs belong here; providers, open databases and other
live resources must remain in the caller. Results are trusted process-local
pickle data, never external artifacts.

The budget starts before process startup and includes startup, computation,
serialization and pipe transfer. Parent-side bookkeeping and process reaping are
also included in the reported elapsed time. Child computation and serialization
are forcibly interruptible; trusted parent-side input pickling and result
reconstruction are synchronous, with deadline checks after they return. This is
not a hard deadline for arbitrary pickle hooks or untrusted object graphs.
The child has its own absolute
expiration: POSIX uses a default-action kernel timer in the spawned child only,
so callers may run on any thread and a killed parent cannot leave an infinite
Python calculation. Platforms without that timer use a child watchdog thread;
the living parent still enforces the deadline by terminating/killing the process.
"""

import math
import multiprocessing as mp
import os
import pickle
import signal
import struct
import threading
import time
import traceback as traceback_module
from multiprocessing.connection import wait

# Each pipe write is smaller than POSIX PIPE_BUF, including Connection's frame.
# Once poll reports data, recv_bytes cannot be left waiting for a large message
# whose producer has stalled. Large results are assembled from bounded frames.
# POSIX guarantees only 512 bytes (including on macOS), not Linux's usual 4096.
_CHUNK_BYTES = 480
_MAX_FRAME_BYTES = _CHUNK_BYTES + 1
_MAX_RESULT_BYTES = 128 * 1024 * 1024
_WATCHDOG_EXIT = 124
_TERMINATE_GRACE_SECONDS = 0.15


class CalculationTimeout(TimeoutError):
    """The computation/transport deadline expired; its worker has been reaped."""

    def __init__(self, *, elapsed_seconds, pid=None, phase="calculation"):
        super().__init__(f"calculation deadline exceeded during {phase}")
        self.elapsed_seconds = elapsed_seconds
        self.pid = pid
        self.phase = phase


class CalculationWorkerError(RuntimeError):
    """A worker failed, preserving its exception identity and traceback."""

    def __init__(self, *, exception_type, exception_module, message, traceback="",
                 elapsed_seconds, pid=None, exitcode=None, phase="calculation"):
        super().__init__(f"{exception_module}.{exception_type}: {message}")
        self.exception_type = exception_type
        self.exception_module = exception_module
        self.message = message
        self.traceback = traceback
        self.elapsed_seconds = elapsed_seconds
        self.pid = pid
        self.exitcode = exitcode
        self.phase = phase


def _message(exception):
    try:
        return str(exception)
    except BaseException:  # noqa: BLE001 -- diagnostics must not hide the original failure.
        return "exception message could not be formatted"


def _error_payload(exception, phase):
    return {"ok": False, "exception_type": type(exception).__name__,
            "exception_module": type(exception).__module__, "message": _message(exception),
            "traceback": traceback_module.format_exc(), "phase": phase}


def _install_child_expiration(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        os._exit(_WATCHDOG_EXIT)
    if os.name == "posix" and hasattr(signal, "setitimer"):
        # A kernel default action does not need the Python GIL, unlike a Python
        # signal handler. This touches no signal state in the calling process.
        signal.signal(signal.SIGALRM, signal.SIG_DFL)
        signal.setitimer(signal.ITIMER_REAL, remaining)
    else:
        timer = threading.Timer(remaining, os._exit, args=(_WATCHDOG_EXIT,))
        timer.daemon = True
        timer.start()


def _worker(connection, function, args, deadline):
    _install_child_expiration(deadline)
    phase = "calculation"
    try:
        value = function(*args)
        phase = "result_serialization"
        payload = pickle.dumps({"ok": True, "result": value}, protocol=pickle.HIGHEST_PROTOCOL)
        if len(payload) > _MAX_RESULT_BYTES:
            raise ValueError("calculation result exceeds the 128 MiB transport limit")
    except BaseException as exc:  # noqa: BLE001 -- transport original error identity to the caller.
        payload = pickle.dumps(_error_payload(exc, phase), protocol=pickle.HIGHEST_PROTOCOL)
    try:
        connection.send_bytes(b"H" + struct.pack("!Q", len(payload)))
        for offset in range(0, len(payload), _CHUNK_BYTES):
            connection.send_bytes(b"D" + payload[offset:offset + _CHUNK_BYTES])
        connection.send_bytes(b"E")
    except (BrokenPipeError, EOFError, OSError):
        # The caller was interrupted or killed. No computation may outlive it
        # merely to finish delivery, and the child expiration remains armed.
        pass
    finally:
        connection.close()
    # Results have already been explicitly flushed through the pipe. Avoid
    # interpreter shutdown hooks or user-created threads delaying worker exit.
    os._exit(0)


def _reap(process):
    """Stop all calculation before returning; SIGKILL is followed by waitpid."""
    if process is None or process.pid is None:
        return
    if process.is_alive():
        process.terminate()
        process.join(_TERMINATE_GRACE_SECONDS)
    if process.is_alive():
        process.kill()
    process.join()


def _timeout_exit(exitcode):
    return exitcode == _WATCHDOG_EXIT or (
        os.name == "posix" and exitcode == -int(signal.SIGALRM)
    )


def _protocol_error(message, started, process):
    return CalculationWorkerError(
        exception_type="WorkerProtocolError", exception_module=__name__, message=message,
        elapsed_seconds=time.monotonic() - started, pid=process.pid,
        exitcode=process.exitcode, phase="result_transfer",
    )


def _receive(connection, process, deadline, started):
    expected, payload = None, bytearray()
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CalculationTimeout(elapsed_seconds=time.monotonic() - started,
                                     pid=process.pid, phase="calculation_or_transfer")
        ready = wait([connection, process.sentinel], timeout=remaining)
        if connection in ready:
            try:
                frame = connection.recv_bytes(_MAX_FRAME_BYTES)
            except (EOFError, OSError) as exc:
                process.join(0)
                if time.monotonic() >= deadline or _timeout_exit(process.exitcode):
                    raise CalculationTimeout(elapsed_seconds=time.monotonic() - started,
                                             pid=process.pid, phase="calculation_or_transfer") from exc
                raise CalculationWorkerError(
                    exception_type="WorkerProcessExited", exception_module=__name__,
                    message="worker exited before delivering a complete result",
                    elapsed_seconds=time.monotonic() - started, pid=process.pid,
                    exitcode=process.exitcode, phase="calculation_or_transfer",
                ) from exc
            if frame[:1] == b"H" and expected is None and len(frame) == 9:
                expected = struct.unpack("!Q", frame[1:])[0]
                if expected > _MAX_RESULT_BYTES:
                    raise _protocol_error("result size exceeds transport limit", started, process)
            elif frame[:1] == b"D" and expected is not None:
                payload.extend(frame[1:])
                if len(payload) > expected:
                    raise _protocol_error("result exceeds announced size", started, process)
            elif frame == b"E" and expected is not None and len(payload) == expected:
                return bytes(payload)
            else:
                raise _protocol_error("invalid or incomplete result frame", started, process)
        elif process.sentinel in ready:
            process.join(0)
            if time.monotonic() >= deadline or _timeout_exit(process.exitcode):
                raise CalculationTimeout(elapsed_seconds=time.monotonic() - started,
                                         pid=process.pid, phase="calculation_or_transfer")
            # The pipe has no buffered frame and the producer is gone.
            raise CalculationWorkerError(
                exception_type="WorkerProcessExited", exception_module=__name__,
                message="worker exited without a result", elapsed_seconds=time.monotonic()-started,
                pid=process.pid, exitcode=process.exitcode, phase="calculation_or_transfer",
            )


def run_bounded(function, *args, timeout_seconds):
    """Run one local calculation, returning ``(result, elapsed_seconds)``.

    Exceptions use ``CalculationWorkerError.exception_module/exception_type``;
    callers decide which mathematical failures or programming errors they imply.
    Timeouts, including races with the child's own expiration, always use
    ``CalculationTimeout``. Every parent exit path, including BaseException,
    closes pipe handles and terminates/joins the spawned worker.
    """
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (float, int)):
        raise TypeError("timeout_seconds must be a finite number")
    if not math.isfinite(timeout_seconds):
        raise ValueError("timeout_seconds must be finite")
    started = time.monotonic()
    if timeout_seconds <= 0:
        raise CalculationTimeout(elapsed_seconds=0.0, phase="before_start")
    if not callable(function):
        raise TypeError("function must be callable")
    deadline = started + timeout_seconds
    context = mp.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_worker, args=(sender, function, args, deadline), daemon=True)
    error, result = None, None
    phase = "startup"
    try:
        process.start()
        sender.close()
        phase = "result_transfer"
        payload = _receive(receiver, process, deadline, started)
        if time.monotonic() >= deadline:
            raise CalculationTimeout(elapsed_seconds=time.monotonic()-started, pid=process.pid, phase=phase)
        phase = "result_deserialization"
        envelope = pickle.loads(payload)
        if time.monotonic() >= deadline:
            raise CalculationTimeout(elapsed_seconds=time.monotonic()-started, pid=process.pid, phase=phase)
        if envelope["ok"]:
            result = envelope["result"]
        else:
            error = CalculationWorkerError(
                **{key: envelope[key] for key in ("exception_type", "exception_module", "message", "traceback", "phase")},
                elapsed_seconds=time.monotonic()-started, pid=process.pid, exitcode=process.exitcode,
            )
    except (CalculationTimeout, CalculationWorkerError) as exc:
        error = exc
    except Exception as exc:  # noqa: BLE001 -- preserve startup/transport failure identity.
        detail = _error_payload(exc, phase)
        error = CalculationWorkerError(
            **{key: detail[key] for key in ("exception_type", "exception_module", "message", "traceback", "phase")},
            elapsed_seconds=time.monotonic()-started, pid=process.pid, exitcode=process.exitcode,
        )
    finally:
        try:
            _reap(process)
            if isinstance(error, CalculationWorkerError):
                error.exitcode = process.exitcode
        finally:
            receiver.close()
            sender.close()
            if process.pid is not None:
                process.close()
    elapsed = time.monotonic() - started
    if error is not None:
        error.elapsed_seconds = elapsed
        raise error
    return result, elapsed
