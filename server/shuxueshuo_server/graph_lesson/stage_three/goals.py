"""Typed goal closure after independent feasibility verification."""

import sympy as sp

from .verification import VerificationGap, math_value


def finalize_goal(goal, feasible_set):
    """Preserve the original target kind; only range closure is registered in 1b."""
    kind = goal["kind"]
    if kind != "find_range":
        raise VerificationGap("goal_finalize.unsupported_kind:" + kind)
    if not isinstance(feasible_set, sp.Set):
        raise TypeError("goal_finalize.expected_set")
    return {"kind": kind, "status": "set", "set": math_value(feasible_set)}
