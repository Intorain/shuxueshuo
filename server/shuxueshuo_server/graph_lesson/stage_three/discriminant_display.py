"""Keep the displayed discriminant polynomial tied to frozen solver evidence."""

import sympy as sp


def constant_true_condition(condition):
    """A numeric fact need not be presented as a parameter restriction."""
    return (isinstance(condition, sp.Rel) and not condition.free_symbols
            and sp.simplify(condition) is sp.true)


def displayed_delta_condition(delta, relation, variable, quantifier, normalized):
    """Recover the original delta condition, checking its normalized equivalent.

    The parameter solver divides by a positive scale and orients its residual
    towards zero. The lesson keeps the computed discriminant and its sign;
    this check needs only a polynomial identity, never another inequality solve.
    """
    if (not isinstance(relation, sp.Rel) or relation.rel_op not in ("<", "<=", ">", ">=")
            or not isinstance(normalized, sp.Rel) or normalized.rel_op not in ("<", "<=", ">", ">=")
            or not isinstance(variable, sp.Symbol) or quantifier not in ("∀", "∃")):
        raise ValueError("discriminant_display.invalid_evidence")
    polynomial = sp.Poly(relation.lhs - relation.rhs, variable)
    if polynomial.degree() != 2:
        raise ValueError("discriminant_display.not_quadratic")
    a, b, c = polynomial.all_coeffs()
    if sp.expand(delta - (b*b - 4*a*c)) != 0:
        raise ValueError("discriminant_display.delta_mismatch")
    strict = relation.rel_op in ("<", ">")
    operator = ("<" if strict else "<=") if quantifier == "∀" else (">" if strict else ">=")
    displayed = sp.Rel(delta, 0, operator, evaluate=False)
    if strict != (normalized.rel_op in ("<", ">")):
        raise ValueError("discriminant_display.strictness_mismatch")
    raw = -delta if quantifier == "∀" else delta
    internal = normalized.lhs - normalized.rhs
    if normalized.rel_op in ("<", "<="):
        internal = -internal
    if raw == 0 and internal == 0:
        return displayed
    if internal == 0:
        raise ValueError("discriminant_display.condition_mismatch")
    scale = sp.cancel(raw / internal)
    if scale.free_symbols or scale.is_positive is not True or sp.expand(raw - scale*internal) != 0:
        raise ValueError("discriminant_display.condition_mismatch")
    return displayed
