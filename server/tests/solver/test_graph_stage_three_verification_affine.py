"""Independent original-input proofs for affine quantified variable swaps."""

import json

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import verification
from tests.solver.test_graph_stage_three_verification import (
    CORPUS,
    TARGET,
    check,
    problem,
)


@pytest.mark.parametrize("question,expected", [
    ("q08", sp.Interval.open((1-sp.sqrt(5))/2, (1+sp.sqrt(5))/2)),
    ("q09", sp.Interval.open(-1, 1)),
])
def test_original_swap_recordings_verify_and_reject_closed_endpoints(question, expected):
    candidate = json.loads((CORPUS / question / "notation.gold.json").read_text())
    valid = check(candidate, expected)
    assert valid["status"] == "verified", valid
    assert valid["proof"]["category"] == "rational-polynomial-coefficients-quantified-affine/v1"
    invalid = check(candidate, expected.closure)
    assert invalid["status"] == "math_failed", invalid
    assert invalid["counterexample"]["reason"] == "extraneous_point"
    assert valid["proof"]["cells"] == invalid["proof"]["cells"]
    assert verification.endpoint_check(candidate, TARGET, expected)["status"] == "passed"
    assert verification.endpoint_check(candidate, TARGET, expected.closure)["status"] == "failed"


def test_existential_swap_requires_both_union_components_and_has_x2_a1_witness():
    candidate = problem("∃a∈[-1,1]:a*x^2-(a+1)*x+1>0", symbol="x")
    expected = sp.S.Reals - sp.FiniteSet(1)
    valid = check(candidate, expected)
    assert valid["status"] == "verified", valid
    assert {"-1", "0", "1"} <= {
        row["expression"] for row in valid["proof"]["critical_points"]
    }
    original = verification.read_problem(candidate, TARGET)
    holds, evidence = verification._point(original, sp.Integer(2))
    assert holds is True
    assert original.expression.subs({original.parameter: 2, original.x: 1}) == 1
    certificate = evidence[-1]["certificate"]
    assert any(row["point"]["expression"] == "1"
               and row["value"]["expression"] == "1" and row["attained"]
               for row in certificate["candidates"])
    for wrong in (sp.Interval.open(-1, 1), sp.Interval.open(-sp.oo, 1),
                  sp.Interval.open(1, sp.oo), sp.S.Reals):
        invalid = check(candidate, wrong)
        assert invalid["status"] == "math_failed", invalid
        assert invalid["counterexample"]["original_holds"] != invalid["counterexample"]["candidate_includes"]
        assert valid["proof"]["cells"] == invalid["proof"]["cells"]
    assert verification.endpoint_check(candidate, TARGET, expected)["status"] == "passed"


# In each row these authored answers correspond to the original t+a relation,
# ordered as forall >=, >, <=, <, then exists >=, >, <=, <. The verifier is not
# used to manufacture expectations or to pick the proposed answer's endpoints.
GE0, GT0 = sp.Interval(0, sp.oo), sp.Interval.open(0, sp.oo)
LE0, LT0 = sp.Interval(-sp.oo, 0), sp.Interval.open(-sp.oo, 0)
GE_NEG1, GT_NEG1 = sp.Interval(-1, sp.oo), sp.Interval.open(-1, sp.oo)
LE_NEG1, LT_NEG1 = sp.Interval(-sp.oo, -1), sp.Interval.open(-sp.oo, -1)
EMPTY, REALS = sp.S.EmptySet, sp.S.Reals
RELATIONS = [(quantifier, relation) for quantifier in ("∀", "∃") for relation in (">=", ">", "<=", "<")]
AFFINE_DOMAINS = [
    ("[0,1]", (GE0, GT0, LE_NEG1, LT_NEG1, GE_NEG1, GT_NEG1, LE0, LT0)),
    ("(0,1)", (GE0, GE0, LE_NEG1, LE_NEG1, GT_NEG1, GT_NEG1, LT0, LT0)),
    ("[0,1)", (GE0, GT0, LE_NEG1, LE_NEG1, GT_NEG1, GT_NEG1, LE0, LT0)),
    ("(0,1]", (GE0, GE0, LE_NEG1, LT_NEG1, GE_NEG1, GT_NEG1, LT0, LT0)),
    ("[0,+∞)", (GE0, GT0, EMPTY, EMPTY, REALS, REALS, LE0, LT0)),
    ("(0,+∞)", (GE0, GE0, EMPTY, EMPTY, REALS, REALS, LT0, LT0)),
    ("(-∞,0]", (EMPTY, EMPTY, LE0, LT0, GE0, GT0, REALS, REALS)),
    ("(-∞,0)", (EMPTY, EMPTY, LE0, LE0, GT0, GT0, REALS, REALS)),
    ("ℝ", (EMPTY, EMPTY, EMPTY, EMPTY, REALS, REALS, REALS, REALS)),
]


@pytest.mark.parametrize("domain,quantifier,relation,expected", [
    (domain, quantifier, relation, expected)
    for domain, answers in AFFINE_DOMAINS
    for (quantifier, relation), expected in zip(RELATIONS, answers, strict=True)
])
def test_all_relations_and_quantifiers_on_open_closed_and_unbounded_intervals(domain, quantifier, relation, expected):
    candidate = problem(f"{quantifier}t∈{domain}:t+a{relation}0")
    valid = check(candidate, expected)
    assert valid["status"] == "verified", valid
    invalid = check(candidate, REALS if expected != REALS else EMPTY)
    assert invalid["status"] == "math_failed", invalid
    assert valid["proof"]["cells"] == invalid["proof"]["cells"]


@pytest.mark.parametrize("quantifier,relation", RELATIONS)
@pytest.mark.parametrize("domain", ["(0,1)", "ℝ"])
def test_original_constant_is_attained_even_without_closed_endpoints(quantifier, relation, domain):
    expected = {">=": GE0, ">": GT0, "<=": LE0, "<": LT0}[relation]
    candidate = problem(f"{quantifier}t∈{domain}:a{relation}0")
    result = check(candidate, expected)
    assert result["status"] == "verified", result
    original = verification.read_problem(candidate, TARGET)
    holds, evidence = verification._point(original, sp.S.Zero)
    assert holds is (relation in (">=", "<="))
    certificate = evidence[-1]["certificate"]
    if certificate["kind"] == "interval_polynomial_range":
        assert certificate["lower_attained"] and certificate["upper_attained"]
        assert certificate["candidates"][0]["kind"] == "constant_value"


@pytest.mark.parametrize("quantifier,relation", RELATIONS)
def test_zero_slope_parameter_is_checked_as_attained_constant(quantifier, relation):
    expected = {">=": GE0, ">": GT0, "<=": LE0, "<": LT0}[relation]
    candidate = problem(f"{quantifier}t∈(1,2):a*t{relation}0")
    result = check(candidate, expected)
    assert result["status"] == "verified", result
    zero = next(row for row in result["proof"]["cells"] if row["sample"]["expression"] == "0")
    assert zero["kind"] == "critical_point"
    assert zero["holds"] is (relation in (">=", "<="))
    certificate = zero["evidence"][-1]["certificate"]
    assert certificate["lower_bound"]["expression"] == "0"
    assert certificate["lower_attained"] and certificate["upper_attained"]


@pytest.mark.parametrize("quantifier,relation", RELATIONS)
def test_identically_zero_polynomial_preserves_strictness(quantifier, relation):
    candidate = problem(f"{quantifier}t∈(0,1):a-a{relation}0")
    expected = REALS if relation in (">=", "<=") else EMPTY
    result = check(candidate, expected)
    assert result["status"] == "verified", result
    assert result["proof"]["critical_points"] == []
    assert any(row["identically_zero"] for row in result["proof"]["critical_polynomials"])


@pytest.mark.parametrize("fact,expected", [
    ("∀t∈(1,1):t+a>0", REALS),
    ("∃t∈(1,1):t+a>=0", EMPTY),
    ("∀t∈[1,1]:t+a>=0", GE_NEG1),
    ("∃t∈[1,1]:t+a>0", GT_NEG1),
    ("∀t∈(sqrt(2),2):t+a>0", sp.Interval(-sp.sqrt(2), sp.oo)),
    ("∃t∈(1,sqrt(2)):t+a>=0", sp.Interval.open(-sp.sqrt(2), sp.oo)),
    ("∀t∈ℝ:(a-1)*t>=0", sp.FiniteSet(1)),
    ("∃t∈ℝ:(a-1)*t>0", REALS - sp.FiniteSet(1)),
])
def test_affine_special_domains_and_isolated_slope_zero(fact, expected):
    candidate = problem(fact)
    valid = check(candidate, expected)
    assert valid["status"] == "verified", valid
    invalid = check(candidate, REALS if expected != REALS else EMPTY)
    assert invalid["status"] == "math_failed", invalid


def test_affine_original_constraints_and_canceled_denominator_are_retained():
    candidate = problem("a<2", "∀t∈[0,1]:t+(a-1)/(a-1)>=0")
    expected = sp.Interval.open(-sp.oo, 2) - sp.FiniteSet(1)
    assert check(candidate, expected)["status"] == "verified"
    for wrong in (sp.Interval.open(-sp.oo, 2), REALS - sp.FiniteSet(1)):
        invalid = check(candidate, wrong)
        assert invalid["status"] == "math_failed", invalid


@pytest.mark.parametrize("facts", [
    ["∀t∈[0,1]:t^3+a>=0"],
    ["∀t∈[0,a]:t+a>=0"],
    ["∀t∈[0,1]:a/t>=0"],
    ["b>0", "∀t∈[0,1]:t+a>=0"],
])
def test_affine_extension_does_not_accept_unregistered_categories(facts):
    result = check(problem(*facts), REALS)
    assert result["status"] == "capability_gap", result
    assert result["diagnostics"][0]["code"] == "verification_incomplete"


def test_affine_proof_uses_original_arithmetic_without_inequality_solver(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("an inequality solver cannot prove the original predicate")

    monkeypatch.setattr(sp, "solve_univariate_inequality", forbidden)
    monkeypatch.setattr(sp, "reduce_inequalities", forbidden)
    candidate = problem("∃a∈[-1,1]:a*x^2-(a+1)*x+1>0", symbol="x")
    assert check(candidate, REALS - sp.FiniteSet(1))["status"] == "verified"
