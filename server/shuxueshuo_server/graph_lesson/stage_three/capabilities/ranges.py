"""Exact interval extrema with explicit attainment and endpoint certificates."""

import sympy as sp

from ....problem_understanding.notation_semantics import bounded_expand
from . import CapabilityGap, polynomial, result


def _sign(value):
    value = sp.simplify(value)
    if value is sp.oo:
        return 1
    if value is -sp.oo:
        return -1
    if value.is_zero is True:
        return 0
    if value.is_positive is True:
        return 1
    if value.is_negative is True:
        return -1
    raise CapabilityGap("range_comparison_unknown")


def interval_domain(domain, *, finite=False, positive=False):
    if not isinstance(domain, sp.Interval):
        raise CapabilityGap("nonempty_interval_required")
    if finite and (domain.start is -sp.oo or domain.end is sp.oo):
        raise CapabilityGap("bounded_interval_required")
    if any(point.free_symbols for point in (domain.start, domain.end)):
        raise CapabilityGap("numeric_interval_required")
    if positive and (
        domain.start is -sp.oo or _sign(domain.start) < 0
        or (domain.start == 0 and not domain.left_open)
    ):
        raise CapabilityGap("positive_interval_required")


def _finite_endpoint(expression, variable, point, attained):
    value = sp.simplify(expression.subs(variable, point))
    if value.is_real is not True or value.free_symbols:
        raise CapabilityGap("finite_endpoint_value_required")
    return {"point": point, "value": value, "attained": attained}


def _bounds(candidates):
    if not candidates:
        raise CapabilityGap("range_candidates_required")
    low, high = candidates[0]["value"], candidates[0]["value"]
    for row in candidates[1:]:
        value = row["value"]
        if value != low and _sign(value - low) < 0:
            low = value
        if value != high and _sign(value - high) > 0:
            high = value
    low_taken = any(row["attained"] and _sign(row["value"] - low) == 0
                    for row in candidates if row["value"] not in (-sp.oo, sp.oo))
    high_taken = any(row["attained"] and _sign(row["value"] - high) == 0
                     for row in candidates if row["value"] not in (-sp.oo, sp.oo))
    value_set = (sp.FiniteSet(low) if low == high else
                 sp.Interval(low, high, left_open=not low_taken, right_open=not high_taken))
    return {"inf": low, "sup": high, "inf_attained": low_taken,
            "sup_attained": high_taken, "set": value_set}


def _contains(domain, point):
    included = domain.contains(point)
    if included is not sp.true and included is not sp.false:
        raise CapabilityGap("critical_point_membership_unknown")
    return included is sp.true


def quadratic_interval_range(expression, variable, domain):
    """Range of a numeric quadratic/affine polynomial on one exact interval."""
    interval_domain(domain)
    poly = polynomial(expression, variable)
    if expression.free_symbols - {variable}:
        raise CapabilityGap("numeric_quadratic_required")
    if any(coefficient.is_real is not True for coefficient in poly.all_coeffs()):
        raise CapabilityGap("real_coefficients_required")
    if poly.degree() <= 0:
        value = poly.nth(0)
        bounds = {"inf": value, "sup": value, "inf_attained": True,
                  "sup_attained": True, "set": sp.FiniteSet(value)}
        return result({"range": bounds, "endpoint_values": [], "critical_points": []},
                      ["interval_extrema"],
                      [{"kind": "constant_interval_range", "passed": True,
                        "value": value, "domain": domain}])
    endpoints = []
    for point, closed in ((domain.start, not domain.left_open),
                          (domain.end, not domain.right_open)):
        if point in (-sp.oo, sp.oo):
            leading_sign = _sign(poly.LC())
            direction = leading_sign if poly.degree() == 2 or point is sp.oo else -leading_sign
            endpoints.append({"point": point, "value": direction * sp.oo, "attained": False})
        else:
            endpoints.append(_finite_endpoint(expression, variable, point, closed))
    critical = []
    if poly.degree() == 2:
        vertex = sp.cancel(-poly.nth(1) / (2 * poly.nth(2)))
        if _contains(domain, vertex):
            critical.append(_finite_endpoint(expression, variable, vertex, True))
    bounds = _bounds([*endpoints, *critical])
    return result(
        {"range": bounds, "endpoint_values": endpoints, "critical_points": critical},
        ["interval_extrema"],
        [{"kind": "polynomial_continuity", "passed": True, "domain": domain},
         {"kind": "complete_critical_points", "passed": True,
          "derivative": sp.diff(expression, variable), "points": critical},
         {"kind": "endpoint_values_and_attainment", "passed": True, "values": endpoints}],
    )


def reciprocal_coefficients(expression, variable):
    if expression.free_symbols - {variable}:
        raise CapabilityGap("numeric_reciprocal_required")
    numerator = sp.cancel(expression * variable)
    poly = polynomial(numerator, variable)
    if sp.cancel(poly.as_expr() / variable - expression) != 0:
        raise CapabilityGap("reciprocal_sum_required")
    a, c, b = poly.nth(2), poly.nth(1), poly.nth(0)
    if any(value.is_real is not True for value in (a, c, b)) or b == 0:
        raise CapabilityGap("reciprocal_sum_required")
    return a, c, b


def nonzero_interval_sign(domain):
    """A single interval must stay strictly on one side of the reciprocal pole."""
    interval_domain(domain)
    lower, upper = _sign(domain.start), _sign(domain.end)
    if lower > 0 or (lower == 0 and domain.left_open):
        return 1
    if upper < 0 or (upper == 0 and domain.right_open):
        return -1
    raise CapabilityGap("strict_nonzero_interval_required")


def reciprocal_range(expression, variable, domain):
    """Range of A*x+B/x+C on either half-axis, with one-sided pole limits."""
    domain_sign = nonzero_interval_sign(domain)
    a, c, b = reciprocal_coefficients(expression, variable)
    endpoints = []
    for point, closed in ((domain.start, not domain.left_open),
                          (domain.end, not domain.right_open)):
        if point == 0:
            value = domain_sign * _sign(b) * sp.oo
        elif point in (-sp.oo, sp.oo):
            value = c if a == 0 else _sign(point) * _sign(a) * sp.oo
        else:
            endpoints.append(_finite_endpoint(expression, variable, point, closed))
            continue
        endpoints.append({"point": point, "value": value, "attained": False})
    critical = []
    if a != 0 and _sign(b / a) > 0:
        point = domain_sign * sp.sqrt(b / a)
        if _contains(domain, point):
            critical.append(_finite_endpoint(expression, variable, point, True))
    derivative = a - b / variable**2
    return result(
        {"range": _bounds([*endpoints, *critical]), "endpoint_values": endpoints,
         "critical_points": critical, "derivative": derivative,
         "domain_sign": "positive" if domain_sign > 0 else "negative"},
        ["reciprocal_extrema"],
        [{"kind": "reciprocal_identity", "passed": sp.cancel(
            expression - (a * variable + b / variable + c)) == 0},
         {"kind": "positive_domain_no_poles" if domain_sign > 0 else "negative_domain_no_poles",
          "passed": True, "domain": domain},
         {"kind": "complete_critical_points", "passed": True,
          "derivative": derivative, "points": critical},
         {"kind": "endpoint_limits_and_attainment", "passed": True, "values": endpoints}],
    )


def linear_range(expression, variable, domain):
    """Numeric affine range, including a constant attained on an open interval."""
    poly = polynomial(expression, variable, maximum=1)
    computed = quadratic_interval_range(expression, variable, domain)
    constant = poly.nth(1) == 0
    return result(
        {**computed["outputs"], "slope": poly.nth(1), "constant": poly.nth(0)},
        ["constant_range" if constant else "linear_interval_extrema"],
        [*computed["checks"], {"kind": "constant_affine_range" if constant else "affine_monotonicity",
                              "passed": True, "slope": poly.nth(1), "domain": domain}],
    )


def endpoint_values_extremum(expression, variable, parameter, domain, policy):
    """Endpoint envelope without comparing parameter-dependent endpoint values.

    A strictly convex quadratic has its supremum among endpoint limits; a
    strictly concave one has its infimum there. Endpoint constraints can thus
    be combined later without classifying the parameter-dependent vertex.
    """
    interval_domain(domain, finite=True)
    poly = polynomial(expression, variable)
    if poly.degree() != 2 or expression.free_symbols - {variable, parameter}:
        raise CapabilityGap("single_parameter_quadratic_required")
    coefficient = poly.nth(2)
    if coefficient.free_symbols or policy.get("bound") not in ("inf", "sup"):
        raise CapabilityGap("parameter_extremum_cases_required")
    sign = _sign(coefficient)
    if (policy["bound"] == "sup" and sign != 1) or (policy["bound"] == "inf" and sign != -1):
        raise CapabilityGap("parameter_vertex_cases_required")
    for value in poly.all_coeffs():
        parameter_poly = polynomial(value, parameter, maximum=48)
        if any(c.is_Rational is not True for c in parameter_poly.all_coeffs()):
            raise CapabilityGap("rational_parameter_coefficients_required")
    endpoints = [
        {"point": point, "value": bounded_expand(expression.subs(variable, point)),
         "attained": closed}
        for point, closed in ((domain.start, not domain.left_open),
                              (domain.end, not domain.right_open))
    ]
    return result(
        {"range": {"bound": policy["bound"], "candidates": endpoints},
         "endpoint_values": endpoints, "coefficient": coefficient},
        ["interval_extrema"],
        [{"kind": "strict_quadratic_endpoint_envelope", "passed": True,
          "coefficient": coefficient, "bound": policy["bound"], "domain": domain},
         {"kind": "endpoint_values_and_attainment", "passed": True, "values": endpoints}],
    )
