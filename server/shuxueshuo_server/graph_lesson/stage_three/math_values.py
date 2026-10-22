"""One inert mathematical-value representation for cards, traces and evidence."""

from copy import deepcopy

import sympy as sp
from sympy.printing.latex import LatexPrinter

# A policy card precedes range computation: attainment is not known yet.
# Reserve min/max for a certified attained value (or an explicit claim that it exists).
BOUND_NAMES = {"inf": "值域下端", "sup": "值域上端"}
EXTREMUM_NAMES = {"inf": "最小值", "sup": "最大值"}
BOUND_TEX = {"inf": r"\text{下端}", "sup": r"\text{上端}"}
EXTREMUM_TEX = {"inf": r"\min", "sup": r"\max"}
BOUND_EXPLANATION = (
    "这里“下端/上端”指函数值范围的两端：能取到时就是最小值/最大值；"
    "取不到时，是函数值向下/向上无限接近的值；向下/向上无界时记为 $-\\infty/+\\infty$。"
)


class _DescendingPrinter(LatexPrinter):
    def __init__(self, variable):
        super().__init__()
        self._variable = variable

    def _as_ordered_terms(self, expr, order=None):
        terms = super()._as_ordered_terms(expr, order=order)
        if self._variable is None or not expr.is_polynomial(self._variable):
            return terms
        return sorted(terms, key=lambda term: -sp.degree(term, self._variable))

    def _print_Relational(self, expr):
        """A constant compared with an expression reads expression first: ``a \\geq 1``, ``1 \\geq 0``."""
        if expr.rel_op in ("<", "<=", ">", ">=") and not expr.lhs.free_symbols and (
                expr.rhs.free_symbols or (expr.lhs == 0 and expr.rhs != 0)):
            expr = expr.reversed
        return super()._print_Relational(expr)

    def _print_And(self, expr):
        """``lo < a < hi`` rather than ``lo < a \\wedge a < hi`` for a two-sided bound."""
        bounds = _two_sided(expr)
        if bounds is None:
            return super()._print_And(expr)
        (low, low_op), symbol, (high, high_op) = bounds
        return f"{self._print(low)} {low_op} {self._print(symbol)} {high_op} {self._print(high)}"


_STRICT_TEX = {True: "<", False: r"\leq"}


def _two_sided(expr):
    """``(lower, op), symbol, (upper, op)`` when ``expr`` bounds one symbol from both sides."""
    if len(expr.args) != 2 or not all(isinstance(arg, sp.core.relational.Relational) for arg in expr.args):
        return None
    lower = upper = None
    symbol = None
    for relation in expr.args:
        if relation.rel_op not in ("<", "<=", ">", ">="):
            return None
        small, large = (relation.lhs, relation.rhs) if relation.rel_op in ("<", "<=") else (relation.rhs, relation.lhs)
        strict = relation.rel_op in ("<", ">")
        if isinstance(large, sp.Symbol) and not small.free_symbols:
            if symbol not in (None, large) or lower is not None:
                return None
            symbol, lower = large, (small, _STRICT_TEX[strict])
        elif isinstance(small, sp.Symbol) and not large.free_symbols:
            if symbol not in (None, small) or upper is not None:
                return None
            symbol, upper = small, (large, _STRICT_TEX[strict])
        else:
            return None
    return (lower, symbol, upper) if lower and upper else None


def latex(value):
    """Polynomials in x read from the highest power down; parameters never lead."""
    variable = next((s for s in getattr(value, "free_symbols", ()) if s.name == "x"), None)
    return _DescendingPrinter(variable).doprint(value)


def math_value(value):
    """Return source text and LaTeX; neither string is an executable expression."""
    if not isinstance(value, sp.Basic):
        raise TypeError("math_value.math_object_required")
    return {"expression": sp.sstr(value), "latex": latex(value)}


def adapt_legacy_math_values(value):
    """Read-only adapter for saved pre-LaTeX records, never a writer fallback.

    Only the old mathematical-value shape is adapted. In particular, D1/D2
    decision.display is a presentation template and must remain untouched.
    Saved card identities and hashes are retained; persisted bytes are not edited.
    """
    if isinstance(value, list):
        return [adapt_legacy_math_values(item) for item in value]
    if not isinstance(value, dict):
        return value
    if (set(value) <= {"expression", "display", "exact"}
            and isinstance(value.get("expression"), str) and isinstance(value.get("display"), str)):
        return {("latex" if key == "display" else key): adapt_legacy_math_values(item)
                for key, item in value.items()}
    return {key: deepcopy(item) if key == "decision" else adapt_legacy_math_values(item)
            for key, item in value.items()}
