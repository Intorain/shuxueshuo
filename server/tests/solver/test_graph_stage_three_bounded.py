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


def _json_adapter(payload):
    operation = payload.get("operation", "echo")
    if operation == "pid":
        return {"pid": os.getpid()}
    if operation == "infinite":
        _infinite(payload["marker"])
    if operation == "delay":
        time.sleep(payload["seconds"])
    if operation == "error":
        raise KeyError("json_math_binding_bug")
    if operation == "symbolic":
        import sympy as sp
        x = sp.Symbol("x", real=True)
        return {"latex": sp.latex(sp.solve_univariate_inequality(x*x - 2 >= 0, x, relational=False))}
    if operation == "bad_result":
        return _NoHooks()
    return payload


class _NoHooks:
    def __reduce__(self):
        raise AssertionError("parent must not pickle mathematical objects")

    def __str__(self):
        raise AssertionError("parent must not format mathematical objects")


def _json_orphan_parent(marker, receipt):
    with bounded.JsonCalculationSession(_json_adapter) as session:
        session.run({"operation": "infinite", "marker": marker}, timeout_seconds=30,
                    receipt_path=receipt, attempt_id="orphan-attempt")


def test_json_session_reuses_worker_and_excludes_idle():
    with bounded.JsonCalculationSession(_json_adapter) as session:
        first, initial_elapsed = session.run({"operation": "pid"}, timeout_seconds=5)
        time.sleep(0.2)
        second, reused_elapsed = session.run({"operation": "pid"}, timeout_seconds=5)
        symbolic, _ = session.run({"operation": "symbolic"}, timeout_seconds=5)
    assert first == second
    assert initial_elapsed > 0
    assert reused_elapsed < 0.2
    assert "sqrt" in symbolic["latex"]
    assert _gone(first["pid"])


def test_json_input_rejects_custom_types_without_running_pickle_hooks():
    session = bounded.JsonCalculationSession(_json_adapter)
    with pytest.raises(TypeError, match="JSON-native"):
        session.run({"math": _NoHooks()}, timeout_seconds=5)
    assert session._process is None


@pytest.mark.parametrize("payload", [{"v": float("inf")}, {1: "bad key"}, {"v": 1 << 4097}])
def test_json_input_rejects_invalid_primitives(payload):
    with bounded.JsonCalculationSession(_json_adapter) as session, pytest.raises((TypeError, ValueError)):
        session.run(payload, timeout_seconds=5)


def test_json_input_rejects_depth_and_size_limits():
    from shuxueshuo_server.graph_lesson.stage_three.json_bounded import MAX_JSON_BYTES
    deep = []
    for _ in range(66):
        deep = [deep]
    for payload in (deep, {"v": "x" * (MAX_JSON_BYTES + 1)}):
        with bounded.JsonCalculationSession(_json_adapter) as session:
            with pytest.raises(ValueError, match="limit"):
                session.run(payload, timeout_seconds=5)
            assert session._process is None


def test_json_worker_errors_keep_identity_and_reject_custom_result():
    with bounded.JsonCalculationSession(_json_adapter) as session:
        with pytest.raises(bounded.CalculationWorkerError) as error:
            session.run({"operation": "error"}, timeout_seconds=5)
        assert error.value.exception_type == "KeyError"
        assert error.value.exception_module == "builtins"
        assert "json_math_binding_bug" in error.value.traceback
        with pytest.raises(bounded.CalculationWorkerError) as bad_result:
            session.run({"operation": "bad_result"}, timeout_seconds=5)
        assert bad_result.value.exception_type == "TypeError"
        assert bad_result.value.phase == "result_serialization"


def test_json_receipt_is_atomic_and_contains_result_without_arguments(tmp_path):
    import json
    receipt = tmp_path / "attempt.json"
    with bounded.JsonCalculationSession(_json_adapter) as session:
        value, _ = session.run({"operation": "pid"}, timeout_seconds=5,
                               receipt_path=receipt, attempt_id="returned-attempt")
    record = json.loads(receipt.read_text())
    assert record["attempt_id"] == "returned-attempt"
    assert record["status"] == "returned"
    assert record["result"] == value
    assert record["elapsed_seconds"] > 0
    assert "payload" not in record
    assert not list(tmp_path.glob("*.tmp"))


def test_json_infinite_timeout_reaps_worker_and_records_actual_time(tmp_path):
    import json
    marker, receipt = tmp_path / "json.pid", tmp_path / "timeout.json"
    with bounded.JsonCalculationSession(_json_adapter) as session, pytest.raises(bounded.CalculationTimeout) as error:
        session.run({"operation": "infinite", "marker": str(marker)}, timeout_seconds=1.2,
                    receipt_path=receipt, attempt_id="timeout-attempt")
    assert marker.is_file() and _gone(int(marker.read_text()))
    record = json.loads(receipt.read_text())
    assert record["status"] == "timeout"
    assert "result" not in record
    assert 1 < record["elapsed_seconds"] < 2
    assert error.value.elapsed_seconds < 2


@pytest.mark.skipif(os.name != "posix", reason="POSIX process kill")
def test_json_supervisor_reaps_worker_immediately_on_parent_sigkill_and_writes_receipt(tmp_path):
    import json
    marker, receipt = tmp_path / "json-orphan.pid", tmp_path / "parent-lost.json"
    parent = mp.get_context("spawn").Process(target=_json_orphan_parent, args=(str(marker), str(receipt)))
    worker_pid = None
    try:
        parent.start()
        assert _wait_until(marker.is_file, seconds=4)
        worker_pid = int(marker.read_text())
        killed = time.monotonic()
        parent.kill()
        parent.join(2)
        assert _wait_until(receipt.is_file, seconds=2)
        record = json.loads(receipt.read_text())
        assert record["status"] == "parent_lost"
        assert record["attempt_id"] == "orphan-attempt"
        assert 0 < record["elapsed_seconds"] < 4
        assert "result" not in record
        assert _gone(worker_pid)
        assert time.monotonic() - killed < 2
    finally:
        if parent.is_alive():
            parent.kill()
        parent.join()
        parent.close()
        if worker_pid is not None and not _gone(worker_pid):
            os.kill(worker_pid, signal.SIGKILL)


def test_json_session_threaded_and_socket_free(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("socket must not be created")
    monkeypatch.setattr(socket, "socket", forbidden)
    seen, failures = [], []
    def run():
        try:
            with bounded.JsonCalculationSession(_json_adapter) as session:
                seen.append(session.run({"ok": True}, timeout_seconds=5)[0])
        except BaseException as exc:  # noqa: BLE001 -- propagate thread test failures.
            failures.append(exc)
    thread = threading.Thread(target=run)
    thread.start()
    thread.join(7)
    assert not thread.is_alive() and not failures
    assert seen == [{"ok": True}]


def test_json_delivery_timeout_never_leaves_reusable_returned_receipt(tmp_path, monkeypatch):
    import json

    from shuxueshuo_server.graph_lesson.stage_three import json_bounded
    original = json_bounded._decode
    def delayed_decode(data):
        value = original(data)
        if isinstance(value, dict) and value.get("phase") == "prepared":
            time.sleep(1)
        return value
    monkeypatch.setattr(json_bounded, "_decode", delayed_decode)
    receipt = tmp_path / "delivery-timeout.json"
    with bounded.JsonCalculationSession(_json_adapter) as session, pytest.raises(bounded.CalculationTimeout):
        session.run({"operation": "pid"}, timeout_seconds=0.8,
                    receipt_path=receipt, attempt_id="delivery-timeout")
    record = json.loads(receipt.read_text())
    assert record["status"] == "timeout"
    assert "result" not in record


def test_json_post_ack_bookkeeping_cannot_reverse_success_into_timeout(tmp_path, monkeypatch):
    import json

    from shuxueshuo_server.graph_lesson.stage_three import json_bounded
    original = json_bounded._decode
    def delayed_settlement(data):
        value = original(data)
        if isinstance(value, dict) and value.get("phase") == "settled":
            time.sleep(1)
        return value
    monkeypatch.setattr(json_bounded, "_decode", delayed_settlement)
    receipt = tmp_path / "settled.json"
    with bounded.JsonCalculationSession(_json_adapter) as session:
        value, elapsed = session.run({"ok": True}, timeout_seconds=0.8,
                                     receipt_path=receipt, attempt_id="settled")
    record = json.loads(receipt.read_text())
    assert value == {"ok": True}
    assert elapsed == record["elapsed_seconds"] < 0.8
    assert record["status"] == "returned"


def test_json_parent_baseexception_reaps_math_and_writes_interruption_receipt(tmp_path, monkeypatch):
    import json

    from shuxueshuo_server.graph_lesson.stage_three import json_bounded
    marker, receipt = tmp_path / "interrupted.pid", tmp_path / "interrupted.json"
    def interrupted(*args):
        assert _wait_until(marker.is_file, seconds=3)
        raise KeyboardInterrupt("parent interrupted")
    monkeypatch.setattr(json_bounded, "_receive", interrupted)
    with bounded.JsonCalculationSession(_json_adapter) as session, pytest.raises(KeyboardInterrupt):
        session.run({"operation": "infinite", "marker": str(marker)}, timeout_seconds=10,
                    receipt_path=receipt, attempt_id="interrupted")
    record = json.loads(receipt.read_text())
    assert record["status"] == "parent_lost" and "result" not in record
    assert _gone(int(marker.read_text()))


def test_json_receipt_write_error_is_not_a_mathematical_timeout(tmp_path):
    with bounded.JsonCalculationSession(_json_adapter) as session, pytest.raises(bounded.CalculationWorkerError) as error:
        session.run({"ok": True}, timeout_seconds=5,
                    receipt_path=tmp_path / "missing" / "receipt.json", attempt_id="io-error")
    assert error.value.exception_type == "FileNotFoundError"
    assert error.value.phase == "supervisor"


def test_json_node_limit_counts_pending_shared_containers_before_expanding():
    from shuxueshuo_server.graph_lesson.stage_three.json_bounded import MAX_JSON_NODES
    shared = [None] * (MAX_JSON_NODES // 2)
    with bounded.JsonCalculationSession(_json_adapter) as session, pytest.raises(ValueError, match="node limit"):
        session.run([shared, shared, shared], timeout_seconds=5)
    assert session._process is None


def test_json_large_result_and_input_have_no_pipe_deadlock():
    payload = {"value": "m" * (2 * 1024 * 1024)}
    with bounded.JsonCalculationSession(_json_adapter) as session:
        result, elapsed = session.run(payload, timeout_seconds=8)
    assert result == payload
    assert 0 < elapsed < 8


def test_json_supervisor_confirmation_loss_is_not_contradictory_timeout(tmp_path, monkeypatch):
    import json

    from shuxueshuo_server.graph_lesson.stage_three import json_bounded
    original = json_bounded._receive
    calls = 0
    def lost_confirmation(*args):
        nonlocal calls
        calls += 1
        data = original(*args)
        if calls == 2:
            raise TimeoutError("simulated final confirmation lost")
        return data
    monkeypatch.setattr(json_bounded, "_receive", lost_confirmation)
    receipt = tmp_path / "confirmation-lost.json"
    with bounded.JsonCalculationSession(_json_adapter) as session, pytest.raises(bounded.CalculationWorkerError) as error:
        session.run({"ok": True}, timeout_seconds=5, receipt_path=receipt, attempt_id="confirmation-lost")
    assert error.value.exception_type == "SettlementConfirmationLost"
    record = json.loads(receipt.read_text())
    assert record["status"] == "returned" and record["result"] == {"ok": True}
