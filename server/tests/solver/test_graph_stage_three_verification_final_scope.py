"""Independent QQbar(a) critical partitions and one-parameter semialgebraic restrictions."""

import json

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import verification
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.verification import (
    apply_visible_constraints,
    verify,
)

TARGET = "/root/goals/0"
REALS = sp.S.Reals
EMPTY = sp.S.EmptySet
EXTENDED_CATEGORY = "real-algebraic-rational-coefficients-semialgebraic-constraints/v1"


def problem(*facts):
    return {"original_text": " ".join(facts), "root": {
        "facts": list(facts), "goals": [{"kind": "find_range", "symbol": "a"}],
    }}


def check(candidate, proposed):
    return verify(candidate, TARGET, build_context(candidate, TARGET), proposed)


@pytest.mark.parametrize("fact,expected", [
    ("∀x∈ℝ:x^2+1/a>=0", sp.Interval.open(0, sp.oo)),
    ("∀x∈ℝ:x^2+(a-1)/(a+1)>=0", sp.Union(sp.Interval.open(-sp.oo, -1), sp.Interval(1, sp.oo))),
    ("∀x∈ℝ:x^2+(a^2-2)/(a-1)>=0", sp.Union(sp.Interval.Ropen(-sp.sqrt(2), 1), sp.Interval(sp.sqrt(2), sp.oo))),
    ("∀x∈ℝ:(a/(a-1))*x^2+1>=0", sp.Union(sp.Interval(-sp.oo, 0), sp.Interval.open(1, sp.oo))),
    ("∀x∈ℝ:((a^2-2)/(a-1))*x^2+1>0", sp.Union(sp.Interval.Ropen(-sp.sqrt(2), 1), sp.Interval(sp.sqrt(2), sp.oo))),
    ("∀x∈ℝ:x^2+1/(1/a)>=0", sp.Interval.open(0, sp.oo)),
    ("∀t∈[0,1]:t+1/a>=0", sp.Interval.open(0, sp.oo)),
    ("∀x∈ℝ:sqrt(2)*x^2+a>=0", sp.Interval(0, sp.oo)),
    ("∀x∈ℝ:x^2+sqrt(2)*a-1>=0", sp.Interval(sp.sqrt(2)/2, sp.oo)),
    ("∀x∈ℝ:x^2+(a-sqrt(2))/(a+sqrt(3))>=0", sp.Union(sp.Interval.open(-sp.oo, -sp.sqrt(3)), sp.Interval(sp.sqrt(2), sp.oo))),
    ("∀x∈ℝ:(sqrt(2)/(a-1))*x^2+1>=0", sp.Interval.open(1, sp.oo)),
    ("∀x∈ℝ:x^2+sqrt(2)/(a-1)>=0", sp.Interval.open(1, sp.oo)),
    ("∀x∈[sqrt(2),2]:(x+a)/(a-1)>0", sp.Union(sp.Interval.open(-sp.oo, -2), sp.Interval.open(1, sp.oo))),
    ("∀x∈[sqrt(2),2):(x+a)/(a-1)>0", sp.Union(sp.Interval(-sp.oo, -2), sp.Interval.open(1, sp.oo))),
    ("∃x∈[sqrt(2),2]:(x+a)/(a-1)>0", sp.Union(sp.Interval.open(-sp.oo, -sp.sqrt(2)), sp.Interval.open(1, sp.oo))),
    ("∃x∈[sqrt(2),2]:(x+a)/(a-1)>=0", sp.Union(sp.Interval(-sp.oo, -sp.sqrt(2)), sp.Interval.open(1, sp.oo))),
    ("∀x∈(1,1):x^2+1/(a-1)>0", REALS - sp.FiniteSet(1)),
])
def test_algebraic_rational_coefficients_and_exact_open_boundaries(fact, expected):
    candidate = problem(fact)
    result = check(candidate, expected)
    assert result["status"] == "verified", result
    assert result["proof"]["invariance"]["proved"] is True
    assert json.dumps(result)
    for wrong in (EMPTY, REALS):
        if wrong != expected:
            rejected = check(candidate, wrong)
            assert rejected["status"] == "math_failed", rejected


@pytest.mark.parametrize("restriction,expected", [
    ("a^2<1", sp.Interval.open(-1, 1)),
    ("(a>0)∨(1/(a-1)>0)", sp.Interval.open(0, sp.oo) - sp.FiniteSet(1)),
    ("(a=1)∨((a-1)/(a-1)>0)", REALS - sp.FiniteSet(1)),
    ("(a-1)/(a+1)>=0", sp.Union(sp.Interval.open(-sp.oo, -1), sp.Interval(1, sp.oo))),
    ("(a^2>=2)∧(a<sqrt(3))", sp.Union(sp.Interval(-sp.oo, -sp.sqrt(2)), sp.Interval.Ropen(sp.sqrt(2), sp.sqrt(3)))),
    ("a∈{-sqrt(2),1,sqrt(3)}", sp.FiniteSet(-sp.sqrt(2), 1, sp.sqrt(3))),
    ("a∉{t∈ℝ|(t>=0)∧(t<=1)}", sp.Union(sp.Interval.open(-sp.oo, 0), sp.Interval.open(1, sp.oo))),
    ("a∉{0,1}", REALS - sp.FiniteSet(0, 1)),
    ("a^2∈[1,4]", sp.Union(sp.Interval(-2, -1), sp.Interval(1, 2))),
    ("a∈({t∈ℝ|(t>=-2)∧(t<=-1)}∪{t∈ℝ|(t>=1)∧(t<=2)})", sp.Union(sp.Interval(-2, -1), sp.Interval(1, 2))),
    ("a∈({t∈ℝ|(t>=-2)∧(t<=2)}∩{t∈ℝ|(t>=0)∧(t<=3)})", sp.Interval(0, 2)),
    ("a∈[a-1,a+1]", REALS),
    ("a∈{t∈ℝ|t^2>=1}", sp.Union(sp.Interval(-sp.oo, -1), sp.Interval(1, sp.oo))),
    ("a∈{a+1,a-1}", EMPTY),
    ("1/a∈[1,2]", sp.Interval(sp.Rational(1, 2), 1)),
    ("1/a∉{t∈ℝ|(t>=1)∧(t<=2)}", REALS - sp.Union(sp.FiniteSet(0), sp.Interval(sp.Rational(1, 2), 1))),
    ("1/a∉∅", REALS - sp.FiniteSet(0)),
    ("a∈[1,1]", sp.FiniteSet(1)),
    ("a∈[sqrt(2),sqrt(2)]", sp.FiniteSet(sp.sqrt(2))),
    ("a∈(1,1)", EMPTY),
])
def test_semialgebraic_restrictions_apply_and_verify_independently(restriction, expected):
    candidate = problem(restriction, "∀x∈ℝ:x^2+1>=0")
    context = build_context(candidate, TARGET)
    actual, processing = apply_visible_constraints(candidate, TARGET, context, REALS)
    assert verification._set_mismatch(actual, expected) is None
    assert any(row["status"] == "intersected" for row in processing)
    correct = verify(candidate, TARGET, context, expected)
    assert correct["status"] == "verified", correct
    wrong = EMPTY if expected != EMPTY else REALS
    rejected = verify(candidate, TARGET, context, wrong)
    assert rejected["status"] == "math_failed", rejected


@pytest.mark.parametrize("restriction,expected,hole", [
    ("a∉{t∈ℝ|1/t>1}", REALS - sp.Interval.open(0, 1), 0),
    ("a∈{t∈ℝ|1/t>1}", sp.Interval.open(0, 1), 0),
    ("a∉{t∈ℝ|t/t>0}", sp.FiniteSet(0), 0),
    ("a∈{t∈ℝ|t/t>0}", REALS - sp.FiniteSet(0), 0),
    ("a∉{t∈ℝ|1/(1/t)>0}", sp.Interval(-sp.oo, 0), 0),
    ("a∉{t∈ℝ|1/(t^2-2)>0}", sp.Interval(-sp.sqrt(2), sp.sqrt(2)), sp.sqrt(2)),
    ("a∈({t∈ℝ|t/t>0}∪{0})", REALS, 0),
    ("a∉({t∈ℝ|t/t>0}∩{0})", REALS, 0),
    ("1/a∉{t∈ℝ|1/t>1}", sp.Union(sp.Interval.open(-sp.oo, 0), sp.Interval.Lopen(0, 1)), 0),
    ("a∉{t∈ℝ|(t<=0)∨(1/t>1)}", sp.Union(sp.FiniteSet(0), sp.Interval(1, sp.oo)), 0),
    ("(a<=0)∨(1/a>1)", sp.Interval.open(-sp.oo, 1) - sp.FiniteSet(0), 0),
])
def test_set_builder_denominators_are_local_and_member_denominators_are_global(restriction, expected, hole):
    candidate = problem(restriction, "∀x∈ℝ:x^2+1>=0")
    context = build_context(candidate, TARGET)
    actual, _ = apply_visible_constraints(candidate, TARGET, context, REALS)
    assert verification._set_mismatch(actual, expected) is None
    correct = verify(candidate, TARGET, context, expected)
    assert correct["status"] == "verified", correct
    # Only flip the pole itself, not a whole interval: both missing and extra
    # endpoints must be rejected by the original-input verifier.
    rejected = verify(candidate, TARGET, context, expected ^ sp.FiniteSet(hole))
    assert rejected["status"] == "math_failed", rejected


@pytest.mark.parametrize("restriction,expected", [
    ("(1/a)/(1/a)∉{t∈ℝ|1/(t-1)>1}", REALS - sp.FiniteSet(0)),
    ("(1/a)/(1/a)∈{t∈ℝ|1/(t-1)>1}", EMPTY),
    ("a/a∈({t∈ℝ|1/(t-1)>1}∪{1})", REALS - sp.FiniteSet(0)),
    ("a/a∉{t∈ℝ|(t-1)^(-1)>1}", REALS - sp.FiniteSet(0)),
])
def test_constant_member_at_local_pole_is_outside_set(restriction, expected):
    candidate = problem(restriction, "∀x∈ℝ:x^2+1>=0")
    context = build_context(candidate, TARGET)
    actual, _ = apply_visible_constraints(candidate, TARGET, context, REALS)
    assert verification._set_mismatch(actual, expected) is None
    assert verify(candidate, TARGET, context, expected)["status"] == "verified"
    wrong = REALS - sp.FiniteSet(0) if expected == EMPTY else EMPTY
    assert verify(candidate, TARGET, context, wrong)["status"] == "math_failed"


def test_nonlinear_constraint_intersects_main_and_rejects_missing_union():
    candidate = problem("a^2<1", "∀x∈ℝ:x^2+a>=0")
    context = build_context(candidate, TARGET)
    actual, _ = apply_visible_constraints(candidate, TARGET, context, sp.Interval(0, sp.oo))
    assert actual == sp.Interval.Ropen(0, 1)
    assert verify(candidate, TARGET, context, actual)["status"] == "verified"
    candidate = problem("a^2>=2", "∀x∈ℝ:x^2+1>=0")
    rejected = check(candidate, sp.Interval(sp.sqrt(2), sp.oo))
    assert rejected["status"] == "math_failed"
    assert rejected["counterexample"]["reason"] == "missing_feasible_point"


def cubic_root():
    t = sp.Symbol("t")
    return sp.CRootOf(t**3-t-1, 0)


@pytest.mark.parametrize("restriction,expected", [
    ("a^3-a-1>=0", sp.Interval(cubic_root(), sp.oo)),
    ("1/(a^3-a-1)>0", sp.Interval.open(cubic_root(), sp.oo)),
    ("(a^3-a-1)/(a-2)>=0", sp.Union(sp.Interval(-sp.oo, cubic_root()), sp.Interval.open(2, sp.oo))),
    ("a∉{t∈ℝ|(t^3-t-1)/(t^3-t-1)>0}", sp.FiniteSet(cubic_root())),
])
def test_rootof_critical_points_poles_and_closedness(restriction, expected):
    candidate = problem(restriction, "∀x∈ℝ:x^2+1>=0")
    context = build_context(candidate, TARGET)
    actual, _ = apply_visible_constraints(candidate, TARGET, context, REALS)
    assert verification._set_mismatch(actual, expected) is None
    correct = verify(candidate, TARGET, context, expected)
    assert correct["status"] == "verified", correct
    wrong = expected ^ sp.FiniteSet(cubic_root())
    rejected = verify(candidate, TARGET, context, wrong)
    assert rejected["status"] == "math_failed", rejected


@pytest.mark.parametrize("definition", [
    "f(t)=(a-sqrt(2))/(a-sqrt(2))",
    "f(t)=(a^3-a-1)/(a^3-a-1)",
])
def test_unused_definitions_keep_algebraic_denominator_holes(definition):
    hole = cubic_root() if "a^3" in definition else sp.sqrt(2)
    candidate = problem("∀x∈ℝ:x^2+1>=0")
    candidate["root"]["definitions"] = [definition]
    context = build_context(candidate, TARGET)
    actual, _ = apply_visible_constraints(candidate, TARGET, context, REALS)
    expected = REALS - sp.FiniteSet(hole)
    assert verification._set_mismatch(actual, expected) is None
    assert verify(candidate, TARGET, context, expected)["status"] == "verified"
    rejected = verify(candidate, TARGET, context, REALS)
    assert rejected["status"] == "math_failed"
    assert rejected["counterexample"]["evidence"][0]["source_ref"] == "/root/definitions/0"


def test_new_category_is_distinct_and_legacy_category_is_stable():
    expanded = check(problem("∀x∈ℝ:x^2+sqrt(2)/(a-1)>=0"), sp.Interval.open(1, sp.oo))
    assert expanded["proof"]["category"] == EXTENDED_CATEGORY
    legacy = check(problem("∀x∈ℝ:x^2+a>=0"), sp.Interval(0, sp.oo))
    assert legacy["proof"]["category"] == "rational-polynomial-coefficients-universal-real-quadratic/v2"


def test_no_route_solver_or_generic_inequality_solver_is_used(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("the original-input verifier must prove its own exact partition")

    for name in ("solve_univariate_inequality", "reduce_inequalities", "solveset"):
        monkeypatch.setattr(sp, name, forbidden)
    candidate = problem("a∉{t∈ℝ|(t>=0)∧(t<=1)}", "(a^2-2)/(a-1)>=0", "∀x∈ℝ:x^2+1>=0")
    expected = sp.Union(sp.Interval.Ropen(-sp.sqrt(2), 0), sp.Interval(sp.sqrt(2), sp.oo))
    context = build_context(candidate, TARGET)
    actual, _ = apply_visible_constraints(candidate, TARGET, context, REALS)
    assert verification._set_mismatch(actual, expected) is None
    assert verify(candidate, TARGET, context, expected)["status"] == "verified"


def test_unknown_algebraic_root_computation_stays_a_gap(monkeypatch):
    def unknown(*args, **kwargs):
        raise NotImplementedError("exact field norm unavailable")

    monkeypatch.setattr(sp.Poly, "norm", unknown)
    result = check(problem("∀x∈ℝ:x^2+sqrt(2)*a>=0"), sp.Interval(0, sp.oo))
    assert result["status"] == "capability_gap"
    assert result["diagnostics"][0]["code"] == "verification_incomplete"


@pytest.mark.parametrize("facts", [
    ["∀x∈ℝ:x^2+sqrt(a)>=0"],
    ["a>sqrt(a)", "∀x∈ℝ:x^2+1>=0"],
    ["∀x∈[0,a]:x^2+1>=0"],
    ["∀x∈ℝ:x^3+1/a>=0"],
    ["∀x∈ℝ:x^2+1/(x+a)>=0"],
    ["b>a", "∀x∈ℝ:x^2+1>=0"],
])
def test_inputs_outside_final_category_are_explicit_gaps(facts):
    result = check(problem(*facts), REALS)
    assert result["status"] == "capability_gap", result
    assert result["diagnostics"][0]["code"] == "verification_incomplete"
