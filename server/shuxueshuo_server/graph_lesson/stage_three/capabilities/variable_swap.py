"""Affine quantified-variable envelopes with exact parameter sign evidence.

The variable is the quantified letter; the parameter is the letter being
solved for. A variable slope uses up to three complete exact sign cases on
every finite interval. Disconnected cells with the same sign share one case;
zero cases are constant and attained in the interior.
"""

from copy import deepcopy
from functools import lru_cache

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
    if sign == "unknown" and (domain.left_open or domain.right_open):
        raise CapabilityGap("open_interval_parameter_slope_cases_required")
    return _signed_linear_range(expression, variable, parameter, domain, policy,
                                slope, intercept, sign, certificate)


def _signed_linear_range(expression, variable, parameter, domain, policy, slope, intercept, sign, certificate):
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


@lru_cache(maxsize=32)
def _session_variable_cases(expression, variable, parameter, domain, policy_key):
    """Group complete root cells by slope sign, independent of endpoint closure."""
    from .parametric import _partition_polynomials

    slope, _, sign, certificate = _range_input(expression, variable, parameter, domain, dict(policy_key))
    if sign != "unknown":
        return [{"id": "variable-direct", "kind": "nondegenerate", "mode": "direct",
                 "condition": sp.true, "domain": sp.S.Reals, "value": None,
                 "slope_sign": sign, "certificate": certificate}]
    cells, critical = _partition_polynomials([("slope", slope)], parameter)
    cases = []
    for sign, sign_value in (("positive", 1), ("zero", 0), ("negative", -1)):
        sign_cells = [cell for cell in cells if cell["signs"]["slope"] == sign_value]
        if not sign_cells:
            continue
        case_domain = sp.Union(*(cell["domain"] for cell in sign_cells))
        value = next(iter(case_domain)) if isinstance(case_domain, sp.FiniteSet) and len(case_domain) == 1 else None
        cases.append({
            "id": f"variable-case-{len(cases) + 1}", "kind": "constant" if sign == "zero" else "linear",
            "mode": "classified", "condition": case_domain.as_relational(parameter),
            "domain": case_domain, "value": value, "slope_sign": sign,
            "certificate": {"kind": "affine_slope_case_certificate", "passed": True,
                            "slope": slope, "sign": sign, "parameter_domain": case_domain,
                            "cells": sign_cells, "critical_polynomials": critical},
        })
    return cases


def variable_case_plan(expression, variable, parameter, domain, policy):
    """Program judgment whose returned cases are explicit contract frames."""
    cases = deepcopy(_session_variable_cases(expression, variable, parameter, domain, tuple(sorted(policy.items()))))
    classified = cases[0]["mode"] == "classified"
    return {"selected": "classified" if classified else "direct", "cases": cases,
            "has_cases": classified, "evidence": {
                "kind": "complete_affine_slope_partition", "passed": True,
                "case_domains": [case["domain"] for case in cases],
                "certificates": [case["certificate"] for case in cases],
                "reason": ("Complete slope-root cells are grouped by positive, zero and negative sign; each nonempty sign is one disjoint case."
                           if classified else "One globally valid envelope applies; no parameter case split is required."),
            }}


def parameter_linear_case_range(expression, variable, parameter, domain, policy, case):
    """Check a case certificate, then compute the bound with its actual attainment.

    Keep the original rational parameter formula in a zero case. The case
    domain proves its slope vanishes; the displayed bound equals the original
    intercept on that domain. This avoids introducing algebraic coefficients
    into the public quadratic solve merely by substituting an isolated root.
    """
    cases = _session_variable_cases(expression, variable, parameter, domain, tuple(sorted(policy.items())))
    expected = next((row for row in cases if row["id"] == case.get("id")), None)
    if expected is None or expected != case:
        raise LocalCheckFailed("variable_case_certificate_mismatch")
    slope, intercept, _, _ = _range_input(expression, variable, parameter, domain, policy)
    return _signed_linear_range(expression, variable, parameter, domain, policy, slope, intercept,
                                expected["slope_sign"], deepcopy(expected["certificate"]))


def intersect_variable_case_solution(solution, case):
    if not isinstance(solution, sp.Set) or not isinstance(case.get("domain"), sp.Set):
        raise LocalCheckFailed("variable_case_solution_set_required")
    computed = solution.intersect(case["domain"])
    return result({"solution": computed}, ["variable_case_intersection"], [
        {"kind": "same_case_intersection", "passed": True, "case_id": case["id"],
         "case_domain": case["domain"], "condition_solution": solution, "solution": computed},
    ])


def merge_variable_cases(cases, results):
    from .parametric import merge_interval_cases

    computed = merge_interval_cases(cases, results)
    return result(computed["outputs"], ["variable_case_union"], computed["checks"])
