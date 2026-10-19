"""Actual process deadlines and durable accounting at the route boundary."""

import time

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import execution, runner, verification
from shuxueshuo_server.graph_lesson.stage_three.events import EventStore
from tests.solver.test_graph_stage_three_contracts import upstream
from tests.solver.test_graph_stage_three_execution import (
    TARGET,
    Interrupted,
    constructed_upstream,
    events,
    read,
    simple,
    store,
)


def slow_calculation(*args):
    time.sleep(60)
    raise AssertionError("a timed-out worker must never reach this statement")


def unavailable_calculation(*args):
    raise verification.VerificationGap("verification_incomplete:injected_sympy_failure")


def mismatched_context(*args):
    raise verification.ContextMismatch("injected_context_mismatch")


def broken_calculation(*args):
    raise KeyError("local_programming_bug")


def test_nested_radical_parameter_domain_finishes_within_route_budget(tmp_path):
    candidate = simple("a∈[sqrt(1+sqrt(2)),5]", "∀x∈ℝ:x^2+a-1>=0")
    source = constructed_upstream(tmp_path, candidate)
    output = tmp_path / "out"
    started = time.monotonic()
    result = runner.run_sample(source, output, milestone="1b-1", verification_budget_seconds=6)
    elapsed = time.monotonic() - started
    route, = result["goals"][0]["routes"]
    assert route["status"] in ("verified", "capability_gap"), route
    assert elapsed < 12, "the original 103-second algebraic field path must not occupy the process"
    if route["status"] == "verified":
        assert route["answer"]["set"]["expression"] == sp.sstr(sp.Interval(sp.sqrt(1+sp.sqrt(2)), 5))
    else:
        assert any("verification_incomplete" in item["code"] for item in route["diagnostics"])


@pytest.mark.parametrize("operation", ["apply_visible_constraints", "verify", "endpoint_check", "_finish_answer"])
def test_each_verification_phase_has_a_real_deadline_and_cannot_publish_completion(tmp_path, monkeypatch, operation):
    monkeypatch.setattr(execution if operation == "_finish_answer" else verification, operation, slow_calculation)
    output = tmp_path / "out"
    started = time.monotonic()
    result = runner.run_sample(upstream(tmp_path), output, milestone="1b-1", verification_budget_seconds=3)
    elapsed = time.monotonic() - started
    route, = result["goals"][0]["routes"]
    assert route["status"] == "capability_gap", route
    assert any("verification_incomplete:timeout:" in d["code"] for d in route["diagnostics"])
    assert elapsed < 9
    durable = store(output)
    checkpoint = durable.checkpoint(TARGET, "discriminant")
    state = checkpoint["driver_state"]
    assert state["verification_seconds"] >= 3
    assert state["verification_timing"][-1]["status"] == "timeout"
    assert state["verification_seconds"] == pytest.approx(sum(t["elapsed_seconds"] for t in state["verification_timing"]))
    assert not durable.snapshot()["handoffs"]
    assert len(durable.snapshot()["math_steps"]) == (5 if operation == "_finish_answer" else 4)
    committed = events(output)
    runner.resume_sample(output)
    assert events(output) == committed
    assert durable.checkpoint(TARGET, "discriminant")["driver_state"]["verification_seconds"] == state["verification_seconds"]


@pytest.mark.parametrize("calculation,status", [
    (unavailable_calculation, "capability_gap"),
    (mismatched_context, "math_failed"),
    (broken_calculation, "execution_error"),
])
def test_worker_failure_preserves_gap_mismatch_and_programming_error_categories(tmp_path, monkeypatch, calculation, status):
    monkeypatch.setattr(verification, "apply_visible_constraints", calculation)
    output = tmp_path / "out"
    result = runner.run_sample(upstream(tmp_path), output, milestone="1b-1")
    route, = result["goals"][0]["routes"]
    assert route["status"] == status, route
    artifact = read(output / route["trajectory"])
    failure = artifact["verification_timing"]["operations"][-1]
    assert failure["status"] == "worker_error" and failure["traceback"]
    assert failure["elapsed_seconds"] > 0
    assert failure["exception_type"] == {
        "capability_gap": "VerificationGap", "math_failed": "ContextMismatch", "execution_error": "KeyError",
    }[status]
    assert not store(output).snapshot()["handoffs"]


def test_resume_keeps_committed_budget_and_passes_only_remaining_time(tmp_path):
    output = tmp_path / "out"

    def interrupt_after_constraints(state, durable):
        raise Interrupted()

    with pytest.raises(Interrupted):
        runner.run_sample(upstream(tmp_path), output, milestone="1b-1",
                          hooks={"before_verification": interrupt_after_constraints})
    first = store(output).checkpoint(TARGET, "discriminant")["driver_state"]
    assert first["verification_seconds"] > 0
    assert [t["operation"] for t in first["verification_timing"]] == ["apply_visible_constraints"]
    result = runner.resume_sample(output)
    assert result["goals"][0]["status"] == "solved"
    state = store(output).checkpoint(TARGET, "discriminant")["driver_state"]
    timing = state["verification_timing"]
    assert timing[0] == first["verification_timing"][0]
    assert [t["operation"] for t in timing] == [
        "apply_visible_constraints", "independent_verification", "endpoint_check", "goal_finalize_and_consistency",
    ]
    consumed = 0
    for item in timing:
        assert item["timeout_seconds"] == pytest.approx(20-consumed)
        consumed += item["elapsed_seconds"]
        assert item["cumulative_seconds"] == pytest.approx(consumed)
    assert state["verification_seconds"] == pytest.approx(consumed)


def test_exhausted_accumulated_budget_does_not_start_another_worker(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("budget is already exhausted")

    monkeypatch.setattr(execution.bounded, "run_bounded", forbidden)
    state = {"verification_seconds": 2, "verification_budget_seconds": 2}
    with pytest.raises(verification.VerificationGap, match="budget_exhausted"):
        execution._run_verification(state, "endpoint_check", verification.endpoint_check)
    assert state["verification_seconds"] == 2
    assert state["verification_timing"][-1]["status"] == "timeout"


def test_custom_budget_is_durable_from_first_route_commit(tmp_path):
    output = tmp_path / "out"
    identities = []

    def interrupt_at_start(state, durable):
        identities.append(durable.identity)
        raise Interrupted()

    with pytest.raises(Interrupted):
        runner.run_sample(upstream(tmp_path), output, milestone="1b-1", verification_budget_seconds=8,
                          hooks={"after_commit": interrupt_at_start})
    # The database commit precedes the debug export; a crash in this seam can
    # legitimately leave no checkpoint.json. Read the authoritative store.
    initial = EventStore(output, identities[0]).checkpoint(TARGET, "discriminant")["driver_state"]
    assert initial["verification_budget_seconds"] == 8
    result = runner.resume_sample(output)
    assert result["goals"][0]["status"] == "solved"
    resumed = store(output).checkpoint(TARGET, "discriminant")["driver_state"]
    assert resumed["verification_budget_seconds"] == 8
    assert resumed["verification_timing"][0]["timeout_seconds"] == 8
