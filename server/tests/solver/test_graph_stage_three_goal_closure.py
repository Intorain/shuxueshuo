"""Exact closure of verified feasible sets into the unchanged original goal."""

import json
from copy import deepcopy

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import goals
from shuxueshuo_server.graph_lesson.stage_three.goals import (
    GoalClosureMismatch,
    equivalent_answers,
    finalize_goal,
    finalize_goal_with_evidence,
    verify_goal_answer,
)
from shuxueshuo_server.graph_lesson.stage_three.trajectory import (
    decode_value,
    encode_value,
)
from shuxueshuo_server.graph_lesson.stage_three.verification import VerificationGap


@pytest.mark.parametrize("kind,feasible,status,value", [
    ("find_minimum", sp.Interval(-sp.Rational(5, 2), sp.oo), "attained", -sp.Rational(5, 2)),
    ("find_maximum", sp.Interval(-sp.oo, sp.Rational(5, 2)), "attained", sp.Rational(5, 2)),
    ("find_minimum", sp.Interval.open(-sp.Rational(5, 2), sp.oo), "not_attained", -sp.Rational(5, 2)),
    ("find_maximum", sp.Interval(-sp.Rational(5, 2), sp.oo), "unbounded_above", None),
    ("find_minimum", sp.S.EmptySet, "empty_feasible_set", None),
    ("find_maximum", sp.S.EmptySet, "empty_feasible_set", None),
    ("find_minimum", sp.S.Reals, "unbounded_below", None),
    ("find_maximum", sp.S.Reals, "unbounded_above", None),
    ("find_minimum", sp.Interval.open(-sp.oo, 1), "unbounded_below", None),
    ("find_maximum", sp.Interval.open(-sp.oo, 1), "not_attained", sp.S.One),
    ("find_minimum", sp.Interval.Ropen(0, 1), "attained", sp.S.Zero),
    ("find_maximum", sp.Interval.Ropen(0, 1), "not_attained", sp.S.One),
    ("find_minimum", sp.FiniteSet(3), "attained", sp.Integer(3)),
    ("find_maximum", sp.FiniteSet(3), "attained", sp.Integer(3)),
    ("find_minimum", sp.FiniteSet(-sp.sqrt(3), -sp.sqrt(2), 5), "attained", -sp.sqrt(3)),
    ("find_maximum", sp.FiniteSet(-5, sp.sqrt(2), sp.sqrt(3)), "attained", sp.sqrt(3)),
    ("find_minimum", sp.Union(sp.Interval.open(-2, -1), sp.Interval(1, 3)), "not_attained", -sp.Integer(2)),
    ("find_maximum", sp.Union(sp.Interval.open(-2, -1), sp.Interval(1, 3)), "attained", sp.Integer(3)),
    ("find_minimum", sp.Union(sp.FiniteSet(-5), sp.Interval.open(-2, -1)), "attained", -sp.Integer(5)),
    ("find_maximum", sp.Union(sp.FiniteSet(5), sp.Interval.open(-2, -1)), "attained", sp.Integer(5)),
    ("find_minimum", sp.Union(sp.Interval.open(-sp.oo, -1), sp.Interval(2, 3)), "unbounded_below", None),
    ("find_maximum", sp.Union(sp.Interval(-3, -2), sp.Interval.open(1, sp.oo)), "unbounded_above", None),
    ("find_minimum", sp.Interval(sp.sqrt(1+sp.sqrt(2)), 3), "attained", sp.sqrt(1+sp.sqrt(2))),
    ("find_maximum", sp.Interval.open(0, sp.sqrt(1+sp.sqrt(2))), "not_attained", sp.sqrt(1+sp.sqrt(2))),
])
def test_extremum_status_and_exact_boundary(kind, feasible, status, value):
    original_goal = {"kind": kind, "expression": "a", "source": "original"}
    unchanged = deepcopy(original_goal)
    answer, evidence = finalize_goal_with_evidence(original_goal, feasible)
    assert original_goal == unchanged
    assert answer["kind"] == kind and answer["status"] == status
    assert answer == finalize_goal(original_goal, feasible)
    assert evidence["kind"] == "goal_closure" and evidence["status"] == status
    assert evidence["direction"] == ("lower" if kind == "find_minimum" else "upper")
    assert decode_value(evidence["feasible_set"]["exact"]) == feasible
    assert evidence["checks"] and all(row["passed"] is True for row in evidence["checks"])
    assert json.loads(json.dumps((answer, evidence))) == [answer, evidence]
    if value is not None:
        field = "value" if status == "attained" else "bound"
        assert set(answer) == {"kind", "status", field}
        assert decode_value(answer[field]["exact"]) == value
        assert answer[field]["expression"] == sp.sstr(value)
        assert answer[field]["latex"] == sp.latex(value)
        assert evidence["bounded"] is True
        assert evidence["member"] is evidence["attained"] is (status == "attained")
        assert decode_value(evidence["bound"]["exact"]) == value
    else:
        assert set(answer) == {"kind", "status"}
        if status == "empty_feasible_set":
            assert evidence["empty"] is True
            assert all(evidence[key] is None for key in ("bound", "bounded", "member", "attained"))
        else:
            assert evidence["bounded"] is False
            assert evidence["member"] is evidence["attained"] is False
            assert decode_value(evidence["bound"]["exact"]) == (-sp.oo if kind == "find_minimum" else sp.oo)


@pytest.mark.parametrize("feasible", [sp.S.EmptySet, sp.S.Reals, sp.Interval.Ropen(0, 1),
                                     sp.FiniteSet(-1, 3), sp.S.Reals-sp.FiniteSet(0)])
def test_range_wire_format_does_not_change(feasible):
    expected = {"kind": "find_range", "status": "set",
                "set": {"expression": sp.sstr(feasible), "latex": sp.latex(feasible)}}
    answer, evidence = finalize_goal_with_evidence({"kind": "find_range"}, feasible)
    assert answer == expected == finalize_goal({"kind": "find_range"}, feasible)
    assert evidence["checks"] == [{"kind": "range_identity", "passed": True}]


def test_union_endpoint_attainment_uses_the_complete_set():
    feasible = sp.Union(sp.Interval.open(0, 1), sp.FiniteSet(0), evaluate=False)
    answer, evidence = finalize_goal_with_evidence({"kind": "find_minimum"}, feasible)
    assert answer["status"] == "attained"
    assert decode_value(answer["value"]["exact"]) == 0
    assert evidence["checks"][0]["component_count"] == 2
    assert len(evidence["checks"][1]["components"]) == 2
    assert evidence["member"] is True


@pytest.mark.parametrize("kind", ["find_minimum", "find_maximum"])
@pytest.mark.parametrize("feasible", [
    sp.FiniteSet(sp.Symbol("unknown", real=True)),
    sp.Interval(sp.Symbol("unknown", real=True), sp.oo),
    sp.FiniteSet(sp.Float("0.1")), sp.FiniteSet(sp.pi),
    sp.FiniteSet(sp.oo), sp.FiniteSet(-sp.oo),
    sp.S.Integers,
    sp.ConditionSet(sp.Symbol("t", real=True), sp.Eq(sp.sin(sp.Symbol("t", real=True)), 0), sp.S.Reals),
])
def test_unsupported_or_unknown_set_is_a_gap(kind, feasible):
    with pytest.raises(VerificationGap):
        finalize_goal({"kind": kind}, feasible)


def test_unknown_membership_never_means_not_attained(monkeypatch):
    monkeypatch.setattr(goals, "_contains_exact", lambda *args: None)
    with pytest.raises(VerificationGap, match="bound_membership_unknown"):
        finalize_goal({"kind": "find_minimum"}, sp.Interval(0, 1))


def test_unsupported_exact_encoding_is_a_gap(monkeypatch):
    def unsupported(value):
        raise ValueError("checkpoint.unsupported_math:future_type")

    monkeypatch.setattr(goals, "encode_value", unsupported)
    with pytest.raises(VerificationGap, match="exact_value_encoding_unsupported"):
        finalize_goal({"kind": "find_minimum"}, sp.Interval(0, 1))
    # Range closure never adds a codec requirement to its legacy contract.
    assert finalize_goal({"kind": "find_range"}, sp.Interval(0, 1))["status"] == "set"


def test_bad_goal_kind_and_nonset_remain_explicit_errors():
    with pytest.raises(VerificationGap, match="unsupported_kind"):
        finalize_goal({"kind": "compute"}, sp.Interval(0, 1))
    with pytest.raises(TypeError, match="expected_set"):
        finalize_goal({"kind": "find_minimum"}, [0, 1])


def _answer(kind="find_minimum", status="attained", value=None):
    value = sp.sqrt(2) if value is None else value
    field = "value" if status == "attained" else "bound"
    return {"kind": kind, "status": status,
            field: {"expression": sp.sstr(value), "latex": sp.latex(value), "exact": encode_value(value)}}


@pytest.mark.parametrize("status", ["attained", "not_attained"])
def test_answer_equivalence_uses_exact_value_and_ignores_display(status):
    first = _answer(status=status)
    equivalent = _answer(status=status, value=sp.Mul(sp.Rational(1, 2), sp.sqrt(8), evaluate=False))
    field = "value" if status == "attained" else "bound"
    equivalent[field]["expression"] = "this text is not parsed"
    equivalent[field]["latex"] = "different rendering"
    assert equivalent_answers(first, equivalent) is True
    different = _answer(status=status, value=sp.sqrt(3))
    different[field]["expression"] = first[field]["expression"]
    different[field]["latex"] = first[field]["latex"]
    assert equivalent_answers(first, different) is False


def test_answer_equivalence_retains_goal_and_status():
    first = _answer()
    assert equivalent_answers(first, _answer(kind="find_maximum")) is False
    assert equivalent_answers(first, _answer(status="not_attained")) is False
    for kind, status in (("find_minimum", "unbounded_below"), ("find_maximum", "unbounded_above"),
                         ("find_minimum", "empty_feasible_set"), ("find_maximum", "empty_feasible_set")):
        assert equivalent_answers({"kind": kind, "status": status}, {"kind": kind, "status": status}) is True


def test_range_equivalence_requires_caller_to_compare_exact_feasible_sets():
    first = finalize_goal({"kind": "find_range"}, sp.S.Reals)
    second = deepcopy(first)
    second["set"] = {"expression": "Interval(-oo, oo)", "latex": "different rendering"}
    assert equivalent_answers(first, second) is True


@pytest.mark.parametrize("payload", [
    {"expression": "sqrt(2)", "latex": "ignored"},
    {"exact": {"$math": "unregistered"}},
    {"exact": {"$math": "Integer", "value": "not an integer"}},
    {"exact": encode_value(sp.oo)},
    {"exact": encode_value(sp.Symbol("a", real=True))},
    {"exact": "sqrt(2)"},
])
def test_unproved_answer_equality_is_a_gap_and_never_parses_expression(payload):
    bad = {"kind": "find_minimum", "status": "attained", "value": payload}
    with pytest.raises(VerificationGap):
        equivalent_answers(bad, _answer())


@pytest.mark.parametrize("answer", [
    {"kind": "find_minimum", "status": "unbounded_above"},
    {"kind": "find_maximum", "status": "unbounded_below"},
    {"kind": "find_minimum", "status": "unbounded_below", "value": {"exact": encode_value(-sp.oo)}},
    {"kind": "find_minimum", "status": "unknown"},
])
def test_invalid_answer_status_or_infinite_value_is_not_equivalent(answer):
    with pytest.raises(VerificationGap):
        equivalent_answers(answer, deepcopy(answer))


@pytest.mark.parametrize("change", ["kind", "status", "value", "bound"])
def test_given_extremum_answer_is_checked_against_original_goal_and_set(change):
    goal, feasible = {"kind": "find_minimum"}, sp.Interval(-sp.Rational(5, 2), sp.oo)
    correct = finalize_goal(goal, feasible)
    assert verify_goal_answer(goal, feasible, correct)["checks"][-1]["passed"] is True
    bad = deepcopy(correct)
    if change == "kind":
        bad["kind"] = "find_maximum"
    elif change == "status":
        bad["status"] = "not_attained"
        bad["bound"] = bad.pop("value")
    elif change == "value":
        bad["value"]["exact"] = encode_value(sp.Rational(5, 2))
    else:
        feasible = sp.Interval.open(-sp.Rational(5, 2), sp.oo)
    with pytest.raises(GoalClosureMismatch, match="goal_finalize.answer_mismatch"):
        verify_goal_answer(goal, feasible, bad)


def test_given_range_answer_cannot_claim_another_set():
    goal = {"kind": "find_range"}
    with pytest.raises(GoalClosureMismatch, match="goal_finalize.answer_mismatch"):
        verify_goal_answer(goal, sp.Interval(0, 1), finalize_goal(goal, sp.S.Reals))


@pytest.mark.parametrize("kind,feasible,change", [
    ("find_minimum", sp.Interval(0, 1), "extra_bound"),
    ("find_maximum", sp.Interval.open(0, 1), "extra_value"),
    ("find_maximum", sp.S.Reals, "extra_bound"),
    ("find_minimum", sp.S.EmptySet, "extra_value"),
    ("find_minimum", sp.Interval(0, 1), "extra_set"),
    ("find_minimum", sp.Interval(0, 1), "missing_value"),
    ("find_minimum", sp.Interval(0, 1), "missing_exact"),
    ("find_minimum", sp.Interval(0, 1), "invalid_exact"),
    ("find_minimum", sp.Interval(0, 1), "infinite_value"),
    ("find_minimum", sp.Interval(0, 1), "symbolic_value"),
    ("find_minimum", sp.Interval(0, 1), "non_object"),
    ("find_range", sp.Interval(0, 1), "extra_value"),
    ("find_range", sp.Interval(0, 1), "missing_set"),
    ("find_range", sp.Interval(0, 1), "invalid_set"),
])
def test_malformed_proposed_answer_is_a_mismatch_not_a_capability_gap(kind, feasible, change):
    goal = {"kind": kind}
    bad = finalize_goal(goal, feasible)
    if change.startswith("extra_"):
        bad[change.removeprefix("extra_")] = _answer(value=sp.S.Zero)["value"]
    elif change.startswith("missing_"):
        field = change.removeprefix("missing_")
        (bad["value"] if field == "exact" else bad).pop(field)
    elif change == "invalid_exact":
        bad["value"]["exact"] = {"$math": "Integer", "value": "not an integer"}
    elif change == "infinite_value":
        bad["value"]["exact"] = encode_value(sp.oo)
    elif change == "symbolic_value":
        bad["value"]["exact"] = encode_value(sp.Symbol("a", real=True))
    elif change == "non_object":
        bad = None
    else:
        bad["set"] = "Interval(0, 1)"
    with pytest.raises(GoalClosureMismatch, match="goal_finalize.answer_mismatch"):
        verify_goal_answer(goal, feasible, bad)


def test_answer_exact_comparison_gap_is_not_reclassified_as_a_mismatch(monkeypatch):
    goal, feasible = {"kind": "find_minimum"}, sp.Interval(0, 1)
    answer = finalize_goal(goal, feasible)

    def unknown_sign(value):
        raise VerificationGap("verification_incomplete:algebraic_sign")

    monkeypatch.setattr(goals, "_algebraic_sign", unknown_sign)
    with pytest.raises(VerificationGap, match="verification_incomplete:algebraic_sign"):
        verify_goal_answer(goal, feasible, answer)


def test_answer_recomputation_gap_is_not_reclassified_as_a_mismatch(monkeypatch):
    goal, feasible = {"kind": "find_minimum"}, sp.Interval(0, 1)
    answer = finalize_goal(goal, feasible)
    monkeypatch.setattr(goals, "_contains_exact", lambda *args: None)
    with pytest.raises(VerificationGap, match="bound_membership_unknown"):
        verify_goal_answer(goal, feasible, answer)


def test_rootof_extremum_has_safe_exact_payload_and_mathematical_equality():
    variable = sp.Symbol("z")
    root = sp.CRootOf(variable**3-variable-1, 0)
    answer, evidence = finalize_goal_with_evidence({"kind": "find_minimum"}, sp.Interval(root, sp.oo))
    assert answer["status"] == "attained" and decode_value(answer["value"]["exact"]) == root
    assert decode_value(evidence["feasible_set"]["exact"]) == sp.Interval(root, sp.oo)
    assert equivalent_answers(answer, deepcopy(answer)) is True
