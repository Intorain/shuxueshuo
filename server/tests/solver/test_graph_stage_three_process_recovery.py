"""Real runner SIGKILL recovery across in-flight and completed calculation seams."""

import json
import multiprocessing as mp
import os
import time
import traceback
from collections import Counter
from pathlib import Path

import pytest
from sqlalchemy import text

from shuxueshuo_server.graph_lesson.stage_three import calculations, runner
from shuxueshuo_server.graph_lesson.stage_three.budget import BudgetLedger
from shuxueshuo_server.graph_lesson.stage_three.checkpoint import export_json
from shuxueshuo_server.graph_lesson.stage_three.preview import open_store
from tests.solver.test_graph_stage_three_contracts import upstream

TARGET = "/root/goals/0"
ROUTE = "discriminant"
SOLVE_BUDGET = 30


def _instrumented_dispatch(payload):
    """Importable pure JSON worker seam; the marker makes only the first call block."""
    if payload["operation"] == "advance":
        state = payload["state"]
        operation = "advance:" + str(state.get("commit_index", 0) + 1)
        line = json.dumps({"operation": operation, "pid": os.getpid()}) + "\n"
        descriptor = os.open(os.environ["STAGE_THREE_RECOVERY_COUNTS"], os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(descriptor, line.encode())
        finally:
            os.close(descriptor)
        marker = Path(os.environ["STAGE_THREE_RECOVERY_MARKER"])
        if (os.environ["STAGE_THREE_RECOVERY_MODE"] == "inflight" and state["fragments"]
                and not marker.exists()):
            export_json(marker, {"operation": operation, "math_pid": os.getpid(),
                                 "supervisor_pid": os.getppid(), "published_steps": len(state["fragments"])})
            time.sleep(60)
    return calculations.dispatch(payload)


def _pause_after_returned_receipt(attempt, store):
    marker = Path(os.environ["STAGE_THREE_RECOVERY_MARKER"])
    if (os.environ["STAGE_THREE_RECOVERY_MODE"] == "returned"
            and attempt["operation_key"].startswith("advance:")
            and store.snapshot()["math_steps"] and not marker.exists()):
        export_json(marker, {"operation": attempt["operation_key"], "attempt_id": attempt["attempt_id"],
                             "receipt_path": attempt["receipt_path"], "parent_pid": os.getpid()})
        time.sleep(60)


def _runner_process(source, output, mode, marker, counts, resumed, completion):
    os.environ.update(STAGE_THREE_RECOVERY_MODE=mode, STAGE_THREE_RECOVERY_MARKER=str(marker),
                      STAGE_THREE_RECOVERY_COUNTS=str(counts))
    hooks = {"calculation_dispatch": _instrumented_dispatch,
             "calculation_returned": _pause_after_returned_receipt}
    try:
        result = (runner.resume_sample(output, hooks=hooks) if resumed else
                  runner.run_sample(source, output, milestone="1b-1", hooks=hooks,
                                    solve_budget_seconds=SOLVE_BUDGET, verification_budget_seconds=30))
        completion.send({"ok": True, "status": result["status"]})
    except BaseException:  # noqa: BLE001 -- make child failures diagnosable without waiting for a marker.
        completion.send({"ok": False, "error": traceback.format_exc()})
    finally:
        completion.close()


def _start(source, output, mode, marker, counts, *, resumed=False):
    context = mp.get_context("spawn")
    reader, writer = context.Pipe(duplex=False)
    process = context.Process(target=_runner_process,
                              args=(source, output, mode, marker, counts, resumed, writer))
    process.start()
    writer.close()
    return process, reader


def _stop(process, connection):
    if process.is_alive():
        process.kill()
    process.join(5)
    assert not process.is_alive(), "test runner was not reaped"
    process.close()
    connection.close()


def _wait(predicate, *, process=None, connection=None, explanation):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        if process is not None and not process.is_alive():
            detail = connection.recv() if connection.poll(0.1) else {"exitcode": process.exitcode}
            pytest.fail(f"runner exited before {explanation}: {detail}")
        time.sleep(0.01)
    pytest.fail("timed out waiting for " + explanation)


def _read(path):
    return json.loads(Path(path).read_text())


def _durable(output):
    return open_store(output)


def _attempts(output):
    durable = _durable(output)
    with durable.transaction() as db:
        return [dict(row) for row in db.execute(text("""SELECT * FROM lesson_calculation_attempts
            WHERE run_id=:run_id AND target=:target AND route=:route AND bucket='solve' ORDER BY sequence"""),
            {"run_id": durable.identity["run_id"], "target": TARGET, "route": ROUTE}).mappings()]


def _pid_exists(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _resume_successfully(source, output, mode, marker, counts):
    process, connection = _start(source, output, mode, marker, counts, resumed=True)
    try:
        assert connection.poll(10), "resumed runner exceeded its test process deadline"
        completion = connection.recv()
        assert completion["ok"], completion.get("error")
        assert completion["status"] == "completed"
        process.join(5)
        assert not process.is_alive() and process.exitcode == 0
    finally:
        _stop(process, connection)
    result = _read(output / "stage-three-result.json")
    assert result["goals"][0]["status"] == "solved"
    route, = result["goals"][0]["routes"]
    assert route["status"] == "verified"
    return result


def _assert_prefix_and_no_duplicate_publication(output, prefix):
    durable = _durable(output)
    after = durable.events()
    assert after[:len(prefix)] == prefix
    assert len({event["event_id"] for event in after}) == len(after)
    assert [event["seq"] for event in after] == list(range(1, len(after) + 1))
    snapshot = durable.snapshot()
    steps = snapshot["math_steps"]
    assert len(steps) == 5
    assert [step["ordinal"] for step in steps] == [1, 2, 3, 4, 5]
    assert len({step["step_id"] for step in steps}) == 5
    published = [event for event in after if event["type"] == "lesson.chunk_ready"
                 and event["payload"]["kind"] == "math_step"]
    assert len(published) == 5
    assert len(snapshot["handoffs"]) == 1


def test_sigkill_during_math_preserves_prefix_and_actual_budget_without_downtime(tmp_path):
    source = upstream(tmp_path)
    output, marker, counts = tmp_path / "out", tmp_path / "blocked.json", tmp_path / "calls.jsonl"
    process, connection = _start(source, output, "inflight", marker, counts)
    try:
        _wait(marker.exists, process=process, connection=connection, explanation="in-flight math marker")
        blocked = _read(marker)
        assert blocked["published_steps"] >= 1
        prefix = _durable(output).events()
        assert _durable(output).snapshot()["math_steps"]
        pending, = [row for row in _attempts(output) if row["status"] == "pending"]
        assert pending["operation_key"] == blocked["operation"]
        process.kill()
        process.join(5)
        assert not process.is_alive()
        receipt_path = output / "calculation-budget" / "receipts" / (pending["attempt_id"] + ".json")
        _wait(receipt_path.exists, explanation="parent-lost supervisor receipt")
        receipt = _read(receipt_path)
        assert receipt["status"] == "parent_lost" and receipt["elapsed_seconds"] > 0
        _wait(lambda: not _pid_exists(blocked["math_pid"]), explanation="mathematical worker reap")
        # No live calculation exists during this simulated service downtime.
        time.sleep(0.2)
        assert _read(receipt_path) == receipt
    finally:
        _stop(process, connection)

    _resume_successfully(source, output, "inflight", marker, counts)
    _assert_prefix_and_no_duplicate_publication(output, prefix)
    rows = _attempts(output)
    interrupted, retried = [row for row in rows if row["operation_key"] == blocked["operation"]]
    assert interrupted["attempt_id"] == pending["attempt_id"]
    assert json.loads(interrupted["receipt"]) == receipt
    assert json.loads(retried["receipt"])["status"] == "returned" and retried["ordinal"] == 2
    earlier_spent = sum(row["elapsed_seconds"] for row in rows[:rows.index(retried)])
    assert retried["allowance_seconds"] == pytest.approx(SOLVE_BUDGET - earlier_spent)
    summary = BudgetLedger(_durable(output)).summary(TARGET, ROUTE, "solve")
    assert summary["actual_seconds"] == pytest.approx(sum(row["elapsed_seconds"] for row in rows))
    assert summary["reserved_upper_seconds"] == 0
    assert interrupted["elapsed_seconds"] == receipt["elapsed_seconds"]
    calls = Counter(json.loads(line)["operation"] for line in counts.read_text().splitlines())
    assert calls[blocked["operation"]] == 2
    assert all(count == (2 if operation == blocked["operation"] else 1) for operation, count in calls.items())


def test_sigkill_after_returned_receipt_reuses_result_without_recalculation_or_double_charge(tmp_path):
    source = upstream(tmp_path)
    output, marker, counts = tmp_path / "out", tmp_path / "returned.json", tmp_path / "calls.jsonl"
    process, connection = _start(source, output, "returned", marker, counts)
    try:
        _wait(marker.exists, process=process, connection=connection, explanation="durable returned receipt marker")
        blocked = _read(marker)
        receipt = _read(blocked["receipt_path"])
        assert receipt["status"] == "returned"
        pending, = [row for row in _attempts(output) if row["status"] == "pending"]
        assert pending["attempt_id"] == blocked["attempt_id"] and pending["elapsed_seconds"] == 0
        durable = _durable(output)
        prefix = durable.events()
        checkpoint = durable.checkpoint(TARGET, ROUTE)
        assert blocked["operation"] == "advance:" + str(checkpoint["driver_state"]["commit_index"] + 1)
        process.kill()
        process.join(5)
        assert not process.is_alive()
    finally:
        _stop(process, connection)

    _resume_successfully(source, output, "returned", marker, counts)
    _assert_prefix_and_no_duplicate_publication(output, prefix)
    rows = _attempts(output)
    completed, = [row for row in rows if row["operation_key"] == blocked["operation"]]
    assert completed["attempt_id"] == blocked["attempt_id"] and completed["ordinal"] == 1
    assert json.loads(completed["receipt"]) == receipt
    assert completed["elapsed_seconds"] == receipt["elapsed_seconds"]
    calls = Counter(json.loads(line)["operation"] for line in counts.read_text().splitlines())
    assert calls and all(count == 1 for count in calls.values())
    summary = BudgetLedger(_durable(output)).summary(TARGET, ROUTE, "solve")
    assert summary["actual_seconds"] == pytest.approx(sum(row["elapsed_seconds"] for row in rows))
    assert summary["reserved_upper_seconds"] == 0
