"""Role-based positive division, with an explicit scaled-residual certificate."""

import sympy as sp

from ....problem_understanding.notation_semantics import bounded_expand
from . import CapabilityGap, polynomial, residual, result
from . import relation as make_relation
from .ranges import quadratic_interval_range


def _positive_divisor(divisor, variable, domain):
    if domain is None:
        if divisor.is_positive is not True:
            raise CapabilityGap("positive_divisor_domain_required")
        return
    bounds = quadratic_interval_range(divisor, variable, domain)["outputs"]["range"]
    if not (bounds["inf"].is_positive is True or
            (bounds["inf"] == 0 and bounds["inf_attained"] is False)):
        raise CapabilityGap("positive_divisor_required")


def inspect_separation(relation, parameter, variable, domain=None):
    """Pure admission/role inspection; this neither invokes nor records a call."""
    lhs, rhs = relation.lhs, relation.rhs
    if not lhs.has(variable) and not rhs.has(parameter):
        h, g, op = lhs, rhs, relation.rel_op
        divisor, already = sp.S.One, True
    elif not rhs.has(variable) and not lhs.has(parameter):
        h, g = rhs, lhs
        op = {"<": ">", "<=": ">=", ">": "<", ">=": "<="}[relation.rel_op]
        divisor, already = sp.S.One, True
    else:
        expression = bounded_expand(lhs - rhs)
        coefficients = polynomial(expression, parameter, maximum=48)
        powers = [power for power in range(1, int(coefficients.degree()) + 1)
                  if coefficients.nth(power) != 0] if coefficients.degree() > 0 else []
        if not powers:
            raise CapabilityGap("parameter_separation_required")
        source = polynomial(coefficients.nth(powers[-1]), variable)
        divisor = source.monic().as_expr()
        h = sp.S.Zero
        for power in powers:
            ratio = sp.cancel(coefficients.nth(power) / divisor)
            if ratio.free_symbols or ratio.is_real is not True:
                raise CapabilityGap("parameter_coefficients_not_proportional")
            h += ratio * parameter**power
        g = sp.cancel(-coefficients.nth(0) / divisor)
        if g.has(parameter) or h.has(variable):
            raise CapabilityGap("separated_symbol_roles_required")
        op = relation.rel_op
        already = False
        _positive_divisor(divisor, variable, domain)
    separated = make_relation(h, op, g)
    identity = sp.cancel(residual(separated) * divisor - residual(relation))
    return {
        "outputs": {"parameter_expression": h, "function": g, "operator": op,
         "already_separated": already, "separated_relation": separated,
         "divisor": divisor, "divisor_sign": "positive"},
        "checks": [
            {"kind": "separated_symbol_roles", "passed": not h.has(variable) and not g.has(parameter)},
            {"kind": "direction_residual" if already else "positive_scaled_residual",
             "passed": bounded_expand(identity) == 0, "divisor": divisor},
            *([] if already else [{"kind": "strict_positive_divisor", "passed": True,
                                   "divisor": divisor, "domain": domain}]),
        ],
    }


def separate_parameter(relation, parameter, variable, domain=None):
    inspected = inspect_separation(relation, parameter, variable, domain)
    return result({**inspected["outputs"], "candidate": inspected["outputs"]}, checks=inspected["checks"])


def separation_division(relation, parameter, variable, domain, prepared=None):
    # The contract supplies the inspected candidate. Recheck its certificate
    # against the current input instead of deriving the separation a second time.
    values = (inspect_separation(relation, parameter, variable, domain)["outputs"]
              if prepared is None else dict(prepared))
    h, g, divisor = (values[key] for key in ("parameter_expression", "function", "divisor"))
    separated = values["separated_relation"]
    _positive_divisor(divisor, variable, domain)
    checks = [
        {"kind": "separated_symbol_roles", "passed": (
            not h.has(variable) and not g.has(parameter)
            and separated.lhs == h and separated.rhs == g and separated.rel_op == values["operator"]
            and (separated.rel_op in ("<", ">")) == (relation.rel_op in ("<", ">"))
        )},
        {"kind": "positive_scaled_residual", "passed":
         sp.cancel(residual(separated) * divisor - residual(relation)) == 0, "divisor": divisor},
        {"kind": "strict_positive_divisor", "passed": True, "divisor": divisor, "domain": domain},
    ]
    values["transformation"] = "move_terms" if divisor == 1 else "positive_division"
    operations = ["add_both_sides"] + ([] if divisor == 1 else ["multiply_positive"])
    return result({**values, "candidate": values}, operations, checks)
