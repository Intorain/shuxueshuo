"""Reusable interval calculations, quantified endpoints and positive division."""

from itertools import product

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import capabilities as cap
from shuxueshuo_server.graph_lesson.stage_three.trajectory import (
    decode_value,
    encode_value,
)

x, m = sp.symbols("x m", real=True)


def output(name, **inputs):
    computed = cap.execute(name, inputs)
    assert computed["checks"] and all(check["passed"] is True for check in computed["checks"])
    assert decode_value(encode_value(computed)) == computed
    return computed["outputs"]


@pytest.mark.parametrize("quantifier,operator,attained", product(
    ("∀", "∃"), (">", ">=", "<", "<="), (False, True),
))
def test_every_quantifier_direction_strictness_and_attainment(quantifier, operator, attained):
    domain = sp.Interval(1, 2)
    policy = output("select_quantifier_policy", quantifier=quantifier,
                    operator=operator, domain=domain)["policy"]
    greater = operator in (">", ">=")
    expected_bound = "sup" if greater == (quantifier == "∀") else "inf"
    assert policy["bound"] == expected_bound
    range_value = {"inf": sp.Integer(3), "sup": sp.Integer(7),
                   "inf_attained": attained, "sup_attained": attained}
    applied = output("apply_quantifier_policy", policy=policy, range=range_value,
                     parameter_expression=m)
    strict = ((operator in (">", "<")) and attained if quantifier == "∀"
              else (operator in (">", "<")) or not attained)
    expected_op = (">" if strict else ">=") if greater else ("<" if strict else "<=")
    condition = applied["condition"]
    assert condition == cap.relation(m, expected_op, 7 if expected_bound == "sup" else 3)
    assert applied["conditions"] == [condition]
    assert applied["combiner"] == ("all" if quantifier == "∀" else "any")


@pytest.mark.parametrize("quantifier,operator", product(("∀", "∃"), (">", ">=", "<", "<=")))
def test_empty_domain_and_unbounded_range_have_exact_truth(quantifier, operator):
    empty_policy = output("select_quantifier_policy", quantifier=quantifier,
                          operator=operator, domain=sp.S.EmptySet)["policy"]
    empty = output("apply_quantifier_policy", policy=empty_policy, range={}, parameter_expression=m)
    solved = output("solve_conditions", conditions=empty["conditions"],
                    combiner=empty["combiner"], variable=m)["solution"]
    assert solved == (sp.S.Reals if quantifier == "∀" else sp.S.EmptySet)
    policy = output("select_quantifier_policy", quantifier=quantifier,
                    operator=operator, domain=sp.S.Reals)["policy"]
    applied = output("apply_quantifier_policy", policy=policy,
                     range={"inf": -sp.oo, "sup": sp.oo, "inf_attained": False, "sup_attained": False},
                     parameter_expression=m)
    solved = output("solve_conditions", conditions=applied["conditions"],
                    combiner=applied["combiner"], variable=m)["solution"]
    assert solved == (sp.S.EmptySet if quantifier == "∀" else sp.S.Reals)


@pytest.mark.parametrize("expression,domain,expected", [
    (x + 4 / x, sp.Interval(1, 2), sp.Interval(4, 5)),
    (x + 4 / x, sp.Interval.open(1, 2), sp.Interval.open(4, 5)),
    (-x - 4 / x, sp.Interval.open(1, 2), sp.Interval.open(-5, -4)),
    (x + 4 / x, sp.Interval.open(1, 4), sp.Interval.Ropen(4, 5)),
    (x + 4 / x, sp.Interval(1, 4, left_open=True), sp.Interval(4, 5)),
    (x + 4 / x, sp.Interval.open(0, sp.oo), sp.Interval(4, sp.oo)),
    (-x - 4 / x, sp.Interval.open(0, sp.oo), sp.Interval(-sp.oo, -4)),
    (x - 4 / x, sp.Interval.open(0, sp.oo), sp.S.Reals),
    (1 / x + 3, sp.Interval(1, sp.oo), sp.Interval.Lopen(3, 4)),
    (2 * x + 9 / x, sp.Interval.open(1, 3), sp.Interval.Ropen(6 * sp.sqrt(2), 11)),
])
def test_reciprocal_exact_range_and_open_endpoint_attainment(expression, domain, expected):
    computed = output("reciprocal_range", expression=expression, variable=x, domain=domain)
    bounds = computed["range"]
    assert bounds["set"] == expected
    assert bounds["inf"] == expected.inf and bounds["sup"] == expected.sup
    assert bounds["inf_attained"] == (expected.contains(expected.inf) is sp.true)
    assert bounds["sup_attained"] == (expected.contains(expected.sup) is sp.true)
    assert all(row["attained"] for row in computed["critical_points"])


@pytest.mark.parametrize("expression,domain,expected", [
    ((x - 1)**2, sp.Interval.open(0, 2), sp.Interval.Ropen(0, 1)),
    ((x - 1)**2, sp.Interval.open(0, 1), sp.Interval.open(0, 1)),
    (-(x - 1)**2, sp.Interval.open(0, 2), sp.Interval.Lopen(-1, 0)),
    ((x - 1)**2, sp.Interval(2, sp.oo), sp.Interval(1, sp.oo)),
    (2 * x + 1, sp.Interval.open(0, 3), sp.Interval.open(1, 7)),
    (sp.Integer(2), sp.Interval.open(0, 3), sp.FiniteSet(2)),
])
def test_quadratic_and_affine_interval_range(expression, domain, expected):
    assert output("quadratic_interval_range", expression=expression, variable=x,
                  domain=domain)["range"]["set"] == expected


@pytest.mark.parametrize("operator,swap", product((">", ">=", "<", "<="), (False, True)))
def test_positive_division_has_identity_direction_and_domain_evidence(operator, swap):
    initial = cap.relation(x*x + m*x + 4, operator)
    if swap:
        initial = cap.relation(initial.rhs, {">": "<", ">=": "<=", "<": ">", "<=": ">="}[operator], initial.lhs)
    computed = cap.separation_division(initial, m, x, sp.Interval.open(0, 2))
    result = computed["outputs"]
    assert result["already_separated"] is False
    assert result["divisor"] == x
    assert result["divisor_sign"] == "positive"
    assert sp.cancel(cap.residual(result["separated_relation"]) * x - cap.residual(initial)) == 0
    assert "multiply_positive" in computed["operations"]
    assert {check["kind"] for check in computed["checks"]} == {
        "separated_symbol_roles", "positive_scaled_residual", "strict_positive_divisor",
    }


@pytest.mark.parametrize("domain", [sp.Interval(0, 2), sp.Interval(-2, -1), sp.Interval(-1, 1)])
def test_zero_or_negative_divisor_is_a_gap_until_negative_division_batch(domain):
    with pytest.raises(cap.CapabilityGap, match="positive_divisor_required"):
        cap.separation_division(cap.relation(x*x + m*x + 4, "<"), m, x, domain)


@pytest.mark.parametrize("fact_op,quantifier,domain,expected", [
    ("<", "∀", sp.Interval(1, 2), sp.Interval.open(-sp.oo, -5)),
    ("<", "∀", sp.Interval.open(1, 2), sp.Interval(-sp.oo, -5)),
    ("<=", "∀", sp.Interval(1, 2), sp.Interval(-sp.oo, -5)),
    (">", "∃", sp.Interval.open(1, 2), sp.Interval.open(-5, sp.oo)),
    (">=", "∃", sp.Interval.open(1, 2), sp.Interval.open(-5, sp.oo)),
    (">=", "∃", sp.Interval(1, 2), sp.Interval(-5, sp.oo)),
])
def test_endpoint_envelope_and_separation_agree_without_parameter_axis_cases(
    fact_op, quantifier, domain, expected,
):
    function = x*x + m*x + 4
    operator = {"<": ">", "<=": ">=", ">": "<", ">=": "<="}[fact_op]
    policy = output("select_quantifier_policy", quantifier=quantifier,
                    operator=operator, domain=domain)["policy"]
    envelope = output("endpoint_values_extremum", expression=function, variable=x,
                      parameter=m, domain=domain, policy=policy)
    assert len(envelope["endpoint_values"]) == 2
    assert all(row["attained"] == (domain.contains(row["point"]) is sp.true)
               for row in envelope["endpoint_values"])
    applied = output("apply_quantifier_policy", policy=policy, range=envelope["range"],
                     parameter_expression=sp.S.Zero)
    assert output("solve_conditions", conditions=applied["conditions"],
                  combiner=applied["combiner"], variable=m)["solution"] == expected
    separated = output("separation_division", relation=cap.relation(function, fact_op),
                       parameter=m, variable=x, domain=domain)
    policy = output("select_quantifier_policy", quantifier=quantifier,
                    operator=separated["operator"], domain=domain)["policy"]
    bounds = output("reciprocal_range", expression=separated["function"], variable=x,
                    domain=domain)["range"]
    applied = output("apply_quantifier_policy", policy=policy, range=bounds,
                     parameter_expression=separated["parameter_expression"])
    assert output("solve_conditions", conditions=applied["conditions"],
                  combiner=applied["combiner"], variable=m)["solution"] == expected


def test_parameter_vertex_or_opening_requires_later_classification():
    for expression in (x*x + m*x + 4, m*x*x + x + 4):
        with pytest.raises(cap.CapabilityGap, match="parameter_.*cases_required"):
            cap.endpoint_values_extremum(expression, x, m, sp.Interval(1, 2), {"bound": "inf"})


@pytest.mark.parametrize("expression,domain", [
    (x + 4/x, sp.Interval(-2, -1)),
    (x + 4/x, sp.Interval(0, 2)),
    (x + m/x, sp.Interval(1, 2)),
    (x + 1/(x + 1), sp.Interval(1, 2)),
])
def test_unsupported_reciprocal_shape_never_becomes_numeric_approximation(expression, domain):
    with pytest.raises(cap.CapabilityGap):
        cap.reciprocal_range(expression, x, domain)
