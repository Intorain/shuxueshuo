"""Exact reciprocal composition over an interval that excludes zero."""

import sympy as sp

from . import CapabilityGap, LocalCheckFailed, polynomial, result
from .cases import exact_set_equal
from .ranges import _sign


def inspect_reciprocal(expression, variable):
    """Recognize 1/q(x) without evaluating q's range or matching question data."""
    if expression == 0 or expression.free_symbols - {variable}:
        raise CapabilityGap("numeric_reciprocal_polynomial_required")
    denominator = sp.cancel(1 / expression)
    poly = polynomial(denominator, variable)
    if poly.degree() not in (1, 2) or any(coefficient.is_real is not True for coefficient in poly.all_coeffs()):
        raise CapabilityGap("reciprocal_linear_or_quadratic_required")
    if sp.cancel(expression * denominator - 1) != 0:
        raise CapabilityGap("reciprocal_identity_unproved")
    return {"denominator": poly.as_expr()}


def _checked_range(bounds):
    lower, upper = bounds["inf"], bounds["sup"]
    low_attained, high_attained = bounds["inf_attained"], bounds["sup_attained"]
    if any(type(flag) is not bool for flag in (low_attained, high_attained)):
        raise LocalCheckFailed("range_attainment_required")
    if any(not isinstance(value, sp.Expr) or value.free_symbols or value.is_extended_real is not True
           for value in (lower, upper)):
        raise CapabilityGap("numeric_extended_real_range_required")
    if (lower in (-sp.oo, sp.oo) and low_attained) or (upper in (-sp.oo, sp.oo) and high_attained):
        raise LocalCheckFailed("infinite_bound_cannot_be_attained")
    if lower == upper:
        if lower in (-sp.oo, sp.oo) or not low_attained or not high_attained:
            raise LocalCheckFailed("nonempty_constant_range_required")
        expected = sp.FiniteSet(lower)
    else:
        if _sign(upper - lower) <= 0:
            raise LocalCheckFailed("ordered_range_bounds_required")
        expected = sp.Interval(lower, upper, left_open=not low_attained, right_open=not high_attained)
    if "set" in bounds and not exact_set_equal(expected, bounds["set"]):
        raise LocalCheckFailed("range_set_disagrees_with_bounds")
    if _sign(lower) > 0 or (lower == 0 and not low_attained):
        sign = "positive"
    elif _sign(upper) < 0 or (upper == 0 and not high_attained):
        sign = "negative"
    else:
        raise CapabilityGap("reciprocal_range_contains_zero")
    return expected, sign


def reciprocal_of_range(range):
    """Apply the strictly decreasing reciprocal on a certified nonzero range."""
    source_set, sign = _checked_range(range)

    def reciprocal_bound(value):
        if value in (-sp.oo, sp.oo):
            return sp.S.Zero
        if value == 0:
            return sp.oo if sign == "positive" else -sp.oo
        return sp.simplify(1 / value)

    lower, upper = reciprocal_bound(range["sup"]), reciprocal_bound(range["inf"])
    low_attained, high_attained = range["sup_attained"], range["inf_attained"]
    transformed_set = (sp.FiniteSet(lower) if lower == upper else
                       sp.Interval(lower, upper, left_open=not low_attained, right_open=not high_attained))
    transformed = {"inf": lower, "sup": upper, "inf_attained": low_attained,
                   "sup_attained": high_attained, "set": transformed_set}
    return result(
        {"range": transformed, "sign": sign},
        ["reciprocal_of_range"],
        [{"kind": "nonzero_connected_range", "passed": True, "set": source_set, "sign": sign},
         {"kind": "reciprocal_decreasing", "passed": True, "sign": sign},
         {"kind": "reversed_reciprocal_bounds", "passed": True,
          "source": range, "result": transformed}],
    )
