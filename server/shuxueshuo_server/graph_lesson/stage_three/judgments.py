"""Explicit deterministic decisions; no model fallback."""

import sympy as sp

from .capabilities import CapabilityGap, execute, polynomial, residual
from .capabilities.cases import partition_cases


def nondegenerate(expression, variable):
    p = polynomial(expression, variable)
    if p.degree() != 2 or p.LC().free_symbols or p.LC().is_nonzero is not True:
        raise CapabilityGap("degenerate_branches_unavailable")
    return {
        "selected": "nondegenerate",
        "evidence": {
            "coefficient": p.LC(),
            "nonzero": True,
            "reason": "constant_nonzero_no_cases",
        },
    }


def degenerate_branches(relation, variable, parameter, domain, quantifier):
    coefficient, zeros, cases = partition_cases(
        relation, variable, parameter, domain, quantifier
    )
    has_degenerate = zeros != sp.S.EmptySet
    return {
        "selected": "degenerate" if has_degenerate else "nondegenerate",
        "cases": cases,
        "coefficient": coefficient,
        "has_degenerate": has_degenerate,
        "evidence": {
            "coefficient": coefficient, "zero_set": zeros,
            "conditions": [case["condition"] for case in cases],
            "domains": [case["domain"] for case in cases],
            "reason": "zero_and_nonzero_coefficient_partition",
        },
    }


def parameter_solver(relation, variable):
    degree = polynomial(residual(relation), variable, maximum=48).degree()
    choice = "quadratic" if degree <= 2 else "polynomial"
    return {"selected": choice, "choice": choice, "evidence": {"degree": degree}}


def polynomial_relation(relation, variable):
    if relation.rhs != 0:
        raise CapabilityGap("normalization_required")
    expression = residual(relation)
    polynomial(expression, variable)
    return {
        "selected": "normalized",
        "expression": expression,
        "strict": relation.rel_op in (">", "<"),
    }


def range_skill(expression, variable, domain):
    if expression.free_symbols - {variable}:
        raise CapabilityGap("range_skill_unavailable")
    if not expression.is_polynomial(variable):
        execute("reciprocal_range", {"expression": expression, "variable": variable, "domain": domain})
        choice = "reciprocal"
        degree = None
    else:
        poly = polynomial(expression, variable)
        if poly.degree() != 2:
            raise CapabilityGap("range_skill_unavailable")
        degree = 2
        choice = "square" if domain == sp.S.Reals else "interval"
        if choice == "interval":
            execute("quadratic_interval_range", {"expression": expression, "variable": variable, "domain": domain})
    return {
        "selected": choice,
        "choice": choice,
        "evidence": {"degree": degree, "domain": domain},
    }


def interval_skill(expression, variable, parameter, domain, policy):
    poly = polynomial(expression, variable)
    if poly.degree() != 2:
        raise CapabilityGap("interval_skill_unavailable")
    parametric = expression.has(parameter)
    inputs = {"expression": expression, "variable": variable, "domain": domain}
    if parametric:
        execute("endpoint_values_extremum", {**inputs, "parameter": parameter, "policy": policy})
    else:
        execute("quadratic_interval_range", inputs)
    return {"selected": "quadratic", "choice": "quadratic", "parametric": parametric,
            "evidence": {"degree": 2, "domain": domain, "parameter_cases": False,
                         "reason": "endpoint_envelope" if parametric else "constant_coefficients"}}


def interval_requirement(domain):
    whole_real = domain == sp.S.Reals
    return {
        "selected": "whole_real" if whole_real else "restricted",
        "requires_interval": not whole_real,
        "evidence": {
            "domain": domain,
            "reason": "whole_real_square_range" if whole_real else "restricted_domain",
        },
    }


REGISTRY = {
    fn.__name__: fn
    for fn in (nondegenerate, degenerate_branches, parameter_solver,
               polynomial_relation, range_skill, interval_requirement, interval_skill)
}
