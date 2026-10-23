"""Choice evidence is durable, optional and separate from mathematical answers."""

from copy import deepcopy

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import (
    choice_completion,
    execution,
    runner,
)
from shuxueshuo_server.graph_lesson.stage_three.budget import BudgetLedger
from shuxueshuo_server.graph_lesson.stage_three.handoff import (
    complete_route,
    invalidate_goal,
)
from shuxueshuo_server.graph_lesson.stage_three.math_values import latex
from shuxueshuo_server.graph_lesson.stage_three.route_calculations import (
    InteractionUnavailable,
)
from shuxueshuo_server.graph_lesson.stage_three.trajectory import (
    decode_value,
    encode_value,
)
from tests.solver.test_graph_stage_three_choice_source import candidate
from tests.solver.test_graph_stage_three_events import (
    TARGET,
    checkpoint,
    store_with_step,
)
from tests.solver.test_graph_stage_three_execution import (
    Interrupted,
    constructed_upstream,
    store,
)


def choice():
    return {"status": "matched", "kind": "single_choice", "target_ref": TARGET,
            "options": [{"label": label, "text": str(index)} for index, label in enumerate("ABCD")],
            "correct_labels": ["A"]}


def publish(saved, original_choice, **kwargs):
    return complete_route(saved, checkpoint(status="verified"),
                          route={"status": "verified", "target_ref": TARGET, "route_id": "discriminant"},
                          verification={"status": "verified"}, feasible_set="verified set",
                          answer={"kind": "find_range", "status": "set", "set": "verified set"},
                          original_choice=original_choice, commit_id=kwargs.pop("commit_id", "completion"), **kwargs)


def test_choice_survives_snapshot_and_is_bound_to_immutable_completion(tmp_path):
    saved, _ = store_with_step(tmp_path)
    result = publish(saved, choice())
    assert result["handoff"]["original_choice"] == choice()
    completion = next(event["payload"] for event in saved.events()
                      if event["payload"].get("kind") == "route_completion")
    assert completion["original_choice"] == choice()
    assert "original_choice" not in completion["answer"]
    assert saved.snapshot()["handoffs"][0]["original_choice"] == choice()
    assert saved.checkpoint(TARGET, "discriminant")["finalization"]["original_choice"] == choice()
    publish(saved, choice())
    changed = choice() | {"correct_labels": ["B"]}
    with pytest.raises(ValueError, match="handoff.immutable_route"):
        publish(saved, changed, commit_id="changed-choice")
    invalidate_goal(saved, TARGET, status="conflict", reason="independent_route_conflict", commit_id="revoke")
    assert saved.snapshot()["handoffs"][0]["available"] is False


@pytest.mark.parametrize("change", [
    {"target_ref": "/root/goals/1"}, {"correct_labels": ["Z"]}, {"correct_labels": ["A", "B"]},
    {"options": [{"label": "A", "text": "1"}, {"label": "A", "text": "2"}]},
    {"options": [{"label": "A", "text": ""}]}, {"kind": "unknown"},
])
def test_invalid_choice_metadata_never_publishes_a_letter(tmp_path, change):
    saved, _ = store_with_step(tmp_path)
    with pytest.raises(ValueError, match="invalid_original_choice"):
        publish(saved, choice() | change)
    assert not saved.snapshot()["handoffs"]


def test_choice_failure_keeps_verified_completion(tmp_path):
    saved, _ = store_with_step(tmp_path)
    failed = {"status": "unavailable", "target_ref": TARGET, "reason": "choice.timeout"}
    task = publish(saved, failed)["handoff"]
    assert task["available"] is True and task["original_choice"] == failed
    assert saved.checkpoint(TARGET, "discriminant")["status"] == "verified"


INVALID_CHOICES = [
    [], "not an object", {},
    choice() | {"options": [{"label": "A", "text": "1"}]},
    choice() | {"options": [{"label": "A", "text": "1"}, {"label": "A", "text": "2"}]},
    choice() | {"options": [{"label": " ", "text": "1"}, {"label": "B", "text": "2"}]},
    choice() | {"options": [{"label": "A"}, {"label": "B", "text": "2"}]},
    choice() | {"correct_labels": ["Z"]},
    choice() | {"target_ref": "/root/goals/1"},
    choice() | {"kind": "multiple_choice"},
    choice() | {"volatile_diagnostic": "worker-specific failure"},
    {"status": "unavailable", "target_ref": TARGET, "reason": " "},
    {"status": "unavailable", "target_ref": TARGET, "reason": "failure", "timestamp": 123},
]


@pytest.mark.parametrize("invalid", INVALID_CHOICES)
def test_malformed_optional_result_normalizes_to_one_stable_unavailable_value(invalid):
    before = deepcopy(invalid)
    result = choice_completion.normalize_original_choice(invalid, TARGET)
    assert result == {"status": "unavailable", "target_ref": TARGET, "reason": "choice.invalid_result"}
    assert invalid == before


@pytest.mark.parametrize("valid", [None, choice(), {
    "status": "unavailable", "target_ref": TARGET, "reason": "choice.multiple_selection_unsupported",
}])
def test_optional_result_normalization_preserves_valid_evidence(valid):
    assert choice_completion.normalize_original_choice(valid, TARGET) == valid


def test_different_malformed_results_have_the_same_immutable_completion_hash(tmp_path):
    saved, _ = store_with_step(tmp_path)
    first = publish(saved, choice_completion.normalize_original_choice(INVALID_CHOICES[3], TARGET))
    before = saved.events()
    repeated = publish(saved, choice_completion.normalize_original_choice(INVALID_CHOICES[4], TARGET),
                       commit_id="retry-with-another-invalid-payload")
    assert repeated["handoff"] == first["handoff"]
    assert saved.events() == before


def test_invalid_optional_result_keeps_verified_route_through_completion_recovery(tmp_path, monkeypatch):
    source = constructed_upstream(tmp_path, candidate())
    output = tmp_path / "out"
    returned = iter([INVALID_CHOICES[3], INVALID_CHOICES[4]])
    monkeypatch.setattr(execution, "resolve_original_choice", lambda *_args: next(returned))
    complete = execution.complete_route
    attempts = []

    def interrupted_completion(*args, **kwargs):
        attempts.append(kwargs["original_choice"])
        if len(attempts) == 1:
            raise Interrupted()
        return complete(*args, **kwargs)

    monkeypatch.setattr(execution, "complete_route", interrupted_completion)
    with pytest.raises(Interrupted):
        runner.run_sample(source, output, milestone="1b-1")
    assert not store(output).snapshot()["handoffs"]
    result = runner.resume_sample(output)
    route, = result["goals"][0]["routes"]
    assert result["status"] == "completed" and route["status"] == "verified", result
    assert decode_value(route["feasible_set_exact"]) == sp.Union(sp.Interval(-sp.oo, -2), sp.Interval(2, sp.oo))
    assert attempts == [{"status": "unavailable", "target_ref": TARGET,
                         "reason": "choice.invalid_result"}] * 2
    saved = store(output)
    task, = saved.snapshot()["handoffs"]
    assert task["available"] and task["original_choice"] == attempts[0]
    events = saved.events()
    runner.resume_sample(output)
    assert saved.events() == events
    assert saved.snapshot()["handoffs"] == [task]


@pytest.mark.parametrize("failure,reason", [
    (InteractionUnavailable("timeout"), "choice.timeout"),
    (InteractionUnavailable("budget_unavailable"), "choice.budget_unavailable"),
    (InteractionUnavailable("receipt_missing"), "choice.receipt_missing"),
    (ValueError("malformed option"), "choice.matching_error"),
])
def test_optional_matching_failure_uses_its_own_budget_and_returns_unavailable(monkeypatch, failure, reason):
    observed = []

    class Calculator:
        def __init__(self, saved, target, route, **kwargs):
            observed.append((saved, target, route, kwargs))

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def call(self, *_args, **kwargs):
            assert kwargs["bucket"] == "interaction"
            raise failure

    monkeypatch.setattr(choice_completion, "DurableCalculations", Calculator)
    answer = {"kind": "find_range", "status": "set", "set": "verified"}
    before = deepcopy(answer)
    result = choice_completion.resolve_original_choice(None, candidate(), TARGET, "route", answer, {})
    assert result == {"status": "unavailable", "target_ref": TARGET, "reason": reason}
    assert answer == before
    assert observed[0][2] == "route#original-choice"
    assert observed[0][3]["limits"] == {"interaction": 5.0}
    assert "hooks" not in observed[0][3]


@pytest.mark.parametrize("source,reason", [
    ({"status": "unavailable"}, "choice.incomplete_options"),
    ({"status": "unavailable", "reason": "choice.ambiguous_scope"}, "choice.ambiguous_scope"),
])
def test_unavailable_choice_source_uses_the_same_reason_namespace(monkeypatch, source, reason):
    monkeypatch.setattr(choice_completion, "choice_source", lambda *_: source)
    result = choice_completion.resolve_original_choice(None, candidate(), TARGET, "route", {}, {})
    assert result == {"status": "unavailable", "target_ref": TARGET, "reason": reason}


def test_student_or_is_chinese_without_changing_grouping_or_math():
    m, n = sp.symbols("m n", real=True)
    value = sp.And(m > 0, sp.Or(n < -2, n > 2))
    rendered = latex(value)
    assert r"\text{或}" in rendered and r"\vee" not in rendered
    assert r"\left(" in rendered and r"\right)" in rendered
    assert value == sp.And(m > 0, sp.Or(n < -2, n > 2))


@pytest.mark.parametrize("set_builder", [False, True])
def test_verified_exam_result_matches_original_choice_and_receipt_is_reused(tmp_path, set_builder):
    problem = candidate()
    expected = sp.Union(sp.Interval(-sp.oo, -2), sp.Interval(2, sp.oo))
    label = "A"
    if set_builder:
        problem = {
            "original_text": r"求实数 $k$ 的取值范围。A. $\{k\mid k<-4\}$ B. $\{k\mid k>0\}$ "
                             r"C. $\{k\mid -4<k<0\}$ D. $\{k\mid k<-4\text{ 或 }k>0\}$",
            "root": {"facts": ["∃x∈ℝ: k*x^2-k*x-1>0"],
                     "goals": [{"kind": "find_range", "symbol": "k"}]},
        }
        expected = sp.Union(sp.Interval.open(-sp.oo, -4), sp.Interval.open(0, sp.oo))
        label = "D"
    source = constructed_upstream(tmp_path, problem)
    output = tmp_path / "out"
    result = runner.run_sample(source, output, milestone="1b-1")
    assert result["status"] == "completed", result
    route = result["goals"][0]["routes"][0]
    assert route["status"] == "verified", route
    assert decode_value(route["feasible_set_exact"]) == expected
    saved = store(output)
    completion = next(event["payload"] for event in saved.events()
                      if event["payload"].get("kind") == "route_completion")
    assert completion["original_choice"]["correct_labels"] == [label]
    assert "original_choice" not in route["answer"]
    ledger = BudgetLedger(saved)
    before = ledger.summary(TARGET, route["route_id"] + "#original-choice", "interaction")
    matched = choice_completion.resolve_original_choice(
        saved, problem, TARGET, route["route_id"], route["answer"], encode_value(expected),
    )
    assert matched == completion["original_choice"]
    assert ledger.summary(TARGET, route["route_id"] + "#original-choice", "interaction") == before
    assert len(before["operations"]) == 1
