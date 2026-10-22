"""Affine coordinate changes preserve domains, extrema and attainability."""

from copy import deepcopy
from itertools import product

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three.capabilities import (
    CapabilityGap,
    LocalCheckFailed,
)
from shuxueshuo_server.graph_lesson.stage_three.capabilities.ranges import (
    reciprocal_range,
)
from shuxueshuo_server.graph_lesson.stage_three.capabilities.substitution import (
    inspect_affine_reciprocal,
    restore_substitution_range,
    substitution,
)
from shuxueshuo_server.graph_lesson.stage_three.trajectory import (
    decode_value,
    encode_value,
)

x, t = sp.symbols("x t", real=True)


def output(function, *args, **kwargs):
    computed = function(*args, **kwargs)
    assert computed["checks"] and all(row["passed"] is True for row in computed["checks"])
    assert decode_value(encode_value(computed)) == computed
    return computed["outputs"]


def solve(expression, domain, *, forward=None, variable=x, reserved_symbols=()):
    probe = inspect_affine_reciprocal(expression, variable, domain, reserved_symbols=reserved_symbols)
    changed = output(substitution, expression, variable, domain, probe["new_variable"],
                     forward if forward is not None else probe["forward"])
    computed = output(reciprocal_range, changed["expression"], changed["variable"], changed["domain"])
    restored = output(restore_substitution_range, changed["mapping"], computed["range"],
                      computed["critical_points"], computed["endpoint_values"], computed["turning_point"])
    return changed, computed, restored


def test_translated_reciprocal_returns_original_coordinate_extrema():
    expression = x - 1 + 16 / (x + 1)
    changed, computed, restored = solve(expression, sp.Interval(1, 4))
    assert changed["variable"] == t
    assert changed["mapping"]["forward"] == x + 1
    assert changed["mapping"]["inverse"] == t - 1
    assert sp.cancel(changed["expression"] - (t - 2 + 16 / t)) == 0
    assert changed["domain"] == sp.Interval(2, 5)
    assert computed["range"]["set"] == restored["range"]["set"] == sp.Interval(6, 8)
    assert restored["critical_points"] == [
        {"point": 3, "transformed_point": 4, "value": 6, "attained": True},
    ]
    assert restored["endpoint_values"] == [
        {"point": 1, "transformed_point": 2, "value": 8, "attained": True},
        {"point": 4, "transformed_point": 5, "value": sp.Rational(31, 5), "attained": True},
    ]
    assert restored["turning_point"] == {
        "point": 3, "transformed_point": 4, "value": 6, "minimum": True, "attained": True,
    }


@pytest.mark.parametrize("slope,intercept,left_open,right_open", product(
    (sp.Integer(2), sp.Integer(-3)), (sp.Integer(1), sp.Integer(-4)), (False, True), (False, True),
))
def test_affine_interval_map_reverses_both_endpoint_flags(slope, intercept, left_open, right_open):
    domain = sp.Interval(-2, 5, left_open=left_open, right_open=right_open)
    changed = output(substitution, x*x + 1, x, domain, t, slope*x + intercept)
    first, last = slope*domain.start + intercept, slope*domain.end + intercept
    expected = (sp.Interval(first, last, left_open=left_open, right_open=right_open) if slope > 0 else
                sp.Interval(last, first, left_open=right_open, right_open=left_open))
    assert changed["domain"] == expected
    assert sp.cancel(changed["expression"].subs(t, slope*x + intercept) - x*x - 1) == 0


@pytest.mark.parametrize("domain,forward,expected", [
    (sp.Interval(1, sp.oo), 2*x + 1, sp.Interval(3, sp.oo)),
    (sp.Interval.Lopen(1, sp.oo), -2*x + 1, sp.Interval.open(-sp.oo, -1)),
    (sp.Interval(-sp.oo, 2), -3*x + 4, sp.Interval(-2, sp.oo)),
    (sp.S.Reals, -x + 1, sp.S.Reals),
])
def test_infinite_interval_endpoints_remain_open(domain, forward, expected):
    assert output(substitution, x*x, x, domain, t, forward)["domain"] == expected


@pytest.mark.parametrize("slope,linear,reciprocal,constant", [
    (2, 3, 12, -7), (-3, 2, 18, 5), (5, -2, -8, 3), (-2, 1, -4, -8),
    (sp.Rational(3, 2), 0, 9, 2), (sp.sqrt(2), 1, 4, sp.sqrt(3)),
])
@pytest.mark.parametrize("negative", [False, True])
def test_same_structure_varied_coefficients_and_both_half_axes(slope, linear, reciprocal, constant, negative):
    intercept = sp.Integer(3)
    forward = slope*x + intercept
    target_domain = sp.Interval(-5, -1) if negative else sp.Interval(1, 5)
    source_points = [(point - intercept) / slope for point in (target_domain.start, target_domain.end)]
    domain = sp.Interval(min(source_points), max(source_points))
    expression = linear*forward + reciprocal/forward + constant
    changed, computed, restored = solve(expression, domain, forward=forward)
    expected = reciprocal_range(linear*t + reciprocal/t + constant, t, target_domain)["outputs"]["range"]
    assert changed["domain"] == target_domain
    assert computed["range"] == restored["range"] == expected
    for row in restored["critical_points"] + restored["endpoint_values"]:
        assert domain.contains(row["point"]) is sp.true
        assert sp.simplify(expression.subs(x, row["point"]) - row["value"]) == 0


@pytest.mark.parametrize("domain,expected,attained", [
    (sp.Interval.open(1, 4), sp.Interval.Ropen(6, 8), True),
    (sp.Interval.open(1, 3), sp.Interval.open(6, 8), False),
    (sp.Interval(4, 6), sp.Interval(sp.Rational(31, 5), sp.Rational(51, 7)), False),
    (sp.Interval.open(-1, sp.oo), sp.Interval(6, sp.oo), True),
    (sp.Interval.open(-sp.oo, -1), sp.Interval(-sp.oo, -10), True),
])
def test_restored_turn_can_be_inside_outside_or_excluded_boundary(domain, expected, attained):
    _, _, restored = solve(x - 1 + 16/(x + 1), domain)
    assert restored["range"]["set"] == expected
    assert restored["turning_point"]["attained"] is attained
    assert all(row["attained"] == (domain.contains(row["point"]) is sp.true)
               for row in restored["endpoint_values"])


def test_negative_map_reorders_original_endpoints_with_correct_flags_and_limits():
    expression = -2*x + 1 + 4/(-2*x + 1)
    domain = sp.Interval.open(-sp.oo, sp.Rational(1, 2))
    changed, _, restored = solve(expression, domain, forward=-2*x + 1)
    assert changed["domain"] == sp.Interval.open(0, sp.oo)
    assert restored["range"]["set"] == sp.Interval(4, sp.oo)
    assert restored["endpoint_values"] == [
        {"point": -sp.oo, "transformed_point": sp.oo, "value": sp.oo, "attained": False},
        {"point": sp.Rational(1, 2), "transformed_point": 0, "value": sp.oo, "attained": False},
    ]


@pytest.mark.parametrize("domain", [sp.Interval(-2, 2), sp.Interval(-1, 4), sp.Interval(-3, -1)])
def test_interior_or_included_endpoint_pole_is_a_safe_gap(domain):
    with pytest.raises(CapabilityGap, match="contains_pole"):
        substitution(x - 1 + 16/(x + 1), x, domain, t, x + 1)
    with pytest.raises(CapabilityGap, match="unavailable"):
        inspect_affine_reciprocal(x - 1 + 16/(x + 1), x, domain)


def test_uncancelled_original_tree_preserves_a_removable_hole():
    expression = sp.Mul(x + 4/x, x - 2, sp.Pow(x - 2, -1, evaluate=False), evaluate=False)
    assert sp.cancel(expression - x - 4/x) == 0
    with pytest.raises(CapabilityGap, match="contains_pole"):
        substitution(expression, x, sp.Interval(1, 4), t, x + 1)
    changed = substitution(expression, x, sp.Interval.open(2, 4), t, x + 1)["outputs"]
    assert changed["domain"] == sp.Interval.open(3, 5)


@pytest.mark.parametrize("forward", [sp.S.Zero, sp.Integer(2), x*x + 1, sp.oo*x + 1,
                                      sp.I*x + 1, sp.Symbol("a", real=True)*x + 1])
def test_noninvertible_or_nonnumeric_affine_maps_are_rejected(forward):
    with pytest.raises(CapabilityGap):
        substitution(x*x, x, sp.Interval(1, 2), t, forward)


@pytest.mark.parametrize("domain", [sp.S.EmptySet, sp.FiniteSet(1), sp.Union(sp.Interval(0, 1), sp.Interval(2, 3))])
def test_only_one_nonempty_interval_is_supported(domain):
    with pytest.raises(CapabilityGap, match="interval_required"):
        substitution(x*x, x, domain, t, x + 1)


def test_new_variable_is_deterministic_and_avoids_reserved_parameter_names():
    expression = t - 1 + 16/(t + 1)
    first = inspect_affine_reciprocal(expression, t, sp.Interval(1, 4))
    assert first["new_variable"] == sp.Symbol("u", real=True)
    assert first == inspect_affine_reciprocal(expression, t, sp.Interval(1, 4))
    reserved = sp.symbols("t u v t_1", real=True)
    assert inspect_affine_reciprocal(x + 4/(x + 1), x, sp.Interval(1, 4),
                                     reserved_symbols=reserved)["new_variable"] == sp.Symbol("t_2", real=True)
    with pytest.raises(CapabilityGap, match="fresh_variable"):
        substitution(x*x, x, sp.Interval(1, 4), x, x + 1)
    with pytest.raises(CapabilityGap, match="fresh_variable"):
        substitution(x + t, x, sp.Interval(1, 4), t, x + 1)


@pytest.mark.parametrize("expression", [x + 4/x, x + 4/(x + 1)**2,
                                        x*x + 4/(x + 1), x + 1/(x + 1) + 1/(x + 2)])
def test_affine_reciprocal_admission_requires_a_translation_and_exact_target_shape(expression):
    with pytest.raises(CapabilityGap, match="unavailable"):
        inspect_affine_reciprocal(expression, x, sp.Interval(1, 4))


def test_substitution_preserves_real_domain_restrictions_beyond_rational_poles():
    changed = output(substitution, sp.sqrt(x - 1), x, sp.Interval(1, 4), t, -x + 1)
    assert changed["domain"] == sp.Interval(-3, 0)
    with pytest.raises(CapabilityGap, match="not_defined"):
        substitution(sp.sqrt(x - 1), x, sp.Interval(0, 4), t, x + 1)


@pytest.mark.parametrize("part,field,value", [
    ("mapping", "inverse", t + 1), ("mapping", "domain", sp.Interval(2, 6)),
    ("range", "inf", sp.Integer(5)), ("range", "inf_attained", False),
    ("critical_points", "point", sp.Integer(3)), ("critical_points", "value", sp.Integer(7)),
    ("endpoint_values", "attained", False), ("endpoint_values", "point", sp.Integer(3)),
    ("turning_point", "minimum", False), ("turning_point", "value", sp.Integer(7)),
])
def test_restore_rejects_changed_coordinates_values_flags_mapping_or_bounds(part, field, value):
    changed, computed, _ = solve(x - 1 + 16/(x + 1), sp.Interval(1, 4))
    inputs = {"mapping": deepcopy(changed["mapping"]), **{
        key: deepcopy(computed[key]) for key in ("range", "critical_points", "endpoint_values", "turning_point")
    }}
    target = inputs[part][0] if isinstance(inputs[part], list) else inputs[part]
    target[field] = value
    with pytest.raises(LocalCheckFailed):
        restore_substitution_range(**inputs)


def test_restore_cannot_drop_an_attained_turning_point():
    changed, computed, _ = solve(x - 1 + 16/(x + 1), sp.Interval(1, 4))
    with pytest.raises(LocalCheckFailed, match="missing_from_critical_points"):
        restore_substitution_range(changed["mapping"], computed["range"], [],
                                   computed["endpoint_values"], computed["turning_point"])


def test_restore_cannot_forge_a_monotone_range_by_dropping_both_stationary_evidences():
    changed, computed, _ = solve(x - 1 + 16/(x + 1), sp.Interval(1, 4))
    forged = {"inf": sp.Rational(31, 5), "sup": sp.Integer(8),
              "inf_attained": True, "sup_attained": True, "set": sp.Interval(sp.Rational(31, 5), 8)}
    with pytest.raises(LocalCheckFailed, match="incomplete_critical"):
        restore_substitution_range(changed["mapping"], forged, [], computed["endpoint_values"], None)


def test_restore_cannot_suppress_a_turning_point_outside_the_restricted_interval():
    changed, computed, _ = solve(x - 1 + 16/(x + 1), sp.Interval(4, 6))
    assert computed["critical_points"] == []
    with pytest.raises(LocalCheckFailed, match="incomplete_turning"):
        restore_substitution_range(changed["mapping"], computed["range"], [],
                                   computed["endpoint_values"], None)
