"""One inert mathematical-value representation for cards, traces and evidence."""

from copy import deepcopy

import sympy as sp


def math_value(value):
    """Return source text and LaTeX; neither string is an executable expression."""
    if not isinstance(value, sp.Basic):
        raise TypeError("math_value.math_object_required")
    return {"expression": sp.sstr(value), "latex": sp.latex(value)}


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
