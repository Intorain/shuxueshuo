"""Same-run math priority without charging queue waits to either worker budget."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from shuxueshuo_server.graph_lesson.stage_three import (
    bounded,
    calculation_gate,
    calculations,
)
from shuxueshuo_server.graph_lesson.stage_three.budget import BudgetLedger
from shuxueshuo_server.graph_lesson.stage_three.events import EventStore
from shuxueshuo_server.graph_lesson.stage_three.route_calculations import (
    DurableCalculations,
    InteractionUnavailable,
)
from tests.solver.test_graph_stage_three_events import IDENTITY, TARGET


def _waiting(gate, **counts):
    with gate._condition:
        assert gate._condition.wait_for(lambda: all(gate._waiting[key] == value for key, value in counts.items()), 2)


def test_directory_aliases_and_separate_store_objects_share_only_their_run_gate(tmp_path):
    first = calculation_gate.for_directory(tmp_path)
    assert calculation_gate.for_directory(tmp_path / "child" / "..") is first
    assert calculation_gate.for_directory(tmp_path / "different") is not first
    store = EventStore(tmp_path, IDENTITY, create=True)
    other = EventStore(tmp_path, IDENTITY)
    left = DurableCalculations(store, TARGET, "math", limits={"solve": 10}, dispatch=calculations.dispatch)
    right = DurableCalculations(other, TARGET, "interactions", limits={"interaction": 30}, dispatch=calculations.dispatch)
    assert left._gate is first and right._gate is first


def test_math_waiter_precedes_queued_interaction_without_preempting_active_work():
    gate = calculation_gate.CalculationGate()
    entered, release = threading.Event(), threading.Event()
    order = []

    def operation(role):
        with gate.operation(role):
            order.append(role)
            if role == "solve":
                entered.set()
                assert release.wait(2)

    with ThreadPoolExecutor(max_workers=2) as executor:
        try:
            with gate.operation("interaction"):
                interaction = executor.submit(operation, "interaction")
                _waiting(gate, interaction=1)
                math = executor.submit(operation, "solve")
                _waiting(gate, math=1, interaction=1)
                assert order == [], "the active operation remains nonpreemptive"
            assert entered.wait(2)
            assert order == ["solve"] and not interaction.done()
        finally:
            release.set()
        math.result(timeout=2)
        interaction.result(timeout=2)
    assert order == ["solve", "interaction"]


def test_gate_releases_on_exception_and_rejects_reentrant_fault_hooks():
    gate = calculation_gate.CalculationGate()
    with pytest.raises(RuntimeError, match="reentrant_operation"), gate.operation("solve"), gate.operation("interaction"):
        pass
    with gate.operation("interaction"):
        pass
    with pytest.raises(ValueError, match="injected"), gate.operation("verification"):
        raise ValueError("injected")
    with gate.operation("solve"):
        pass


@pytest.fixture
def sessions(monkeypatch):
    """Exercise real durable reservations/settlement, with a deterministic worker."""
    calls = []

    class Session:
        def __init__(self, dispatch):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def run(self, payload, *, timeout_seconds, receipt_path, attempt_id):
            calls.append({"payload": payload, "allowance": timeout_seconds})
            status = payload.get("status", "returned")
            receipt = {"schema_version": "bounded-calculation-receipt/v1", "attempt_id": attempt_id,
                       "elapsed_seconds": 0.001, "status": status, "result": payload}
            Path(receipt_path).write_text(json.dumps(receipt))
            if status == "timeout":
                raise bounded.CalculationTimeout(elapsed_seconds=0.001)

    monkeypatch.setattr(bounded, "JsonCalculationSession", Session)
    return calls


@pytest.mark.parametrize("bucket", ["solve", "verification", "selection", "interaction"])
def test_queued_operation_has_no_reservation_or_budget_charge(tmp_path, sessions, bucket):
    store = EventStore(tmp_path, IDENTITY, create=True)
    calculator = DurableCalculations(store, TARGET, bucket, limits={bucket: 2}, dispatch=calculations.dispatch)
    with calculator, ThreadPoolExecutor(max_workers=1) as executor:
        with calculator._gate.operation("solve"):
            waiting = executor.submit(calculator.call, "one", {"value": "exact"}, bucket=bucket)
            _waiting(calculator._gate, **{"interaction" if bucket == "interaction" else "math": 1})
            summary = calculator.ledger.summary(TARGET, bucket, bucket)
            assert summary["operations"] == []
            assert summary["actual_seconds"] == summary["reserved_upper_seconds"] == 0
            assert sessions == [] and not waiting.done()
        assert waiting.result(timeout=2) == {"value": "exact"}
        summary = calculator.ledger.summary(TARGET, bucket, bucket)
        assert summary["actual_seconds"] == 0.001
        assert summary["reserved_upper_seconds"] == 0 and sessions[0]["allowance"] == 2


def test_same_run_calls_do_not_overlap_and_release_after_each_operation(tmp_path, sessions):
    store = EventStore(tmp_path, IDENTITY, create=True)
    math = DurableCalculations(store, TARGET, "math", limits={"solve": 10}, dispatch=calculations.dispatch)
    interactive = DurableCalculations(store, TARGET, "interactive", limits={"interaction": 30}, dispatch=calculations.dispatch)
    returned, release = threading.Event(), threading.Event()

    def hold_before_settlement(_attempt, _store):
        returned.set()
        assert release.wait(2)

    math.hooks["calculation_returned"] = hold_before_settlement
    with math, interactive, ThreadPoolExecutor(max_workers=2) as executor:
        try:
            result = executor.submit(math.call, "math-one", {"kind": "math"})
            assert returned.wait(2)
            future = executor.submit(interactive.call, "card-one", {"kind": "interaction"}, bucket="interaction")
            _waiting(math._gate, interaction=1)
            assert len(sessions) == 1 and not future.done()
            assert interactive.ledger.summary(TARGET, "interactive", "interaction")["operations"] == []
        finally:
            release.set()
        assert result.result(timeout=2) == {"kind": "math"}
        assert future.result(timeout=2) == {"kind": "interaction"}
        # The math session/route stays open: the gate is an operation boundary.
        assert math.call("math-two", {"kind": "math-two"}) == {"kind": "math-two"}
    assert [item["payload"]["kind"] for item in sessions] == ["math", "interaction", "math-two"]


def test_timeout_and_reused_receipt_both_release_the_gate(tmp_path, sessions):
    store = EventStore(tmp_path, IDENTITY, create=True)
    with DurableCalculations(store, TARGET, "interaction", limits={"interaction": 30},
                             dispatch=calculations.dispatch) as calculator:
        for _ in range(2):
            with pytest.raises(InteractionUnavailable):
                calculator.call("timeout", {"status": "timeout"}, bucket="interaction")
            assert calculator._gate._owner is None
        assert len(sessions) == 1, "replaying a timeout uses its receipt"
        assert calculator.call("success", {"value": 1}, bucket="interaction") == {"value": 1}
        assert calculator.call("success", {"value": 1}, bucket="interaction") == {"value": 1}
        assert calculator._gate._owner is None and len(sessions) == 2


def test_fault_after_worker_receipt_releases_gate_and_recovers_without_recomputing(tmp_path, sessions):
    store = EventStore(tmp_path, IDENTITY, create=True)

    def fail(_attempt, _store):
        raise RuntimeError("injected after receipt")

    with DurableCalculations(store, TARGET, "math", limits={"solve": 10}, dispatch=calculations.dispatch,
                             hooks={"calculation_returned": fail}) as calculator:
        with pytest.raises(RuntimeError, match="injected after receipt"):
            calculator.call("operation", {"value": 1})
        assert calculator._gate._owner is None
        assert calculator.call("operation", {"value": 1}) == {"value": 1}
        assert len(sessions) == 1
        assert BudgetLedger(store).summary(TARGET, "math", "solve")["actual_seconds"] == 0.001


def test_fault_hook_cannot_reenter_calculation_or_leave_gate_held(tmp_path, sessions):
    store = EventStore(tmp_path, IDENTITY, create=True)
    with DurableCalculations(store, TARGET, "math", limits={"solve": 10}, dispatch=calculations.dispatch) as calculator:
        calculator.hooks["calculation_returned"] = lambda *_: calculator.call("nested", {"value": 2})
        with pytest.raises(RuntimeError, match="calculation_gate.reentrant_operation"):
            calculator.call("first", {"value": 1})
        assert calculator._gate._owner is None and len(sessions) == 1
        assert calculator.call("first", {"value": 1}) == {"value": 1}
