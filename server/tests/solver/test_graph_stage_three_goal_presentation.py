"""Goal closure cards consume certified extrema without changing prior cards."""

import json
from copy import deepcopy

import pytest
import sympy as sp
from jsonschema import Draft202012Validator

from shuxueshuo_server.graph_lesson.stage_three import execution_contracts, goals
from shuxueshuo_server.graph_lesson.stage_three.contracts import ROOT
from shuxueshuo_server.graph_lesson.stage_three.presentation import (
    append_boundary,
    append_goal_finalization,
    make_fragment,
    math_step_hash,
)
from shuxueshuo_server.graph_lesson.stage_three.trajectory import encode_value


def state_with_boundary(feasible, method="method-separation"):
    state = {
        "run_id": "presentation-extremum", "lesson_version": "lesson-extremum",
        "target_ref": "/root/goals/0", "route_id": "extremum", "method": method,
        "revisions": {"presentation": "a" * 64}, "fragments": [], "premise_refs": [],
        "trajectory": {"steps": [], "finalization": [], "math_steps": []},
        "verification": {"status": "verified"}, "feasible_set_exact": encode_value(feasible),
    }
    prefix = make_fragment(state, unit_id="solution", method_ref=method + "#" +
                           execution_contracts.read("presentation-registry")["boundary_steps"][method],
                           template="solution", after=[feasible])
    state["fragments"].append(prefix)
    state["trajectory"]["math_steps"].append({"step_id": prefix["step_id"],
                                             "math_step_sha256": prefix["math_step_sha256"]})
    return append_boundary(state, {"status": "passed", "points": []}, feasible_set=feasible)


@pytest.mark.parametrize("kind,feasible,status,expected", [
    ("find_minimum", sp.Interval(-sp.Rational(5, 2), sp.oo), "attained", "最小值为"),
    ("find_maximum", sp.Interval(-sp.oo, sp.Rational(5, 2)), "attained", "最大值为"),
    ("find_minimum", sp.Interval.open(-sp.Rational(5, 2), sp.oo), "not_attained", "最小值不存在"),
    ("find_maximum", sp.Interval.open(-sp.oo, sp.Rational(5, 2)), "not_attained", "最大值不存在"),
    ("find_minimum", sp.S.Reals, "unbounded_below", "没有下界"),
    ("find_maximum", sp.S.Reals, "unbounded_above", "没有上界"),
    ("find_minimum", sp.S.EmptySet, "empty_feasible_set", "没有满足题设的参数"),
    ("find_maximum", sp.S.EmptySet, "empty_feasible_set", "没有满足题设的参数"),
    ("find_maximum", sp.FiniteSet(-1, sp.sqrt(2)), "attained", "能够取得"),
])
def test_typed_goal_card_keeps_complete_set_exact_value_and_actual_finalization_source(kind, feasible, status, expected):
    state = state_with_boundary(feasible)
    original = deepcopy(state)
    answer = goals.finalize_goal({"kind": kind}, feasible)
    evidence = goals.verify_goal_answer({"kind": kind}, feasible, answer)
    updated = append_goal_finalization(state, answer, evidence)
    assert state == original
    assert updated["fragments"][:-1] == state["fragments"]
    assert updated["trajectory"]["math_steps"][:-1] == state["trajectory"]["math_steps"]
    card = updated["fragments"][-1]
    assert card["display_unit"] == "goal_finalization"
    assert card["title"] == ("确定最小值" if kind == "find_minimum" else "确定最大值")
    assert expected in card["explanation"]
    assert card["before"][0]["exact"] == encode_value(feasible)
    assert card["math_step_sha256"] == math_step_hash(card)
    index = len(updated["finalization"]) - 1
    assert card["source_refs"] == [f"/finalization/{index}"]
    operation = updated["finalization"][index]
    assert operation["capability"] == "finalize_goal" and operation["public_ref"] is None
    assert operation["outputs"] == {"answer": answer, "evidence": evidence}
    assert operation["answer"]["status"] == status
    assert all(check["passed"] is True for check in operation["postconditions"])
    assert updated["trajectory"]["finalization"] == updated["finalization"]
    assert card["used_basis"] == ["function-range-extrema#attainability"]
    nodes = execution_contracts.load_nodes()
    assert execution_contracts.valid_ref(card["method_ref"], nodes)
    assert all(execution_contracts.valid_ref(ref, nodes) for ref in card["used_basis"])
    if status in ("attained", "not_attained"):
        value = answer["value" if status == "attained" else "bound"]
        assert card["after"] == [{"expression": value["expression"], "latex": value["latex"], "exact": value["exact"]}]
    else:
        assert card["after"] == []
    Draft202012Validator(json.loads((ROOT / "internal/schemas/graph-math-step-v2.schema.json").read_text())).validate(card)


@pytest.mark.parametrize("feasible", [sp.Interval(0, 1), sp.S.EmptySet, sp.S.Reals])
def test_range_closure_preserves_original_cards_and_legacy_record(feasible):
    state = state_with_boundary(feasible)
    original = deepcopy(state)
    answer, evidence = goals.finalize_goal_with_evidence({"kind": "find_range"}, feasible)
    updated = append_goal_finalization(state, answer, evidence)
    assert state == original
    assert updated["fragments"] == state["fragments"]
    assert updated["finalization"] == [*state["finalization"], {"capability": "finalize_goal", "answer": answer}]
    assert updated["trajectory"] == {**state["trajectory"], "finalization": updated["finalization"]}


@pytest.mark.parametrize("field,value", [("checks", []), ("checks", [{"kind": "not_proved", "passed": False}]),
                                         ("status", "unknown"), ("direction", "upper"),
                                         ("goal_kind", "find_maximum"), ("member", False),
                                         ("attained", None), ("bounded", None)])
def test_unproved_or_mismatched_closure_never_publishes_a_success_card(field, value):
    feasible = sp.Interval(0, 1)
    state = state_with_boundary(feasible)
    original = deepcopy(state)
    answer, evidence = goals.finalize_goal_with_evidence({"kind": "find_minimum"}, feasible)
    evidence[field] = value
    with pytest.raises(ValueError, match="presentation.goal_"):
        append_goal_finalization(state, answer, evidence)
    assert state == original


@pytest.mark.parametrize("mutate", [
    lambda state: state.update(verification={"status": "unknown"}),
    lambda state: state["fragments"].pop(),
    lambda state: state["fragments"][-1].update(source_refs=["/finalization/999"]),
    lambda state: state["finalization"][-1].update(postconditions=[{"passed": False}]),
])
def test_goal_card_requires_independently_verified_boundary_before_it(mutate):
    feasible = sp.Interval(0, 1)
    state = state_with_boundary(feasible)
    mutate(state)
    answer, evidence = goals.finalize_goal_with_evidence({"kind": "find_minimum"}, feasible)
    with pytest.raises(ValueError, match="presentation.goal_independent_boundary_required"):
        append_goal_finalization(state, answer, evidence)


def test_goal_card_rejects_wrong_set_missing_exact_value_and_stale_display():
    feasible = sp.Interval(0, 1)
    state = state_with_boundary(feasible)
    answer, evidence = goals.finalize_goal_with_evidence({"kind": "find_minimum"}, feasible)
    other = deepcopy(state)
    other["feasible_set_exact"] = encode_value(sp.Interval(1, 2))
    with pytest.raises(ValueError, match="goal_feasible_set_mismatch"):
        append_goal_finalization(other, answer, evidence)
    for change, error in (({"expression": "1"}, "goal_display_mismatch"),
                          ({"latex": "1"}, "goal_display_mismatch"),
                          ({"exact": None}, "goal_math_type")):
        changed = deepcopy(answer)
        changed["value"].update(change)
        with pytest.raises((ValueError, TypeError), match=error):
            append_goal_finalization(state, changed, evidence)


def test_goal_card_refuses_unknown_answer_status_and_wrong_goal_kind():
    feasible = sp.Interval(0, 1)
    state = state_with_boundary(feasible)
    answer, evidence = goals.finalize_goal_with_evidence({"kind": "find_minimum"}, feasible)
    with pytest.raises(ValueError, match="goal_evidence_unverified"):
        append_goal_finalization(state, {**answer, "status": "unknown"}, evidence)
    with pytest.raises(ValueError, match="goal_kind_unsupported"):
        append_goal_finalization(state, {**answer, "kind": "unknown"}, evidence)


def test_existing_math_fragments_keep_their_original_representation():
    feasible = sp.Interval(0, 1)
    state = state_with_boundary(feasible)
    assert all(set(value) == {"expression", "latex"} for card in state["fragments"]
               for value in [*card["before"], *card["after"]])
