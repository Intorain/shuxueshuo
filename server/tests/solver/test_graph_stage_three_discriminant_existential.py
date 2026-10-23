"""Whole-real discriminant conditions preserve existential and universal logic."""

from itertools import product

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import capabilities as cap
from shuxueshuo_server.graph_lesson.stage_three import driver, judgments
from shuxueshuo_server.graph_lesson.stage_three.trajectory import (
    decode_value,
    encode_value,
)
from tests.solver.test_graph_stage_three_methods import candidate, finish, start

x, a = sp.symbols("x a", real=True)


def output(function, *args, **kwargs):
    computed = function(*args, **kwargs)
    assert computed["checks"] and all(check["passed"] is True for check in computed["checks"])
    assert decode_value(encode_value(computed)) == computed
    return computed["outputs"]


def solve(relation, quantifier="∃"):
    cases = judgments.degenerate_branches(relation, x, a, sp.S.Reals, quantifier)["cases"]
    normalized = output(cap.normalize_to_zero, relation, x)["relation"]
    records = []
    for case in cases:
        if case["kind"] == "degenerate":
            computed = output(cap.degenerate_case_check, relation, x, a, case, quantifier)
        else:
            inputs = {"relation": normalized, "variable": x, "domain": sp.S.Reals,
                      "quantifier": quantifier, "case_domain": case["domain"]}
            opening = output(cap.quadratic_sign_condition, **inputs, mode="opening")
            delta = output(cap.quadratic_sign_condition, **inputs, mode="delta")
            conditions = [opening["opening"], delta["condition"]]
            solutions = [output(cap.solve_parameter_relation, condition, a)["solution"]
                         for condition in conditions]
            computed = output(cap.combine_condition_solutions, conditions, solutions, a,
                              case["domain"], opening["condition_combiner"], quantifier)
        records.append({"case_id": case["id"], "case_path": [case["id"]],
                        "condition": case["condition"], "domain": case["domain"],
                        "outputs": computed, "source_refs": [f"/cases/{case['id']}/calls/0"]})
    return output(cap.merge_cases, cases, records)["solution"], cases, records


@pytest.mark.parametrize("operator,swapped", product((">", ">=", "<", "<="), (False, True)))
def test_concave_existential_discriminant_respects_all_directions_and_touching(operator, swapped):
    expression = -x*x + a*x - 1
    strict = operator in (">", "<")
    oriented = expression if operator in (">", ">=") else -expression
    relation = cap.relation(oriented, operator)
    if swapped:
        relation = cap.relation(relation.rhs, {">": "<", ">=": "<=", "<": ">", "<=": ">="}[operator],
                                relation.lhs)
    expected = sp.Union(sp.Interval(-sp.oo, -2, right_open=strict), sp.Interval(2, sp.oo, left_open=strict))
    solved, _, _ = solve(relation)
    assert solved == expected
    assert solved.contains(-2) is (sp.false if strict else sp.true)
    assert solved.contains(2) is (sp.false if strict else sp.true)


@pytest.mark.parametrize("operator", (">", ">=", "<", "<="))
def test_positive_residual_leading_coefficient_is_sufficient_even_when_delta_fails(operator):
    expression = x*x + a*a + 1
    oriented = expression if operator in (">", ">=") else -expression
    solved, _, records = solve(cap.relation(oriented, operator))
    assert solved == sp.S.Reals
    assert records[-1]["outputs"]["solution"] == sp.S.Reals


@pytest.mark.parametrize("strict,quantifier,expected", [
    (True, "∀", sp.Interval.open(-2, 2)), (False, "∀", sp.Interval(-2, 2)),
    (True, "∃", sp.S.Reals), (False, "∃", sp.S.Reals),
])
def test_same_quadratic_has_different_quantified_condition_combinations(strict, quantifier, expected):
    assert solve(cap.relation(x*x + a*x + 1, ">" if strict else ">="), quantifier)[0] == expected


@pytest.mark.parametrize("expression,strict_expected,weak_expected", [
    (a*x*x - 1, sp.Interval.open(0, sp.oo), sp.Interval.open(0, sp.oo)),
    (a*x*x + 1, sp.S.Reals, sp.S.Reals),
    (a*x*x, sp.Interval.open(0, sp.oo), sp.S.Reals),
    (a*x*x + x - 1, sp.Interval.open(-sp.Rational(1, 4), sp.oo), sp.Interval(-sp.Rational(1, 4), sp.oo)),
    (a*x*x + a*x, sp.Complement(sp.S.Reals, sp.FiniteSet(0)), sp.S.Reals),
    ((a*a - 1)*x*x - 1, sp.Union(sp.Interval.open(-sp.oo, -1), sp.Interval.open(1, sp.oo)),
     sp.Union(sp.Interval.open(-sp.oo, -1), sp.Interval.open(1, sp.oo))),
    ((a - 1)**2*x*x - 1, sp.Complement(sp.S.Reals, sp.FiniteSet(1)),
     sp.Complement(sp.S.Reals, sp.FiniteSet(1))),
    ((a*a - 2)*x*x + a*x - 1,
     sp.Union(sp.Interval.open(-sp.oo, -sp.sqrt(sp.Rational(8, 5))),
              sp.Interval.open(sp.sqrt(sp.Rational(8, 5)), sp.oo)),
     sp.Union(sp.Interval(-sp.oo, -sp.sqrt(sp.Rational(8, 5))),
              sp.Interval(sp.sqrt(sp.Rational(8, 5)), sp.oo))),
])
@pytest.mark.parametrize("strict,negative_direction", product((False, True), (False, True)))
def test_parameter_leading_coefficient_and_every_degenerate_case(expression, strict_expected, weak_expected,
                                                                strict, negative_direction):
    operator = ("<" if strict else "<=") if negative_direction else (">" if strict else ">=")
    relation = cap.relation(-expression if negative_direction else expression, operator)
    solution, _, _ = solve(relation)
    assert solution == (strict_expected if strict else weak_expected)


@pytest.mark.parametrize("quantifier,operator,expression,expected", [
    ("∃", ">", a*x*x + x - 1, True), ("∀", ">", a*x*x + x - 1, False),
    ("∃", "<", a*x*x + x - 1, True), ("∀", "<", a*x*x + x - 1, False),
    ("∃", ">", a*x*x, False), ("∃", ">=", a*x*x, True),
    ("∃", "<", a*x*x, False), ("∃", "<=", a*x*x, True),
    ("∃", ">", a*x*x + 1, True), ("∃", ">", a*x*x - 1, False),
    ("∃", "<", a*x*x + 1, False), ("∃", "<", a*x*x - 1, True),
])
def test_degenerate_nonconstant_linear_and_zero_nonzero_constant(quantifier, operator, expression, expected):
    relation = cap.relation(expression, operator)
    case = judgments.degenerate_branches(relation, x, a, sp.S.Reals, quantifier)["cases"][0]
    checked = output(cap.degenerate_case_check, relation, x, a, case, quantifier)
    assert checked["holds"] is expected
    assert checked["solution"] == (sp.FiniteSet(0) if expected else sp.S.EmptySet)


def test_negative_normalization_preserves_original_existential_residual():
    relation = cap.relation(-x*x + a*x - 1, ">=")
    normalized = output(cap.normalize_to_zero, relation, x)["relation"]
    assert normalized.rel_op == "<="
    arguments = (normalized, x, sp.S.Reals, "∃", sp.S.Reals)
    opening = output(cap.quadratic_sign_condition, *arguments, "opening")
    delta = output(cap.quadratic_sign_condition, *arguments, "delta")
    assert opening["coefficient"] == -1
    assert opening["basis_expression"] == -x*x + a*x - 1
    assert opening["condition_combiner"] == "any"
    assert delta["condition"] == cap.relation(a*a - 4, ">=")


@pytest.mark.parametrize("quantifier,combiner", [("∀", "any"), ("∃", "all"), ("∃", "unknown")])
def test_condition_combiner_cannot_disagree_with_the_original_quantifier(quantifier, combiner):
    conditions = [cap.relation(a, ">"), cap.relation(a*a - 4, ">=")]
    solutions = [output(cap.solve_parameter_relation, condition, a)["solution"] for condition in conditions]
    with pytest.raises(cap.LocalCheckFailed, match="quantifier_condition_combiner_mismatch"):
        cap.combine_condition_solutions(conditions, solutions, a, sp.S.Reals, combiner, quantifier)


def test_existential_union_rechecks_children_then_restricts_to_nondegenerate_case():
    conditions = [cap.relation(a, ">"), cap.relation(a*a, ">=")]
    solutions = [sp.Interval.open(0, sp.oo), sp.S.Reals]
    case_domain = sp.Complement(sp.S.Reals, sp.FiniteSet(0))
    computed = output(cap.combine_condition_solutions, conditions, solutions, a, case_domain, "any", "∃")
    assert computed["solution"] == case_domain
    with pytest.raises(cap.LocalCheckFailed, match="incorrect_condition_solution"):
        cap.combine_condition_solutions(conditions, [sp.S.Reals, sp.S.Reals], a, case_domain, "any", "∃")


def test_existential_theorem_still_requires_nonzero_leading_and_decidable_coefficients():
    with pytest.raises(cap.CapabilityGap, match="nondegenerate_case_required"):
        cap.quadratic_sign_condition(cap.relation(a*x*x + 1, ">="), x, sp.S.Reals, "∃", sp.S.Reals, "delta")
    with pytest.raises(cap.CapabilityGap, match="rational_parameter_polynomial_required"):
        judgments.degenerate_branches(cap.relation(sp.sin(a)*x*x + 1, ">="), x, a, sp.S.Reals, "∃")


@pytest.mark.parametrize("fact,parameter,expected", [
    ("∃x∈ℝ:-x^2+m*x-1>=0", "m", sp.Union(sp.Interval(-sp.oo, -2), sp.Interval(2, sp.oo))),
    ("∃x∈ℝ:-x^2+m*x-1>0", "m", sp.Union(sp.Interval.open(-sp.oo, -2), sp.Interval.open(2, sp.oo))),
    ("∃x∈ℝ:x^2+a^2+1>=0", "a", sp.S.Reals),
    ("∃x∈ℝ:a*x^2+x-1>=0", "a", sp.Interval(-sp.Rational(1, 4), sp.oo)),
    ("∃x∈ℝ:a*x^2+a*x>0", "a", sp.Complement(sp.S.Reals, sp.FiniteSet(0))),
    ("∃x∈ℝ:a*x^2+a*x>=0", "a", sp.S.Reals),
    ("∃z∈ℝ:z^2-b*z+1<=0", "b", sp.Union(sp.Interval(-sp.oo, -2), sp.Interval(2, sp.oo))),
])
def test_existential_discriminant_executes_the_entire_declared_route(fact, parameter, expected):
    state = finish(start(candidate(fact, parameter)))
    assert state["status"] == "method_complete", state["trajectory"]
    assert driver.export_values(state)["feasible_set"] == expected
    calls = [call for step in state["trajectory"]["steps"] for call in step["calls"]]
    combined = [call for call in calls if call["capability"] == "combine_condition_solutions"]
    assert combined
    for call in combined:
        assert decode_value(call["inputs"])["quantifier"] == "∃"
        assert decode_value(call["inputs"])["combiner"] == "any"
