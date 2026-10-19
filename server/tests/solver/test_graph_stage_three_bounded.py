"""Real spawn/process interruption, including threaded callers and large pipes."""
import multiprocessing as mp
import os
import signal
import socket
import threading
import time
from pathlib import Path

import pytest

from shuxueshuo_server.graph_lesson.stage_three import bounded


def _identity(value):
    return value


def _sympy_value():
    import sympy as sp
    return sp.Union(sp.Interval(-sp.oo, -sp.sqrt(2)), sp.Interval(sp.sqrt(2), sp.oo))


def _fail():
    raise KeyError("deliberate_math_binding_bug")


def _crash():
    os._exit(73)


def _unserializable():
    return lambda: None


def _large_result(size):
    return b"m" * size


def _infinite(marker):
    Path(marker).write_text(str(os.getpid()))
    while True:
        pass


def _delay(marker):
    Path(marker).write_text(str(os.getpid()))
    time.sleep(30)
    return "too late"


def _ignore_termination(marker):
    # Test the final kill fallback even if a computation overrides its signals.
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    signal.signal(signal.SIGALRM, signal.SIG_IGN)
    _infinite(marker)


def _parent_for_orphan(marker):
    bounded.run_bounded(_infinite, marker, timeout_seconds=2)


def _gone(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    status = Path(f"/proc/{pid}/stat")
    return status.exists() and status.read_text().split()[2] == "Z"


def _wait_until(predicate, seconds=4):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_returns_exact_sympy_and_elapsed():
    import sympy as sp
    value, elapsed = bounded.run_bounded(_sympy_value, timeout_seconds=5)
    assert value == sp.Union(sp.Interval(-sp.oo, -sp.sqrt(2)), sp.Interval(sp.sqrt(2), sp.oo))
    assert 0 < elapsed < 5
    assert not any(child.name.startswith("SpawnProcess") for child in mp.active_children())


@pytest.mark.parametrize("function", [_infinite, _delay])
def test_real_worker_is_stopped_at_deadline_and_reaped(tmp_path, function):
    marker = tmp_path / "worker.pid"
    started = time.monotonic()
    with pytest.raises(bounded.CalculationTimeout) as error:
        bounded.run_bounded(function, str(marker), timeout_seconds=1.2)
    assert marker.is_file(), "test must reach the actual infinite/delayed computation"
    pid = int(marker.read_text())
    assert error.value.pid == pid
    assert error.value.elapsed_seconds >= 1.1
    assert time.monotonic() - started < 3
    assert _gone(pid)
    assert pid not in {child.pid for child in mp.active_children()}


def test_failure_preserves_exception_identity_and_worker_traceback():
    with pytest.raises(bounded.CalculationWorkerError) as error:
        bounded.run_bounded(_fail, timeout_seconds=5)
    value = error.value
    assert value.exception_type == "KeyError"
    assert value.exception_module == "builtins"
    assert "deliberate_math_binding_bug" in value.message
    assert "_fail" in value.traceback
    assert value.phase == "calculation"
    assert value.elapsed_seconds > 0
    assert _gone(value.pid)


@pytest.mark.skipif(os.name != "posix", reason="POSIX signal escalation")
def test_worker_ignoring_termination_is_killed_and_reaped(tmp_path):
    marker = tmp_path / "ignore-term.pid"
    started = time.monotonic()
    with pytest.raises(bounded.CalculationTimeout) as error:
        bounded.run_bounded(_ignore_termination, str(marker), timeout_seconds=1.2)
    assert marker.is_file()
    assert error.value.pid == int(marker.read_text())
    assert _gone(error.value.pid)
    assert time.monotonic() - started < 3


def test_spawn_transport_requires_no_network_socket(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("socket must not be created")
    monkeypatch.setattr(socket, "socket", forbidden)
    value, _ = bounded.run_bounded(_identity, {"local": True}, timeout_seconds=5)
    assert value == {"local": True}


def test_worker_crash_reports_exit_status_instead_of_hanging():
    with pytest.raises(bounded.CalculationWorkerError) as error:
        bounded.run_bounded(_crash, timeout_seconds=5)
    assert error.value.exception_type == "WorkerProcessExited"
    assert error.value.exitcode == 73
    assert _gone(error.value.pid)


def test_large_result_is_drained_before_join():
    size = 8 * 1024 * 1024
    value, elapsed = bounded.run_bounded(_large_result, size, timeout_seconds=8)
    assert value == b"m" * size
    assert elapsed < 8


def test_worker_result_serialization_failure_retains_phase():
    with pytest.raises(bounded.CalculationWorkerError) as error:
        bounded.run_bounded(_unserializable, timeout_seconds=5)
    assert error.value.phase == "result_serialization"
    assert error.value.exception_type in ("AttributeError", "PicklingError")
    assert _gone(error.value.pid)


def test_parent_startup_serialization_failure_has_diagnostics():
    with pytest.raises(bounded.CalculationWorkerError) as error:
        bounded.run_bounded(lambda: None, timeout_seconds=2)
    assert error.value.phase == "startup"
    assert error.value.exception_type in ("AttributeError", "PicklingError")
    assert error.value.traceback


def test_bounded_computation_works_from_preview_thread(tmp_path):
    seen, failures = [], []
    marker = tmp_path / "thread-worker.pid"
    def run():
        try:
            seen.append(bounded.run_bounded(_identity, {"exact": 42}, timeout_seconds=5)[0])
            with pytest.raises(bounded.CalculationTimeout):
                bounded.run_bounded(_infinite, str(marker), timeout_seconds=1.2)
        except BaseException as exc:  # noqa: BLE001 -- surface thread failures to the main test.
            failures.append(exc)
    thread = threading.Thread(target=run)
    thread.start()
    thread.join(8)
    assert not thread.is_alive()
    assert not failures
    assert seen == [{"exact": 42}]
    assert marker.is_file() and _gone(int(marker.read_text()))


def test_parent_baseexception_still_reaps_child(monkeypatch):
    pids = []
    def interrupted(objects, timeout):
        del objects, timeout
        pids.extend(child.pid for child in mp.active_children())
        raise KeyboardInterrupt("interrupt caller")
    monkeypatch.setattr(bounded, "wait", interrupted)
    with pytest.raises(KeyboardInterrupt, match="interrupt caller"):
        bounded.run_bounded(_delay, os.devnull, timeout_seconds=5)
    assert pids and all(_gone(pid) for pid in pids)


@pytest.mark.skipif(os.name != "posix", reason="POSIX orphan-process deadline")
def test_child_deadline_survives_parent_sigkill(tmp_path):
    marker = tmp_path / "orphan.pid"
    parent = mp.get_context("spawn").Process(target=_parent_for_orphan, args=(str(marker),))
    orphan_pid = None
    try:
        parent.start()
        assert _wait_until(marker.is_file, seconds=2)
        orphan_pid = int(marker.read_text())
        parent.kill()
        parent.join(2)
        assert not parent.is_alive()
        assert _wait_until(lambda: _gone(orphan_pid), seconds=3)
    finally:
        if parent.is_alive():
            parent.kill()
        parent.join()
        parent.close()
        if orphan_pid is not None and not _gone(orphan_pid):
            os.kill(orphan_pid, signal.SIGKILL)


def test_child_alarm_race_is_reported_as_timeout(tmp_path, monkeypatch):
    original = bounded.wait
    def lagged(objects, timeout):
        time.sleep(timeout + 0.05)
        return original(objects, timeout=0)
    monkeypatch.setattr(bounded, "wait", lagged)
    with pytest.raises(bounded.CalculationTimeout):
        bounded.run_bounded(_infinite, str(tmp_path / "alarm.pid"), timeout_seconds=1.2)


@pytest.mark.parametrize("budget", [0, -1])
def test_exhausted_budget_does_not_start_worker(budget):
    with pytest.raises(bounded.CalculationTimeout) as error:
        bounded.run_bounded(_identity, 42, timeout_seconds=budget)
    assert error.value.phase == "before_start"
    assert error.value.pid is None


@pytest.mark.parametrize("budget", [float("inf"), float("nan")])
def test_nonfinite_budget_is_rejected(budget):
    with pytest.raises(ValueError):
        bounded.run_bounded(_identity, 42, timeout_seconds=budget)
