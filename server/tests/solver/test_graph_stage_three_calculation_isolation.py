"""Production route math stays outside the publishing process."""

import time

import pytest

from shuxueshuo_server.graph_lesson.stage_three import (
    calculations,
    driver,
    route_constraints,
    runner,
    trajectory,
    verification,
)
from shuxueshuo_server.graph_lesson.stage_three.bounded import CalculationWorkerError
from shuxueshuo_server.graph_lesson.stage_three.events import EventStore
from shuxueshuo_server.graph_lesson.stage_three.route_calculations import (
    RouteCalculations,
)
from tests.solver.graph_stage_three_faults import offline_dispatch
from tests.solver.test_graph_stage_three_contracts import upstream
from tests.solver.test_graph_stage_three_events import IDENTITY
from tests.solver.test_graph_stage_three_execution import TARGET, read, store


def slow_after_first_fragment(payload):
    if payload["operation"] == "advance" and payload["state"]["fragments"]:
        time.sleep(60)
    return offline_dispatch(payload)


def test_route_parent_never_constructs_or_renders_symbolic_objects(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("route mathematics escaped its worker")

    for module, names in (
        (driver, ("create_state", "can_execute", "advance", "export_values", "append_endpoint")),
        (trajectory, ("encode_value", "decode_value")),
        (verification, ("verify", "endpoint_check", "math_value")),
        (route_constraints, ("apply_visible_constraints",)),
        (calculations, ("finalize_goal_with_evidence", "verify_goal_answer", "append_goal_finalization", "consistency")),
    ):
        for name in names:
            monkeypatch.setattr(module, name, forbidden)
    result = runner.run_sample(upstream(tmp_path), tmp_path / "out")
    assert result["goals"][0]["status"] == "solved"
    assert all(route["status"] == "verified" for route in result["goals"][0]["routes"])


def test_solve_deadline_kills_nonreturning_method_and_preserves_committed_prefix(tmp_path):
    output = tmp_path / "out"
    started = time.monotonic()
    result = runner.run_sample(upstream(tmp_path), output, milestone="1b-1", solve_budget_seconds=4,
                               hooks={"calculation_dispatch": slow_after_first_fragment})
    elapsed = time.monotonic()-started
    route, = result["goals"][0]["routes"]
    assert route["status"] == "execution_error", route
    assert any("solve_timeout" in row.get("message", "") for row in route["diagnostics"])
    assert elapsed < 10
    durable = store(output)
    assert durable.snapshot()["math_steps"] and not durable.snapshot()["handoffs"]
    state = durable.checkpoint(TARGET, "discriminant")["driver_state"]
    assert state["compute_seconds"] >= 4
    assert state["solve_timing"][-1]["status"] == "timeout"
    artifact = read(output / route["trajectory"])
    assert artifact["budget_accounting"]["solve"]["reserved_upper_seconds"] == 0
    assert artifact["solve_timing"]["elapsed_seconds"] == state["compute_seconds"]
    before = durable.events()
    runner.resume_sample(output)
    assert durable.events() == before


def test_receipt_storage_failure_stays_visible_instead_of_becoming_math_gap(tmp_path, monkeypatch):
    error = CalculationWorkerError(exception_type="OSError", exception_module="builtins", message="disk failure",
                                   traceback="original supervisor traceback", phase="settlement", elapsed_seconds=0.1)

    def cannot_write_receipt(*args, **kwargs):
        raise error

    durable = EventStore(tmp_path, IDENTITY, create=True)
    with RouteCalculations(durable, TARGET, "discriminant", solve_budget_seconds=10,
                           verification_budget_seconds=20) as calculation:
        monkeypatch.setattr(calculation.session, "run", cannot_write_receipt)
        with pytest.raises(CalculationWorkerError) as caught:
            calculation.call("independent_verification", {"operation": "verify"}, bucket="verification")
        assert caught.value is error
        state = calculation.sync_state({})
        assert state["budget_accounting"]["verification"]["actual_seconds"] == 0
        assert state["budget_accounting"]["verification"]["reserved_upper_seconds"] == 20
    assert not durable.snapshot()["handoffs"]
