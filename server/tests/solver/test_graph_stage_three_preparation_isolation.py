"""Preparation must be bounded before any route checkpoint exists."""

import json
import os
from time import monotonic

import pytest

from shuxueshuo_server.graph_lesson.stage_three import runner
from shuxueshuo_server.graph_lesson.stage_three.budget import BudgetLedger
from shuxueshuo_server.graph_lesson.stage_three.preparation import PREPARATION_ROUTE
from shuxueshuo_server.graph_lesson.stage_three.preview import open_store
from tests.solver.stage_three_preparation_probes import hooks
from tests.solver.test_graph_stage_three_resilience import upstream

FIRST = "/root/children/0/goals/0"
SECOND = "/root/children/1/goals/0"


def read(path):
    return json.loads(path.read_text())


def assert_reaped(pid_file):
    assert pid_file.exists(), "probe must reach the calculation, not just time out during process startup"
    pid = int(pid_file.read_text())
    assert pid != os.getpid()
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


@pytest.mark.parametrize("phase", ["build_context", "evaluate_goal"])
def test_one_selection_timeout_is_a_gap_and_other_target_continues(tmp_path, phase):
    source = upstream(tmp_path)
    output, pid = tmp_path / "out", tmp_path / "worker.pid"
    started = monotonic()
    result = runner.run_sample(source, output, milestone="1a", selection_budget_seconds=2,
        hooks=hooks(phase, target_ref=FIRST, sleep=30, pid_file=str(pid)))
    assert monotonic() - started < 9
    assert_reaped(pid)
    failed, continued = result["goals"]
    assert failed["status"] == "capability_gap" and not failed["routes"] and failed["answer"] is None
    assert failed["diagnostics"][0]["phase"] == phase
    assert failed["diagnostics"][0]["code"] == "preparation.budget_exhausted"
    assert continued["status"] == "no_verified_route" and continued["d3"]
    assert result["preparation"]["targets"][FIRST]["operations"][-1]["outcome"] == "timeout"
    assert result["preparation"]["targets"][SECOND]["operations"][-1]["outcome"] == "returned"
    assert read(output / "stage-three-result.json") == result
    assert "preparation.budget_exhausted" in (output / "index.html").read_text()
    assert not any(result["llm"].values())


def test_admission_timeout_has_an_inspectable_report(tmp_path):
    source = upstream(tmp_path)
    output, pid = tmp_path / "out", tmp_path / "admission.pid"
    started = monotonic()
    result = runner.run_sample(source, output, admission_budget_seconds=2,
        hooks=hooks("admission", sleep=30, pid_file=str(pid)))
    assert monotonic() - started < 7
    assert_reaped(pid)
    assert result["status"] == "input_error" and result["goals"] == []
    assert result["input_diagnostics"][0]["code"] == "input.admission_timeout"
    assert result["preparation"]["admission"][0]["status"] == "timeout"
    assert (output / "index.html").is_file()


def test_admission_programming_failure_is_not_a_mathematical_gap(tmp_path):
    result = runner.run_sample(upstream(tmp_path), tmp_path / "out",
        hooks=hooks("admission", error="KeyError", message="broken admission adapter"))
    assert result["status"] == "input_error"
    diagnostic = result["input_diagnostics"][0]
    assert diagnostic["code"] == "input.admission_error" and diagnostic["exception_type"] == "KeyError"
    assert "broken admission adapter" in diagnostic["traceback"]


def test_selection_usage_accumulates_across_resume(tmp_path):
    source = upstream(tmp_path)
    output = tmp_path / "out"
    # Keep this a preparation test: fail before route creation on both runs.
    injected = hooks("evaluate_goal", error="KeyError")
    initial = runner.run_sample(source, output, hooks=injected)
    resumed = runner.resume_sample(output, hooks=injected)
    assert initial["status"] == resumed["status"] == "failed"
    ledger = BudgetLedger(open_store(output))
    for ref in (FIRST, SECOND):
        before, after = initial["preparation"]["targets"][ref], resumed["preparation"]["targets"][ref]
        assert len(before["operations"]) == 2 and len(after["operations"]) == 4
        assert after["actual_seconds"] > before["actual_seconds"] > 0
        assert after == ledger.summary(ref, PREPARATION_ROUTE, "selection")
        assert after["remaining_seconds"] < before["remaining_seconds"]


def test_resume_admission_timeout_revokes_previous_handoff_and_preserves_history(tmp_path):
    from tests.solver.test_graph_stage_three_contracts import upstream as q01_upstream

    output, pid = tmp_path / "out", tmp_path / "resume-admission.pid"
    initial = runner.run_sample(q01_upstream(tmp_path), output, milestone="1b-1", admission_budget_seconds=2)
    assert initial["goals"][0]["status"] == "solved"
    before = open_store(output).snapshot()
    resumed = runner.resume_sample(output, hooks=hooks("admission", sleep=30, pid_file=str(pid)))
    assert_reaped(pid)
    assert resumed["status"] == "input_error"
    assert resumed["input_diagnostics"][0]["code"] == "input.admission_timeout"
    assert resumed["goals"] == []
    assert resumed["retained_goals"][0]["answer"] is None
    assert resumed["retained_goals"][0]["d3"] == initial["goals"][0]["d3"]
    after = open_store(output).snapshot()
    assert after["math_steps"] == before["math_steps"]
    assert all(not task["available"] for task in after["handoffs"])
    assert len(resumed["preparation"]["admission"]) == 2
    again = runner.resume_sample(output, hooks=hooks("admission", error="ValueError"))
    assert len(again["preparation"]["admission"]) == 3
    assert "input.admission_error" in (output / "index.html").read_text()


def test_resume_without_aggregate_result_revokes_goal_and_handoff_mirrors(tmp_path):
    from tests.solver.test_graph_stage_three_contracts import upstream as q01_upstream

    output = tmp_path / "out"
    initial = runner.run_sample(q01_upstream(tmp_path), output, milestone="1b-1")
    result_path = output / "stage-three-result.json"
    tampered = {**initial, "milestone": "6"}
    result_path.write_text(json.dumps(tampered))
    with pytest.raises(ValueError, match="checkpoint.result_identity_changed"):
        runner.resume_sample(output)
    result_path.unlink()
    resumed = runner.resume_sample(output, hooks=hooks("admission", error="ValueError"))
    assert resumed["status"] == "input_error" and resumed["goals"] == []
    assert resumed["retained_goals"][0]["answer"] is None
    mirror = read(output / "goals/goal-001/goal.json")
    assert mirror["status"] == "execution_error" and mirror["answer"] is None
    tasks = list((output / "goals/goal-001/handoff").glob("*.json"))
    assert tasks and all(not read(path)["available"] for path in tasks)


@pytest.mark.parametrize("name", ["admission_budget_seconds", "selection_budget_seconds"])
@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan")])
def test_preparation_budgets_are_validated_before_creating_output(tmp_path, name, value):
    output = tmp_path / "out"
    with pytest.raises(ValueError, match="invalid_options"):
        runner.run_sample("unused", output, **{name: value})
    assert not output.exists()
