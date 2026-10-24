"""Bounded JSON transport with a persistent supervisor and mathematical worker.

Only exact JSON-native types cross a process boundary. The supervisor never
imports the calculation adapter or constructs mathematical objects. It watches
the caller's pipe even while the mathematical worker holds the GIL, kills and
reaps that worker on caller disappearance, and records the attempt's actual
elapsed time. Inactive sessions consume no calculation budget.
"""

import importlib
import json
import math
import multiprocessing as mp
import os
import select
import signal
import struct
import threading
import time
import types
import zlib
from pathlib import Path

from .bounded import (
    CalculationTimeout,
    CalculationWorkerError,
    _error_payload,
    _install_child_expiration,
    _reap,
    _timeout_exit,
    wait,
)

MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_JSON_DEPTH = 64
MAX_JSON_NODES = 200_000
_CHUNK = 480
_CLEANUP_SECONDS = 1.0
_COMPRESS_THRESHOLD = 16 * 1024
_COMPRESSED_MAGIC = b"\x00S3Z1\x00"


def _validate_json(value):
    """Validate native values and bound the size of their UTF-8 JSON encoding.

    The bound may exceed the actual size: those inputs retain streaming encoding
    so an overestimate never rejects otherwise valid calculation data.
    """
    pending = [(value, 0)]
    nodes, text_size, encoded_size = 1, 0, 0
    while pending:
        item, depth = pending.pop()
        if depth > MAX_JSON_DEPTH or nodes > MAX_JSON_NODES:
            raise ValueError("JSON calculation data exceeds depth/node limit")
        kind = type(item)
        if kind in (type(None), bool):
            encoded_size += 5 if item is False else 4
            continue
        if kind is int:
            bits = item.bit_length()
            if bits > 4096:
                raise ValueError("JSON integer exceeds 4096-bit limit")
            # 30103 / 100000 is an upper bound for log10(2). Do not convert
            # every large integer to decimal before the streaming byte guard.
            encoded_size += bits * 30103 // 100000 + 1 + (item < 0)
        elif kind is float:
            if not math.isfinite(item):
                raise ValueError("JSON numbers must be finite")
            encoded_size += len(repr(item))
        elif kind is str:
            text_size += len(item)
            # A character needs at most six bytes (a JSON control escape).
            # Non-ASCII UTF-8 characters need at most four; include quotes.
            encoded_size += 6 * len(item) + 2
        elif kind is list:
            nodes += len(item)
            if nodes > MAX_JSON_NODES:
                raise ValueError("JSON calculation data exceeds node limit")
            encoded_size += 2 + max(0, len(item) - 1)
            pending.extend((child, depth + 1) for child in item)
        elif kind is dict:
            nodes += len(item)
            if nodes > MAX_JSON_NODES:
                raise ValueError("JSON calculation data exceeds node limit")
            encoded_size += 2 + max(0, len(item) - 1) + len(item)
            for key, child in item.items():
                if type(key) is not str:
                    raise TypeError("JSON object keys must be exact strings")
                text_size += len(key)
                encoded_size += 6 * len(key) + 2
                pending.append((child, depth + 1))
        else:
            raise TypeError(f"calculation data must be JSON-native, got {kind.__module__}.{kind.__name__}")
        if text_size > MAX_JSON_BYTES:
            raise ValueError("JSON calculation data exceeds byte limit")
    return encoded_size


def _encode(value):
    if _validate_json(value) <= MAX_JSON_BYTES:
        # Only bounded output reaches the C encoder. Larger estimates fall
        # back to the incremental guard instead of allocating oversized JSON.
        return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    chunks, size = [], 0
    for text in json.JSONEncoder(ensure_ascii=False, allow_nan=False, separators=(",", ":")).iterencode(value):
        chunk = text.encode("utf-8")
        size += len(chunk)
        if size > MAX_JSON_BYTES:
            raise ValueError("JSON calculation data exceeds byte limit")
        chunks.append(chunk)
    return b"".join(chunks)


def _decode(data):
    if len(data) > MAX_JSON_BYTES:
        raise ValueError("JSON calculation data exceeds byte limit")
    if data.startswith(_COMPRESSED_MAGIC):
        decoder = zlib.decompressobj()
        try:
            expanded = decoder.decompress(data[len(_COMPRESSED_MAGIC):], MAX_JSON_BYTES + 1)
        except zlib.error as exc:
            raise ValueError("invalid compressed JSON data") from exc
        if len(expanded) > MAX_JSON_BYTES or decoder.unconsumed_tail:
            raise ValueError("JSON calculation data exceeds byte limit")
        if not decoder.eof or decoder.unused_data:
            raise ValueError("incomplete or trailing compressed JSON data")
        data = expanded
    result = json.loads(data)
    _validate_json(result)
    return result


def _wire_bytes(data):
    """Compress only pipe messages; durable receipts remain ordinary JSON."""
    if len(data) > MAX_JSON_BYTES:
        raise ValueError("JSON calculation data exceeds byte limit")
    if len(data) > _COMPRESS_THRESHOLD:
        compressed = _COMPRESSED_MAGIC + zlib.compress(data, level=1)
        if len(compressed) < len(data):
            return compressed
    return data


def _frames(data):
    yield b"H" + struct.pack("!Q", len(data))
    for offset in range(0, len(data), _CHUNK):
        yield b"D" + data[offset:offset + _CHUNK]
    yield b"E"


def _send(connection, data, deadline=None, cancel_connection=None):
    """Atomic POSIX frames prevent partial-frame recv from evading deadlines."""
    if deadline is not None and time.monotonic() >= deadline:
        raise TimeoutError("JSON transport deadline exceeded")
    data = _wire_bytes(data)
    fd = connection.fileno()
    if os.name != "posix":
        for frame in _frames(data):
            connection.send_bytes(frame)
        return
    os.set_blocking(fd, False)
    for frame in _frames(data):
        packet = struct.pack("!i", len(frame)) + frame
        while True:
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                raise TimeoutError("JSON transport deadline exceeded")
            try:
                count = os.write(fd, packet)
                if count != len(packet):
                    raise OSError("partial atomic pipe frame")
                break
            except BlockingIOError:
                cancelled, writable, _ = select.select(
                    [] if cancel_connection is None else [cancel_connection], [fd], [], remaining)
                if cancelled:
                    cancel_connection.recv_bytes(1)
                    raise ValueError("unexpected message while calculation is active")
                if not writable:
                    raise TimeoutError("JSON transport deadline exceeded")


class _Reader:
    def __init__(self):
        self.size = None
        self.data = bytearray()

    def read(self, connection):
        frame = connection.recv_bytes(_CHUNK + 1)
        if self.size is None and frame[:1] == b"H" and len(frame) == 9:
            self.size = struct.unpack("!Q", frame[1:])[0]
            if self.size > MAX_JSON_BYTES:
                raise ValueError("JSON frame exceeds byte limit")
        elif self.size is not None and frame[:1] == b"D":
            self.data.extend(frame[1:])
            if len(self.data) > self.size:
                raise ValueError("JSON frame exceeds announced size")
        elif self.size is not None and frame == b"E" and len(self.data) == self.size:
            data = bytes(self.data)
            self.size, self.data = None, bytearray()
            return data
        else:
            raise ValueError("invalid JSON frame")
        return None


def _receive(connection, deadline=None):
    reader = _Reader()
    while True:
        remaining = None if deadline is None else deadline - time.monotonic()
        if remaining is not None and remaining <= 0:
            raise TimeoutError("JSON transport deadline exceeded")
        if not wait([connection], timeout=remaining):
            raise TimeoutError("JSON transport deadline exceeded")
        data = reader.read(connection)
        if data is not None:
            return data


def _disarm(timer):
    if os.name == "posix" and hasattr(signal, "setitimer"):
        signal.setitimer(signal.ITIMER_REAL, 0)
    elif timer is not None:
        timer.cancel()


def _worker(requests, responses, module, qualname):
    # Import and all mathematical decoding happen only inside this worker.
    function = None
    try:
        while True:
            request = _decode(_receive(requests))
            deadline = request["deadline"]
            timer = _install_child_expiration(deadline)
            phase = "adapter_import"
            try:
                if function is None:
                    function = importlib.import_module(module)
                    for name in qualname.split("."):
                        function = getattr(function, name)
                phase = "calculation"
                result = function(request["payload"])
                phase = "result_serialization"
                response = _encode({"status": "returned", "result": result})
            except BaseException as exc:  # noqa: BLE001 -- preserve worker identity.
                response = _encode({"status": "worker_error", "error": _error_payload(exc, phase)})
            _send(responses, response, deadline)
            _disarm(timer)
    except (EOFError, BrokenPipeError, OSError, TimeoutError):
        pass
    finally:
        requests.close()
        responses.close()
    os._exit(0)


def _receipt(request, outcome, elapsed):
    receipt = {"schema_version": "bounded-calculation-receipt/v1",
               "attempt_id": request.get("attempt_id"), "elapsed_seconds": elapsed, **outcome}
    path = request.get("receipt_path")
    if path:
        destination = Path(path)
        temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
        data = _encode(receipt)
        with temporary.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    return receipt


def _supervisor(parent_requests, parent_responses, module, qualname):
    context = mp.get_context("spawn")
    math_requests, sender = context.Pipe(duplex=False)
    receiver, math_responses = context.Pipe(duplex=False)
    worker = context.Process(target=_worker, args=(math_requests, math_responses, module, qualname), daemon=True)
    active, reader = None, _Reader()
    try:
        while True:
            raw = _receive(parent_requests)
            active = _decode(raw)
            started, deadline = active["started"], active["deadline"]
            if worker.pid is None:
                worker.start()
                math_requests.close()
                math_responses.close()
            _send(sender, _encode({"payload": active["payload"], "deadline": deadline}),
                  deadline, cancel_connection=parent_requests)
            outcome = None
            while outcome is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    outcome = {"status": "timeout"}
                    break
                ready = wait([parent_requests, receiver, worker.sentinel], timeout=remaining)
                if parent_requests in ready:
                    try:
                        parent_requests.recv_bytes(1)
                    except EOFError:
                        # The parent's deadline closes the request pipe too.
                        # Prefer timeout once that shared deadline has expired,
                        # even if EOF wins the race with the worker's alarm.
                        outcome = {"status": "timeout" if time.monotonic() >= deadline else "parent_lost"}
                        break
                    raise ValueError("concurrent calculation requests are not supported")
                if receiver in ready:
                    try:
                        data = reader.read(receiver)
                    except (EOFError, OSError):
                        worker.join(0)
                        outcome = {"status": "timeout"} if time.monotonic() >= deadline or _timeout_exit(worker.exitcode) else {
                            "status": "worker_error", "error": {"exception_type": "WorkerProcessExited",
                            "exception_module": __name__, "message": "mathematical worker exited without result",
                            "traceback": "", "phase": "calculation", "exitcode": worker.exitcode}}
                    else:
                        if data is not None:
                            outcome = _decode(data)
                elif worker.sentinel in ready:
                    worker.join(0)
                    outcome = {"status": "timeout"} if time.monotonic() >= deadline or _timeout_exit(worker.exitcode) else {
                        "status": "worker_error", "error": {"exception_type": "WorkerProcessExited",
                        "exception_module": __name__, "message": "mathematical worker exited without result",
                        "traceback": "", "phase": "calculation", "exitcode": worker.exitcode}}
            if outcome["status"] in ("timeout", "parent_lost") or not worker.is_alive():
                _reap(worker)
            if outcome["status"] in ("returned", "worker_error"):
                # Delivery is provisional until the parent has decoded all JSON
                # and acknowledged before the same deadline. A parent timeout
                # must never leave a reusable successful receipt behind.
                _send(parent_responses, _encode({"phase": "prepared", "outcome": outcome}),
                      deadline, cancel_connection=parent_requests)
                acknowledgement = _decode(_receive(parent_requests, deadline))
                if acknowledgement != {"accept": active.get("attempt_id")}:
                    raise ValueError("invalid calculation delivery acknowledgement")
                if time.monotonic() >= deadline:
                    raise TimeoutError("calculation delivery acknowledgement exceeded deadline")
            receipt = _receipt(active, outcome, time.monotonic() - started)
            active = None
            if outcome["status"] == "parent_lost":
                break
            # Settlement persistence/confirmation is bookkeeping after the
            # budgeted result transfer has completed, and cannot turn an
            # acknowledged result into a contradictory mathematical timeout.
            _send(parent_responses, _encode({"phase": "settled", "status": receipt["status"],
                  "elapsed_seconds": receipt["elapsed_seconds"]}), time.monotonic() + _CLEANUP_SECONDS)
            if outcome["status"] == "timeout" or not worker.is_alive():
                break
    except (EOFError, BrokenPipeError, TimeoutError) as exc:
        _reap(worker)
        if active is not None:
            status = "timeout" if isinstance(exc, TimeoutError) or time.monotonic() >= active["deadline"] else "parent_lost"
            receipt = _receipt(active, {"status": status}, time.monotonic() - active["started"])
            if status == "timeout":
                try:
                    _send(parent_responses, _encode({"phase": "settled", **receipt}), time.monotonic() + 0.2)
                except (EOFError, OSError, TimeoutError):
                    pass
    except BaseException as exc:  # noqa: BLE001 -- supervisor errors remain diagnostic failures.
        _reap(worker)
        if active is not None:
            outcome = {"status": "worker_error", "error": _error_payload(exc, "supervisor")}
            elapsed = time.monotonic() - active["started"]
            try:
                receipt = _receipt(active, outcome, elapsed)
            except OSError:
                # A failed receipt write must remain a program/IO error. The
                # attempt stays reserved in the ledger rather than fabricated.
                receipt = {"status": "worker_error", "error": outcome["error"], "elapsed_seconds": elapsed}
            try:
                _send(parent_responses, _encode({"phase": "settled", **receipt}), time.monotonic() + 0.2)
            except (EOFError, OSError, TimeoutError):
                pass
    finally:
        reaped = _reap(worker)
        for connection in (parent_requests, parent_responses, math_requests, math_responses, sender, receiver):
            connection.close()
        if reaped and worker.pid is not None:
            worker.close()
    os._exit(0)


class JsonCalculationSession:
    """Reuse a spawn worker; each ``run`` receives/returns JSON-native data.

    ``receipt_path`` belongs to the caller's attempt ledger. Its parent directory
    must already exist. Only results decoded and acknowledged before the deadline
    receive a reusable receipt. Elapsed time includes startup, mathematical work,
    transfer and caller decoding through the supervisor's receipt of that ACK;
    receipt fsync and final settlement confirmation are excluded bookkeeping.
    The supervisor also records actual work duration when the caller dies.
    No input payload is written to the receipt.
    """

    def __init__(self, function):
        if type(function) is not types.FunctionType or "<locals>" in function.__qualname__ or function.__name__ == "<lambda>":
            raise TypeError("calculation adapter must be an importable top-level function")
        self._module, self._qualname = function.__module__, function.__qualname__
        self._process = self._requests = self._responses = None
        self._closed = False
        self._lock = threading.Lock()

    def __enter__(self):
        if self._closed:
            raise RuntimeError("calculation session is closed")
        return self

    def __exit__(self, *_):
        self.close()

    def _start(self):
        context = mp.get_context("spawn")
        requests, self._requests = context.Pipe(duplex=False)
        self._responses, responses = context.Pipe(duplex=False)
        self._process = context.Process(target=_supervisor, args=(requests, responses, self._module, self._qualname))
        try:
            self._process.start()
        finally:
            requests.close()
            responses.close()

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._requests is not None:
            self._requests.close()
        if self._process is not None and self._process.pid is not None:
            # EOF wakes the supervisor, which first kills/reaps its math child.
            self._process.join(_CLEANUP_SECONDS)
            if _reap(self._process):
                self._process.close()
        if self._responses is not None:
            self._responses.close()

    def run(self, payload, *, timeout_seconds, receipt_path=None, attempt_id=None):
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("calculation session already has an active run")
        started = time.monotonic()
        accepting = False
        try:
            if self._closed:
                raise RuntimeError("calculation session is closed")
            if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not math.isfinite(timeout_seconds):
                raise ValueError("timeout_seconds must be finite")
            if timeout_seconds <= 0:
                raise CalculationTimeout(elapsed_seconds=0.0, phase="before_start")
            deadline = started + timeout_seconds
            request = {"payload": payload, "deadline": deadline, "started": started,
                       "receipt_path": os.fspath(receipt_path) if receipt_path is not None else None,
                       "attempt_id": attempt_id}
            raw = _encode(request)
            if self._process is None:
                self._start()
            _send(self._requests, raw, deadline)
            delivery = _decode(_receive(self._responses, deadline))
            outcome = delivery.get("outcome", delivery)
            if delivery["phase"] == "prepared":
                if time.monotonic() >= deadline:
                    raise TimeoutError("calculation result decoding exceeded deadline")
                _send(self._requests, _encode({"accept": attempt_id}), deadline)
                accepting = True
                # The accept is either settled by the supervisor within budget,
                # or followed by EOF/timeout. Settlement I/O is not more math.
                delivery = _decode(_receive(self._responses, time.monotonic() + _CLEANUP_SECONDS))
            if delivery["phase"] != "settled":
                raise RuntimeError("invalid calculation settlement")
            elapsed = delivery["elapsed_seconds"]
            if delivery["status"] == "timeout":
                raise CalculationTimeout(elapsed_seconds=elapsed, pid=self._process.pid, phase="calculation_or_transfer")
            if delivery["status"] == "worker_error":
                error = delivery.get("error", outcome.get("error"))
                if error is None:
                    raise RuntimeError("worker error has no diagnostic payload")
                raise CalculationWorkerError(
                    **{key: error[key] for key in ("exception_type", "exception_module", "message", "traceback", "phase")},
                    elapsed_seconds=elapsed, pid=self._process.pid, exitcode=error.get("exitcode"))
            if delivery["status"] != "returned":
                raise RuntimeError(f"unexpected calculation outcome: {delivery['status']}")
            return outcome["result"], elapsed
        except TimeoutError as exc:
            self.close()
            if isinstance(exc, CalculationTimeout):
                raise
            if accepting:
                # ACK may already have a durable successful receipt. Missing
                # settlement confirmation is an I/O failure, never a new math
                # timeout that would contradict that receipt on recovery.
                raise CalculationWorkerError(
                    exception_type="SettlementConfirmationLost", exception_module=__name__,
                    message="calculation acknowledgement was sent but settlement was not received",
                    elapsed_seconds=time.monotonic() - started, phase="settlement") from exc
            raise CalculationTimeout(elapsed_seconds=time.monotonic() - started,
                                     phase="calculation_or_transfer") from exc
        except CalculationWorkerError:
            raise
        except (EOFError, OSError) as exc:
            self.close()
            if not accepting and time.monotonic() >= deadline:
                raise CalculationTimeout(elapsed_seconds=time.monotonic() - started,
                                         phase="calculation_or_transfer") from exc
            raise CalculationWorkerError(
                exception_type="SettlementConfirmationLost" if accepting else "SupervisorProcessExited",
                exception_module=__name__, message=str(exc), elapsed_seconds=time.monotonic() - started,
                phase="settlement" if accepting else "supervisor") from exc
        except BaseException:
            self.close()
            raise
        finally:
            self._lock.release()
