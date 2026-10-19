"""Explicit deterministic decisions; no model fallback."""

import sympy as sp

from .capabilities import CapabilityGap, polynomial, residual


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
    poly = polynomial(expression, variable)
    if (
        domain != sp.S.Reals
        or poly.degree() != 2
        or expression.free_symbols - {variable}
    ):
        raise CapabilityGap("range_skill_unavailable")
    return {
        "selected": "square",
        "choice": "square",
        "evidence": {"degree": 2, "domain": domain},
    }


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
    for fn in (nondegenerate, polynomial_relation, range_skill, interval_requirement)
}
