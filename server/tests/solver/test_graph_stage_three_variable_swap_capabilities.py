"""Exact affine reordering, slope decisions and quantified endpoint conditions."""

from itertools import product

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import capabilities as cap
from shuxueshuo_server.graph_lesson.stage_three.capabilities import (
    variable_swap as swap,
)
from shuxueshuo_server.graph_lesson.stage_three.trajectory import (
    decode_value,
    encode_value,
)

x, m = sp.symbols("x m", real=True)
REVERSE = {">": "<", ">=": "<=", "<": ">", "<=": ">="}


def output(function, *args, **kwargs):
    computed = function(*args, **kwargs)
    assert computed["checks"] and all(check["passed"] is True for check in computed["checks"])
    assert decode_value(encode_value(computed)) == computed
    return computed["outputs"]


def policy(quantifier, original_operator, domain):
    # The existing policy compares zero with the quantified affine function.
    return output(cap.select_quantifier_policy, quantifier, REVERSE[original_operator], domain)["policy"]


def solve(expression, domain, quantifier="∀", operator=">", variable=m, parameter=x):
    selected = policy(quantifier, operator, domain)
    assert swap.validate_variable_swap(expression, variable, parameter, domain, selected) is None
    reordered = output(swap.reorder_by_variable, expression, variable, parameter)
    envelope = output(swap.parameter_linear_range, reordered["expression"], variable,
                      parameter, domain, selected)
    applied = output(cap.apply_quantifier_policy, selected, envelope["range"], sp.S.Zero)
    normalized = output(swap.normalize_parameter_conditions, applied["conditions"], parameter)
    solved = output(swap.solve_variable_conditions, normalized["conditions"], applied["combiner"], parameter)
    return solved["solution"], envelope, applied, normalized


def test_reordering_collects_the_quantified_letter_and_certifies_roles():
    expression = m*x*x - m*x - 6 + m
    computed = swap.reorder_by_variable(expression, m, x)
    reordered = computed["outputs"]
    assert reordered == {"expression": m*(x*x - x + 1) - 6,
                         "slope": x*x - x + 1, "intercept": -6,
                         "variable": m, "parameter": x}
    assert computed["operations"] == ["identity"]
    assert {check["kind"] for check in computed["checks"]} == {
        "affine_reordering_identity", "affine_symbol_roles",
    }


def test_strictly_positive_quadratic_slope_selects_the_upper_endpoint():
    solution, envelope, applied, _ = solve(m*x*x - m*x - 6 + m, sp.Interval(1, 3), operator="<")
    assert solution == sp.Interval.open((1 - sp.sqrt(5))/2, (1 + sp.sqrt(5))/2)
    assert envelope["slope_sign"] == "positive"
    assert envelope["slope_certificate"]["square"] == (x - sp.Rational(1, 2))**2 + sp.Rational(3, 4)
    assert envelope["endpoint_mode"] == "right_endpoint"
    assert envelope["selected_endpoint"] == 3
    assert envelope["range"]["candidates"] == [{"point": 3, "value": 3*x*x - 3*x - 3,
                                                  "attained": True}]
    assert len(applied["conditions"]) == 1


@pytest.mark.parametrize("quantifier,expected,combiner", [
    ("∀", sp.Interval.open(-1, 1), "all"),
    ("∃", sp.Complement(sp.S.Reals, sp.FiniteSet(1)), "any"),
])
def test_unknown_slope_combines_both_endpoints_by_the_actual_quantifier(quantifier, expected, combiner):
    expression = m*x*x - (m + 1)*x + 1
    solution, envelope, applied, _ = solve(expression, sp.Interval(-1, 1), quantifier=quantifier)
    assert solution == expected
    assert envelope["slope_sign"] == "unknown"
    assert envelope["endpoint_mode"] == "both_endpoints"
    assert envelope["selected_endpoint"] is None
    assert applied["combiner"] == combiner
    assert len(applied["conditions"]) == 2
    if quantifier == "∃":
        assert solution.contains(2) is sp.true
        assert expression.subs({x: 2, m: 1}) > 0


@pytest.mark.parametrize("quantifier,operator", product(("∀", "∃"), (">", ">=", "<", "<=")))
def test_unknown_sign_all_directions_and_strictness(quantifier, operator):
    # Over [-1,1], m*x has bounds -abs(x), abs(x). Its zero slope at
    # x=0 distinguishes strict from weak inequalities for both quantifiers.
    solution, envelope, applied, _ = solve(m*x, sp.Interval(-1, 1), quantifier, operator)
    if quantifier == "∀":
        expected = sp.S.EmptySet if operator in (">", "<") else sp.FiniteSet(0)
    else:
        expected = sp.Complement(sp.S.Reals, sp.FiniteSet(0)) if operator in (">", "<") else sp.S.Reals
    assert solution == expected
    assert envelope["slope_sign"] == "unknown"
    assert applied["combiner"] == ("all" if quantifier == "∀" else "any")


@pytest.mark.parametrize("quantifier,operator,slope,open_left,open_right", product(
    ("∀", "∃"), (">", ">=", "<", "<="), (1, -1), (False, True), (False, True),
))
def test_strict_slope_endpoint_direction_and_attainment(
    quantifier, operator, slope, open_left, open_right,
):
    domain = sp.Interval(0, 1, left_open=open_left, right_open=open_right)
    solution, envelope, _, _ = solve(slope*m + x, domain, quantifier, operator)
    lower_needed = (operator in (">", ">=")) == (quantifier == "∀")
    right = (slope < 0) == lower_needed
    point = int(right)
    attained = not (open_right if right else open_left)
    strict = ((operator in (">", "<") and attained) if quantifier == "∀"
              else operator in (">", "<") or not attained)
    boundary = -slope * point
    expected = (sp.Interval(boundary, sp.oo, left_open=strict) if operator in (">", ">=")
                else sp.Interval(-sp.oo, boundary, right_open=strict))
    assert solution == expected
    assert envelope["selected_endpoint"] == point
    assert envelope["endpoint_mode"] == ("right_endpoint" if right else "left_endpoint")
    assert envelope["slope_sign"] == ("positive" if slope > 0 else "negative")
    assert envelope["range"]["candidates"][0]["attained"] is attained


@pytest.mark.parametrize("quantifier,operator", product(("∀", "∃"), (">", ">=", "<", "<=")))
def test_constant_function_attains_its_value_in_the_open_interval(quantifier, operator):
    solution, envelope, _, _ = solve(x, sp.Interval.open(-1, 1), quantifier, operator)
    strict = operator in (">", "<")
    expected = (sp.Interval(0, sp.oo, left_open=strict) if operator in (">", ">=") else
                sp.Interval(-sp.oo, 0, right_open=strict))
    assert solution == expected
    assert envelope["slope_sign"] == "zero"
    assert envelope["endpoint_mode"] == "constant"
    assert all(row["attained"] is False for row in envelope["endpoint_values"])
    assert envelope["range"]["candidates"] == [{"point": 0, "value": x, "attained": True}]


@pytest.mark.parametrize("quantifier,operator", product(("∀", "∃"), (">", ">=", "<", "<=")))
def test_identically_zero_expression_does_not_invent_an_open_endpoint_witness(quantifier, operator):
    solution, envelope, _, _ = solve(sp.S.Zero, sp.Interval.open(0, 2), quantifier, operator)
    assert solution == (sp.S.EmptySet if operator in (">", "<") else sp.S.Reals)
    assert envelope["range"]["candidates"] == [{"point": 1, "value": 0, "attained": True}]


@pytest.mark.parametrize("slope,sign", [(x*x + 1, "positive"), (-x*x - 1, "negative"),
                                         (x*x, "unknown"), (-x*x, "unknown"),
                                         (x*x - 1, "unknown"), (x, "unknown")])
def test_global_slope_sign_requires_strictness_even_at_double_roots(slope, sign):
    domain = sp.Interval(0, 2)
    computed = swap.parameter_linear_range(slope*m + x, m, x, domain, policy("∀", ">", domain))
    assert computed["outputs"]["slope_sign"] == sign
    assert all(row["passed"] is True for row in computed["checks"])
    assert computed["operations"] == ["linear_interval_extrema"]


@pytest.mark.parametrize("slope", [x*x, -x*x, x*x - x, x])
@pytest.mark.parametrize("domain", [sp.Interval.open(-1, 1), sp.Interval.Lopen(-1, 1),
                                    sp.Interval.Ropen(-1, 1)])
def test_open_interval_with_parameter_dependent_zero_slope_is_an_explicit_gap(slope, domain):
    selected = policy("∃", ">=", domain)
    for function in (swap.validate_variable_swap, swap.parameter_linear_range):
        with pytest.raises(cap.CapabilityGap, match="open_interval_parameter_slope_cases_required"):
            function(slope*m + x, m, x, domain, selected)


def test_variable_renaming_preserves_the_result_and_role_binding():
    t, z = sp.symbols("t z", real=True)
    solution, envelope, _, _ = solve(t*z*z - (t + 1)*z + 1, sp.Interval(-1, 1),
                                     "∃", ">", variable=t, parameter=z)
    assert solution == sp.Complement(sp.S.Reals, sp.FiniteSet(1))
    assert envelope["slope"] == z*z - z
    assert envelope["intercept"] == 1 - z


def test_admission_checks_do_not_emit_or_claim_a_capability_execution(monkeypatch):
    def forbidden_result(*args, **kwargs):
        raise AssertionError("admission must not emit a capability result")

    domain = sp.Interval(1, 3)
    selected = policy("∀", "<", domain)
    monkeypatch.setattr(swap, "result", forbidden_result)
    assert swap.validate_variable_swap(m*(x*x - x + 1) - 6, m, x, domain, selected) is None


def test_normalization_records_actual_reversible_operations_and_preserves_sets():
    initial = [cap.relation(sp.S.Zero, ">", 3*x*x - 3*x - 3),
               cap.relation(sp.S.Zero, "<=", -2*x*x + 2)]
    computed = swap.normalize_parameter_conditions(initial, x)
    assert computed["outputs"]["original_conditions"] == initial
    assert set(computed["operations"]) == {"add_both_sides", "multiply_negative", "multiply_constant"}
    for original, transformed, check in zip(initial, computed["outputs"]["conditions"], computed["checks"]):
        assert check["original"] == original and check["normalized"] == transformed
        assert check["move_checks"] and check["scale_checks"]
        assert cap.solve_conditions([original], "all", x)["outputs"]["solution"] == cap.solve_conditions(
            [transformed], "all", x,
        )["outputs"]["solution"]


@pytest.mark.parametrize("expression,variable,parameter,reason", [
    (m*x, m, m, "distinct_real_symbol_roles_required"),
    (m*x, m + 1, x, "distinct_real_symbol_roles_required"),
    (m*x, m, sp.Symbol("z"), "distinct_real_symbol_roles_required"),
    (m*x + sp.Symbol("z", real=True), m, x, "single_parameter_affine_required"),
    (m*x*x, x, m, "polynomial_degree"),
    (m*m + x, m, x, "polynomial_degree"),
    (m*x**3 + 1, m, x, "polynomial_degree"),
    (m + x**3, m, x, "polynomial_degree"),
    (m/x + 1, m, x, "nonpolynomial"),
    (sp.sin(m) + x, m, x, "nonpolynomial"),
    (sp.sqrt(2)*m + x, m, x, "rational_parameter_coefficients_required"),
    (sp.Float("1.1")*m + x, m, x, "rational_parameter_coefficients_required"),
])
def test_invalid_roles_and_unsupported_shapes_are_gaps(expression, variable, parameter, reason):
    with pytest.raises(cap.CapabilityGap, match=reason):
        swap.reorder_by_variable(expression, variable, parameter)


@pytest.mark.parametrize("domain,reason", [
    (sp.Interval(0, sp.oo), "bounded_interval_required"),
    (sp.S.Reals, "bounded_interval_required"),
    (sp.S.EmptySet, "nonempty_interval_required"),
    (sp.FiniteSet(1), "nonempty_interval_required"),
    (sp.Interval(0, sp.sqrt(2)), "rational_interval_endpoints_required"),
    (sp.Interval(0, x), "numeric_interval_required"),
])
def test_unsupported_domain_is_an_explicit_gap(domain, reason):
    with pytest.raises(cap.CapabilityGap, match=reason):
        swap.parameter_linear_range(m*x + 1, m, x, domain, policy("∀", ">", domain))


@pytest.mark.parametrize("updates,reason", [
    ({"quantifier": "?"}, "unsupported_quantifier"),
    ({"operator": "=="}, "unsupported_comparison"),
    ({"bound": "sup"}, "inconsistent_quantifier_policy"),
    ({"strict": False}, "inconsistent_quantifier_policy"),
    ({"empty": True}, "inconsistent_quantifier_policy"),
])
def test_inconsistent_quantifier_policy_cannot_select_an_endpoint(updates, reason):
    domain = sp.Interval(0, 1)
    selected = {**policy("∀", ">", domain), **updates}
    with pytest.raises(cap.CapabilityGap, match=reason):
        swap.parameter_linear_range(m + x, m, x, domain, selected)


@pytest.mark.parametrize("conditions,reason", [
    ([], "parameter_conditions_required"),
    ([sp.true], "ordered_relation_required"),
    ([sp.Eq(x, 0)], "ordered_relation_required"),
    ([cap.relation(x**3, ">")], "polynomial_degree"),
    ([cap.relation(x + m, ">")], "rational_parameter_coefficients_required"),
])
def test_normalization_keeps_its_public_quadratic_scope(conditions, reason):
    with pytest.raises(cap.CapabilityGap, match=reason):
        swap.normalize_parameter_conditions(conditions, x)


@pytest.mark.parametrize("combiner,conditions", [
    ("all", [cap.relation(x*x - 1, "<"), cap.relation(x - 1, ">=")]),
    ("any", [cap.relation(x*x - 1, "<"), cap.relation(x - 1, ">=")]),
    ("all", [sp.true, cap.relation(x*x, ">=")]),
    ("any", [sp.false, cap.relation(x*x, ">")]),
])
def test_public_quadratic_combination_keeps_checked_solution_and_own_basis(combiner, conditions):
    expected = cap.solve_conditions(conditions, combiner, x)
    computed = swap.solve_variable_conditions(conditions, combiner, x)
    assert computed["outputs"] == expected["outputs"]
    assert computed["checks"] == expected["checks"]
    assert computed["operations"] == ["variable_condition_sets"]


@pytest.mark.parametrize("conditions,combiner,reason", [
    ([], "all", "parameter_conditions_required"),
    ([cap.relation(x*x, ">")], "xor", "condition_combination_required"),
    ([cap.relation(x**3, ">")], "all", "polynomial_degree"),
    ([cap.relation(x*x + m, ">")], "all", "rational_parameter_coefficients_required"),
    ([cap.relation(x + 1/x, ">")], "all", "nonpolynomial"),
    ([sp.Eq(x, 0)], "all", "ordered_relation_required"),
])
def test_public_quadratic_combination_refuses_uncovered_shapes(conditions, combiner, reason):
    with pytest.raises(cap.CapabilityGap, match=reason):
        swap.solve_variable_conditions(conditions, combiner, x)
