"""Negative division, reciprocal composition and affine boundary evidence."""

from copy import deepcopy
from itertools import product

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three.capabilities import (
    CapabilityGap,
    LocalCheckFailed,
    relation,
    residual,
)
from shuxueshuo_server.graph_lesson.stage_three.capabilities.quantified import (
    apply_quantifier_policy,
    select_quantifier_policy,
)
from shuxueshuo_server.graph_lesson.stage_three.capabilities.ranges import (
    linear_range,
    quadratic_interval_range,
    reciprocal_range,
)
from shuxueshuo_server.graph_lesson.stage_three.capabilities.reciprocal import (
    inspect_reciprocal,
    reciprocal_of_range,
)
from shuxueshuo_server.graph_lesson.stage_three.capabilities.separation import (
    inspect_separation,
    separate_parameter,
    separation_division,
)
from shuxueshuo_server.graph_lesson.stage_three.trajectory import (
    decode_value,
    encode_value,
)

x, a = sp.symbols("x a", real=True)


def outputs(computed):
    assert computed["checks"] and all(check["passed"] is True for check in computed["checks"])
    assert decode_value(encode_value(computed)) == computed
    return computed["outputs"]


def bounds(domain):
    return {"inf": domain.inf, "sup": domain.sup,
            "inf_attained": domain.contains(domain.inf) is sp.true,
            "sup_attained": domain.contains(domain.sup) is sp.true, "set": domain}


@pytest.mark.parametrize("operator,swapped,domain", product(
    (">", ">=", "<", "<="), (False, True),
    (sp.Interval.open(-sp.oo, 0), sp.Interval(-3, -1), sp.Interval.Lopen(-3, -1)),
))
def test_negative_divisor_reverses_each_relation_with_positive_scaled_residual(operator, swapped, domain):
    original = relation(x*x + a*x + 2, operator)
    if swapped:
        original = relation(0, {">": "<", ">=": "<=", "<": ">", "<=": ">="}[operator], original.lhs)
    prepared = outputs(separate_parameter(original, a, x, domain))["candidate"]
    evaluated = separation_division(original, a, x, domain, prepared=prepared)
    values = outputs(evaluated)
    assert values["divisor"] == x
    assert values["divisor_sign"] == "negative"
    assert values["transformation"] == "negative_division"
    assert values["operator"] == {">": "<", ">=": "<=", "<": ">", "<=": ">="}[operator]
    assert values["candidate"]["divisor_sign"] == "negative"
    assert sp.cancel(residual(values["separated_relation"]) * (-x) - residual(original)) == 0
    assert evaluated["operations"] == ["add_both_sides", "multiply_negative"]
    assert any(check["kind"] == "strict_negative_divisor" for check in evaluated["checks"])
    assert next(check for check in evaluated["checks"] if check["kind"] == "positive_scaled_residual")["positive_scale"] == -x


def test_prepared_negative_division_is_checked_without_reinspecting(monkeypatch):
    original = relation(x*x + a*x + 2, ">=")
    domain = sp.Interval.open(-sp.oo, 0)
    prepared = inspect_separation(original, a, x, domain)["outputs"]

    def forbidden(*_args, **_kwargs):
        raise AssertionError("prepared candidates must not be recomputed")

    monkeypatch.setattr("shuxueshuo_server.graph_lesson.stage_three.capabilities.separation.inspect_separation", forbidden)
    assert outputs(separation_division(original, a, x, domain, prepared=prepared))["operator"] == "<="
    wrong_sign = deepcopy(prepared)
    wrong_sign["divisor_sign"] = "positive"
    with pytest.raises(LocalCheckFailed):
        separation_division(original, a, x, domain, prepared=wrong_sign)
    wrong_direction = deepcopy(prepared)
    wrong_direction["operator"] = ">="
    wrong_direction["separated_relation"] = relation(a, ">=", wrong_direction["function"])
    with pytest.raises(LocalCheckFailed):
        separation_division(original, a, x, domain, prepared=wrong_direction)


@pytest.mark.parametrize("domain", [sp.Interval(-2, 0), sp.Interval(-2, 1), sp.S.Reals])
def test_divisor_zero_or_sign_change_remains_a_capability_gap(domain):
    with pytest.raises(CapabilityGap, match="strict_divisor_sign_required"):
        separate_parameter(relation(x*x + a*x + 2, ">="), a, x, domain)


@pytest.mark.parametrize("expression,domain,expected", [
    (-x - 2/x, sp.Interval.open(-sp.oo, 0), sp.Interval(2*sp.sqrt(2), sp.oo)),
    (-x - 8/x, sp.Interval.open(-sp.oo, 0), sp.Interval(4*sp.sqrt(2), sp.oo)),
    (-x - 2/x, sp.Interval(-sp.oo, -2), sp.Interval(3, sp.oo)),
    (-x - 2/x, sp.Interval.open(-sp.oo, -2), sp.Interval.open(3, sp.oo)),
    (x + 4/x, sp.Interval(-4, -1), sp.Interval(-5, -4)),
    (x + 4/x, sp.Interval.open(-4, -1), sp.Interval.Lopen(-5, -4)),
    (x + 4/x, sp.Interval.open(-2, -1), sp.Interval.open(-5, -4)),
    (x - 4/x, sp.Interval.open(-sp.oo, 0), sp.S.Reals),
    (1/x + 3, sp.Interval(-sp.oo, -1), sp.Interval.Ropen(2, 3)),
    (-1/x, sp.Interval.open(-sp.oo, 0), sp.Interval.open(0, sp.oo)),
])
def test_negative_reciprocal_range_has_exact_limits_stationary_point_and_attainment(expression, domain, expected):
    computed = reciprocal_range(expression, x, domain)
    values = outputs(computed)
    assert values["domain_sign"] == "negative"
    assert values["range"] == bounds(expected)
    assert all(point["point"].is_negative is True for point in values["critical_points"])
    assert all(point["attained"] for point in values["critical_points"])
    assert any(check["kind"] == "negative_domain_no_poles" for check in computed["checks"])


@pytest.mark.parametrize("domain", [sp.Interval(-1, 0), sp.Interval(0, 1), sp.Interval(-1, 1)])
def test_reciprocal_sum_refuses_a_pole_inside_or_at_a_closed_boundary(domain):
    with pytest.raises(CapabilityGap, match="strict_nonzero_interval_required"):
        reciprocal_range(-x - 2/x, x, domain)


@pytest.mark.parametrize("source,expected", [
    (sp.Interval(2, 6), sp.Interval(sp.Rational(1, 6), sp.Rational(1, 2))),
    (sp.Interval.open(2, 6), sp.Interval.open(sp.Rational(1, 6), sp.Rational(1, 2))),
    (sp.Interval.Lopen(2, 6), sp.Interval.Ropen(sp.Rational(1, 6), sp.Rational(1, 2))),
    (sp.Interval(2, sp.oo), sp.Interval.Lopen(0, sp.Rational(1, 2))),
    (sp.Interval.open(0, 6), sp.Interval.open(sp.Rational(1, 6), sp.oo)),
    (sp.Interval.open(0, sp.oo), sp.Interval.open(0, sp.oo)),
    (sp.Interval(-6, -2), sp.Interval(-sp.Rational(1, 2), -sp.Rational(1, 6))),
    (sp.Interval.open(-6, -2), sp.Interval.open(-sp.Rational(1, 2), -sp.Rational(1, 6))),
    (sp.Interval.Lopen(-6, -2), sp.Interval.Ropen(-sp.Rational(1, 2), -sp.Rational(1, 6))),
    (sp.Interval(-sp.oo, -2), sp.Interval.Ropen(-sp.Rational(1, 2), 0)),
    (sp.Interval.Ropen(-6, 0), sp.Interval(-sp.oo, -sp.Rational(1, 6))),
    (sp.Interval.open(-sp.oo, 0), sp.Interval.open(-sp.oo, 0)),
    (sp.FiniteSet(2), sp.FiniteSet(sp.Rational(1, 2))),
    (sp.FiniteSet(-2), sp.FiniteSet(-sp.Rational(1, 2))),
])
def test_reciprocal_range_composition_reverses_bounds_without_losing_attainment(source, expected):
    computed = reciprocal_of_range(bounds(source))
    values = outputs(computed)
    assert values["range"] == bounds(expected)
    assert computed["operations"] == ["reciprocal_of_range"]
    assert values["sign"] == ("positive" if source.sup.is_extended_positive else "negative")


@pytest.mark.parametrize("source", [sp.Interval(0, 2), sp.Interval(-2, 0), sp.Interval(-2, 2), sp.FiniteSet(0)])
def test_reciprocal_composition_refuses_zero(source):
    with pytest.raises(CapabilityGap, match="reciprocal_range_contains_zero"):
        reciprocal_of_range(bounds(source))


def test_reciprocal_composition_rejects_inconsistent_range_certificates():
    source = bounds(sp.Interval(2, 6))
    for change in ({"set": sp.Interval(2, 7)}, {"inf_attained": False},
                   {"inf": sp.Integer(7)}, {"sup": sp.oo, "sup_attained": True},
                   {"inf_attained": "false"}):
        with pytest.raises(LocalCheckFailed):
            reciprocal_of_range({**source, **change})


@pytest.mark.parametrize("expression,expected", [
    (1/(x*x - x), x*x - x),
    (2/(x*x - x), (x*x - x)/2),
    (-1/(x*x + 1), -x*x - 1),
    (1/(x + 1), x + 1),
])
def test_reciprocal_inspection_normalizes_constant_numerators(expression, expected):
    assert sp.expand(inspect_reciprocal(expression, x)["denominator"] - expected) == 0


@pytest.mark.parametrize("expression", [sp.S.Zero, sp.S.One, 1/(x**3 + 1), a/(x*x - x), x + 1/x])
def test_reciprocal_inspection_closes_unsupported_shapes(expression):
    with pytest.raises(CapabilityGap):
        inspect_reciprocal(expression, x)


@pytest.mark.parametrize("expression,domain,expected,operation", [
    (2*x + 1, sp.Interval.open(2, 3), sp.Interval.open(5, 7), "linear_interval_extrema"),
    (-2*x + 1, sp.Interval.Lopen(2, 3), sp.Interval.Ropen(-5, -3), "linear_interval_extrema"),
    (-2*x + 1, sp.Interval.open(-sp.oo, 0), sp.Interval.open(1, sp.oo), "linear_interval_extrema"),
    (sp.Integer(-1), sp.Interval.open(2, 3), sp.FiniteSet(-1), "constant_range"),
    (sp.S.Zero, sp.S.Reals, sp.FiniteSet(0), "constant_range"),
])
def test_linear_and_constant_ranges_have_distinct_operations(expression, domain, expected, operation):
    computed = linear_range(expression, x, domain)
    assert outputs(computed)["range"] == bounds(expected)
    assert computed["operations"] == [operation]


def test_q06_and_q07_generic_composition_before_independent_route_validation():
    domain = sp.Interval.open(-sp.oo, 0)
    divided = outputs(separation_division(relation(x*x + a*x + 2, ">="), a, x, domain))
    function_range = outputs(reciprocal_range(divided["function"], x, domain))["range"]
    policy = outputs(select_quantifier_policy("∀", divided["operator"], domain))["policy"]
    assert outputs(apply_quantifier_policy(policy, function_range, a))["condition"] == relation(a, "<=", 2*sp.sqrt(2))

    domain = sp.Interval(2, 3)
    divided = outputs(separation_division(relation(a*x*x - a*x - 1, "<"), a, x, domain))
    denominator = inspect_reciprocal(divided["function"], x)["denominator"]
    denominator_range = outputs(quadratic_interval_range(denominator, x, domain))["range"]
    function_range = outputs(reciprocal_of_range(denominator_range))["range"]
    policy = outputs(select_quantifier_policy("∀", divided["operator"], domain))["policy"]
    assert outputs(apply_quantifier_policy(policy, function_range, a))["condition"] == relation(a, "<", sp.Rational(1, 6))
