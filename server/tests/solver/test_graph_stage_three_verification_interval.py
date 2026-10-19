"""Original-input interval proofs: quantifier, attainable endpoints and extrema."""

import json

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three.verification import endpoint_check
from tests.solver.test_graph_stage_three_verification import (
    CORPUS,
    TARGET,
    check,
    problem,
)


@pytest.mark.parametrize("question,expected", [
    ("q04", sp.Interval.open(-sp.oo, -5)),
    ("q05", sp.Interval.open(-5, sp.oo)),
])
def test_original_interval_recordings_verify_and_reject_closed_answer(question, expected):
    candidate = json.loads((CORPUS / question / "notation.gold.json").read_text())
    correct = check(candidate, expected)
    assert correct["status"] == "verified", correct
    wrong = check(candidate, expected.closure)
    assert wrong["status"] == "math_failed", wrong
    assert wrong["counterexample"]["parameter"]["expression"] == "-5"
    assert endpoint_check(candidate, TARGET, expected)["status"] == "passed"
    assert endpoint_check(candidate, TARGET, expected.closure)["status"] == "failed"
    assert correct["proof"]["cells"] == wrong["proof"]["cells"]
    assert {"quantifier_endpoint_value", "stationary_point_boundary"} <= {
        row["kind"] for row in correct["proof"]["critical_polynomials"]
    }


@pytest.mark.parametrize("fact,expected", [
    ("∀x∈(0,1):x^2+a>0", sp.Interval(0, sp.oo)),
    ("∀x∈[0,1]:x^2+a>0", sp.Interval.open(0, sp.oo)),
    ("∀x∈(0,1):x^2+a>=0", sp.Interval(0, sp.oo)),
    ("∃x∈(0,1):x^2+a>=0", sp.Interval.open(-1, sp.oo)),
    ("∃x∈(0,1):x^2+a>0", sp.Interval.open(-1, sp.oo)),
    ("∃x∈(0,1]:x^2+a>=0", sp.Interval(-1, sp.oo)),
    ("∃x∈(0,1]:x^2+a>0", sp.Interval.open(-1, sp.oo)),
    ("∀x∈[-1,1]:x^2+a>=0", sp.Interval(0, sp.oo)),
    ("∃x∈(-1,1):-x^2+a>=0", sp.Interval(0, sp.oo)),
    ("∃x∈(-1,1):-x^2+a>0", sp.Interval.open(0, sp.oo)),
    ("∀x∈[0,1]:x^2-2*a*x+1>=0", sp.Interval(-sp.oo, 1)),
    ("∀x∈(0,1):a*x^2+x>0", sp.Interval(-1, sp.oo)),
    ("∀x∈(0,1):a*x^2+x>=0", sp.Interval(-1, sp.oo)),
    ("∃x∈(0,1):a*x^2>=0", sp.Interval(0, sp.oo)),
    ("∃x∈(0,1):a*x^2>0", sp.Interval.open(0, sp.oo)),
    ("∀x∈[1,+∞):x^2+a>=0", sp.Interval(-1, sp.oo)),
    ("∀x∈(1,+∞):x^2+a>0", sp.Interval(-1, sp.oo)),
    ("∃x∈(1,+∞):-x^2+a>=0", sp.Interval.open(1, sp.oo)),
    ("∃x∈ℝ:x^2+a>=0", sp.S.Reals),
    ("∃x∈ℝ:-x^2+a>=0", sp.Interval(0, sp.oo)),
    ("∃x∈ℝ:-x^2+a>0", sp.Interval.open(0, sp.oo)),
    ("∀x∈[sqrt(2),2]:x^2+a*x>=0", sp.Interval(-sp.sqrt(2), sp.oo)),
    ("∀x∈(sqrt(2),2]:x^2+a*x>0", sp.Interval(-sp.sqrt(2), sp.oo)),
    ("∃x∈(1,sqrt(2)):x^2+a>=0", sp.Interval.open(-2, sp.oo)),
    ("∀x∈(1,1):x^2+a>0", sp.S.Reals),
    ("∃x∈(1,1):x^2+a>=0", sp.S.EmptySet),
    ("∀x∈[1,1]:x^2+a>=0", sp.Interval(-1, sp.oo)),
    ("∃x∈[1,1]:x^2+a>0", sp.Interval.open(-1, sp.oo)),
])
def test_exact_interval_variations(fact, expected):
    candidate = problem(fact)
    valid = check(candidate, expected)
    assert valid["status"] == "verified", valid
    invalid = check(candidate, sp.S.Reals if expected != sp.S.Reals else sp.S.EmptySet)
    assert invalid["status"] == "math_failed", invalid
    assert valid["proof"]["cells"] == invalid["proof"]["cells"]


def test_open_endpoint_equality_is_decided_by_quantifier_and_attainability():
    candidate = problem("∃x∈(1,2):x^2+a*x+4>=0")
    result = check(candidate, sp.Interval.open(-5, sp.oo))
    assert result["status"] == "verified", result
    boundary = next(row for row in result["proof"]["cells"] if row["sample"]["expression"] == "-5")
    certificate = boundary["evidence"][-1]["certificate"]
    assert certificate["upper_bound"]["expression"] == "0"
    assert certificate["upper_attained"] is False
    assert boundary["holds"] is False


def test_original_interval_parameter_restriction_is_not_lost():
    candidate = problem("a<0", "∀x∈(1,+∞):x^2+a>0")
    assert check(candidate, sp.Interval.Ropen(-1, 0))["status"] == "verified"
    assert check(candidate, sp.Interval(-1, sp.oo))["status"] == "math_failed"


def test_parameter_membership_does_not_replace_the_quantified_domain():
    candidate = problem("a∈[0,1]", "∃x∈(1,2):-x^2+a>=0")
    assert check(candidate, sp.S.EmptySet)["status"] == "verified"
    assert check(candidate, sp.Interval(0, 1))["status"] == "math_failed"


def test_verifier_does_not_use_method_ranges_or_an_inequality_solver(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("method range or inequality solver must not prove the original interval predicate")

    monkeypatch.setattr(sp, "solve_univariate_inequality", forbidden)
    candidate = problem("∃x∈(1,2):x^2+a*x+4>0")
    assert check(candidate, sp.Interval.open(-5, sp.oo))["status"] == "verified"
