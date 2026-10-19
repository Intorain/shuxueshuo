"""Affine quantified-variable envelopes with exact parameter sign evidence.

The variable is the quantified letter; the parameter is the letter being
solved for. Closed rational intervals support every affine slope. Open finite
intervals currently require a globally strict slope sign or an identically
zero slope: a parameter-dependent zero slope changes endpoint attainment and
must not silently inherit the endpoint's exclusion.
"""

import sympy as sp

from ....problem_understanding.notation_semantics import bounded_expand
from . import (
    CapabilityGap,
    LocalCheckFailed,
    normalize_to_zero,
    polynomial,
    result,
    transform_param_inequality,
)
from .quantified import solve_conditions
from .ranges import interval_domain


def _parameter_polynomial(expression, parameter):
    value = polynomial(expression, parameter)
    if any(coefficient.is_Rational is not True for coefficient in value.all_coeffs()):
        raise CapabilityGap("rational_parameter_coefficients_required")
    return value


def _affine_input(expression, variable, parameter):
    if (
        not isinstance(variable, sp.Symbol) or not isinstance(parameter, sp.Symbol)
        or variable == parameter or variable.is_real is not True or parameter.is_real is not True
    ):
        raise CapabilityGap("distinct_real_symbol_roles_required")
    if not isinstance(expression, sp.Expr) or expression.free_symbols - {variable, parameter}:
        raise CapabilityGap("single_parameter_affine_required")
    expanded = bounded_expand(expression)
    affine = polynomial(expanded, variable, maximum=1)
    slope, intercept = affine.nth(1), affine.nth(0)
    _parameter_polynomial(slope, parameter)
    _parameter_polynomial(intercept, parameter)
    return slope, intercept


def _slope_sign(slope, parameter):
    poly = _parameter_polynomial(slope, parameter)
    if poly.is_zero:
        return "zero", {"kind": "identically_zero_affine_slope", "passed": True,
                        "slope": slope}
    if poly.degree() == 0:
        sign = "positive" if slope.is_positive else "negative"
        return sign, {"kind": "constant_affine_slope_sign", "passed": True,
                      "slope": slope, "sign": sign}
    if poly.degree() == 2:
        a, b, c = poly.all_coeffs()
        vertex = -b / (2 * a)
        value = c - b * b / (4 * a)
        square = a * (parameter - vertex)**2 + value
        strict = (a > 0 and value > 0) or (a < 0 and value < 0)
        sign = ("positive" if a > 0 else "negative") if strict else "unknown"
        return sign, {"kind": "affine_slope_square_certificate", "passed":
                      bounded_expand(square - slope) == 0,
                      "slope": slope, "square": square, "coefficient": a,
                      "vertex": vertex, "value": value, "sign": sign,
                      "parameter_domain": sp.S.Reals}
    return "unknown", {"kind": "nonconstant_linear_affine_slope", "passed": True,
                       "slope": slope, "sign": "unknown", "parameter_domain": sp.S.Reals}


def _range_input(expression, variable, parameter, domain, policy):
    slope, intercept = _affine_input(expression, variable, parameter)
    interval_domain(domain, finite=True)
    if any(point.is_Rational is not True for point in (domain.start, domain.end)):
        raise CapabilityGap("rational_interval_endpoints_required")
    if not isinstance(policy, dict) or policy.get("quantifier") not in ("∀", "∃"):
        raise CapabilityGap("unsupported_quantifier")
    operator = policy.get("operator")
    if operator not in (">", ">=", "<", "<="):
        raise CapabilityGap("unsupported_comparison")
    expected = "sup" if (operator in (">", ">=")) == (policy["quantifier"] == "∀") else "inf"
    if (policy.get("bound") != expected or policy.get("strict") is not (operator in (">", "<"))
            or policy.get("empty")):
        raise CapabilityGap("inconsistent_quantifier_policy")
    sign, certificate = _slope_sign(slope, parameter)
    if sign == "unknown" and (domain.left_open or domain.right_open):
        raise CapabilityGap("open_interval_parameter_slope_cases_required")
    return slope, intercept, sign, certificate


def validate_variable_swap(expression, variable, parameter, domain, policy):
    """Pure admission check, without emitting a successful capability trace."""
    _range_input(expression, variable, parameter, domain, policy)


def reorder_by_variable(expression, variable, parameter):
    slope, intercept = _affine_input(expression, variable, parameter)
    reordered = slope * variable + intercept
    return result(
        {"expression": reordered, "slope": slope, "intercept": intercept,
         "variable": variable, "parameter": parameter},
        ["identity"],
        [{"kind": "affine_reordering_identity", "passed":
          bounded_expand(reordered - expression) == 0,
          "original": expression, "reordered": reordered},
         {"kind": "affine_symbol_roles", "passed":
          not slope.has(variable) and not intercept.has(variable)
          and (slope.free_symbols | intercept.free_symbols) <= {parameter},
          "variable": variable, "parameter": parameter,
          "slope": slope, "intercept": intercept}],
    )


def parameter_linear_range(expression, variable, parameter, domain, policy):
    """Compute the bound of an affine function needed by a quantified policy.

The policy compares zero with this expression. For unknown slope signs on a
closed interval, both endpoint conditions are necessary for a universal
quantifier, while either endpoint supplies an existential witness.
"""
    slope, intercept, sign, certificate = _range_input(
        expression, variable, parameter, domain, policy,
    )
    endpoints = [
        {"point": point, "value": bounded_expand(slope * point + intercept),
         "attained": attained}
        for point, attained in ((domain.start, not domain.left_open),
                                (domain.end, not domain.right_open))
    ]
    bound = policy["bound"]
    selected_endpoint = None
    if sign == "zero":
        midpoint = (domain.start + domain.end) / 2
        candidates = [{"point": midpoint, "value": intercept, "attained": True}]
        mode = "constant"
    elif sign == "unknown":
        candidates, mode = endpoints, "both_endpoints"
    else:
        right = (sign == "positive") == (bound == "sup")
        candidates = [endpoints[int(right)]]
        mode = "right_endpoint" if right else "left_endpoint"
        selected_endpoint = candidates[0]["point"]
    checks = [
        {"kind": "affine_range_identity", "passed":
         bounded_expand(expression - slope * variable - intercept) == 0,
         "slope": slope, "intercept": intercept, "variable": variable,
         "parameter": parameter},
        certificate,
        {"kind": "affine_endpoint_substitution", "passed": all(
            bounded_expand(expression.subs(variable, row["point"]) - row["value"]) == 0
            for row in endpoints), "values": endpoints},
        {"kind": "constant_interior_attainment" if sign == "zero" else "affine_bound_envelope",
         "passed": (domain.contains(candidates[0]["point"]) is sp.true if sign == "zero" else
                    sign != "unknown" or (not domain.left_open and not domain.right_open)),
         "domain": domain, "bound": bound, "endpoint_mode": mode,
         "candidates": candidates},
    ]
    return result(
        {"range": {"bound": bound, "candidates": candidates},
         "slope": slope, "intercept": intercept, "slope_sign": sign,
         "slope_certificate": certificate,
         "endpoint_values": endpoints, "endpoint_mode": mode,
         "selected_endpoint": selected_endpoint},
        ["constant_range" if sign == "zero" else "linear_interval_extrema"], checks,
    )


def normalize_parameter_conditions(conditions, variable):
    """Record real move-to-zero and positive-scaling calls for every endpoint."""
    if not isinstance(variable, sp.Symbol) or variable.is_real is not True:
        raise CapabilityGap("real_parameter_symbol_required")
    if not isinstance(conditions, (list, tuple)) or not conditions:
        raise CapabilityGap("parameter_conditions_required")
    normalized, operations, checks = [], [], []
    for condition in conditions:
        if getattr(condition, "rel_op", None) not in (">", ">=", "<", "<="):
            raise CapabilityGap("ordered_relation_required")
        _parameter_polynomial(bounded_expand(condition.lhs - condition.rhs), variable)
        moved = normalize_to_zero(condition, variable)
        scaled = transform_param_inequality(moved["outputs"]["relation"], variable)
        transformed = scaled["outputs"]["relation"]
        normalized.append(transformed)
        operations.extend([*moved["operations"], *scaled["operations"]])
        checks.append({"kind": "parameter_condition_normalization", "passed": True,
                       "original": condition, "normalized": transformed,
                       "move_checks": moved["checks"], "scale_checks": scaled["checks"]})
    return result({"conditions": normalized, "original_conditions": list(conditions)},
                  list(dict.fromkeys(operations)), checks)


def solve_variable_conditions(conditions, combiner, variable):
    """Use the checked condition solver within the public quadratic scope."""
    if not isinstance(variable, sp.Symbol) or variable.is_real is not True:
        raise CapabilityGap("real_parameter_symbol_required")
    if not isinstance(conditions, (list, tuple)) or not conditions:
        raise CapabilityGap("parameter_conditions_required")
    for condition in conditions:
        if condition is sp.true or condition is sp.false:
            continue
        if getattr(condition, "rel_op", None) not in (">", ">=", "<", "<="):
            raise CapabilityGap("ordered_relation_required")
        _parameter_polynomial(bounded_expand(condition.lhs - condition.rhs), variable)
    computed = solve_conditions(conditions, combiner, variable)
    return result(computed["outputs"], ["variable_condition_sets"], computed["checks"])


def solve_affine_condition(condition, variable):
    """Solve a constant/linear endpoint without claiming a quadratic method."""
    polynomial(bounded_expand(condition.lhs - condition.rhs), variable, maximum=1)
    computed = solve_variable_conditions([condition], "all", variable)
    return result({"solution": computed["outputs"]["solution"]},
                  computed["operations"], computed["checks"])


def combine_variable_solutions(conditions, first, second, combiner, variable):
    """Combine the one/two actual endpoint results, checking every child output."""
    from .cases import exact_set_equal

    if len(conditions) not in (1, 2) or (len(conditions) == 1) != (second is None):
        raise LocalCheckFailed("incomplete_endpoint_solutions")
    solutions = [first] if second is None else [first, second]
    checked = solve_variable_conditions(conditions, combiner, variable)
    if not all(exact_set_equal(actual, expected) for actual, expected in
               zip(solutions, checked["outputs"]["solutions"], strict=True)):
        raise LocalCheckFailed("incorrect_endpoint_solution")
    checks = [*checked["checks"], {"kind": "actual_child_solutions", "passed": True,
                                 "solutions": solutions, "combiner": combiner}]
    return result({"solution": checked["outputs"]["solution"], "solutions": solutions},
                  ["variable_condition_sets"], checks)
