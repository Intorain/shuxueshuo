"""Certified opening-direction branches for quantified real quadratics."""

import sympy as sp

from ..discriminant_display import displayed_delta_condition
from . import CapabilityGap, LocalCheckFailed, result
from .cases import _relation_set, exact_set_equal


def quadratic_opening_solutions(relation, variable, parameter, quantifier, case_domain,
                               delta, parameter_condition, delta_solution, solution):
    """Partition the verified solution by the *displayed* leading coefficient.

    All set solving and cross-checking happens here, before presentation. An
    automatic existence branch needs only its coefficient sign; the other
    viable branch intersects that sign domain with the certified delta set.
    """
    if quantifier not in ("∀", "∃") or relation.rel_op not in ("<", "<=", ">", ">="):
        raise CapabilityGap("quantified_quadratic_required")
    condition = displayed_delta_condition(delta, relation, variable, quantifier, parameter_condition)
    expected_delta, evidence = _relation_set(condition, parameter)
    if not exact_set_equal(expected_delta, delta_solution):
        raise LocalCheckFailed("opening_branch_delta_solution")
    coefficient = sp.Poly(relation.lhs - relation.rhs, variable).nth(2)
    positive_target = relation.rel_op in (">", ">=")
    branches, excluded, domains = [], [], []
    for upward in (True, False):
        sign = (sp.Gt if upward else sp.Lt)(coefficient, 0, evaluate=False)
        sign_solution, sign_evidence = _relation_set(sign, parameter)
        domain = sp.Intersection(case_domain, sign_solution)
        domains.append(domain)
        if domain.is_empty is True:
            continue
        aligned = upward == positive_target
        automatic = quantifier == "∃" and aligned
        viable = quantifier == "∃" or aligned
        branch = {"id": "opening-up" if upward else "opening-down",
                  "direction": "向上" if upward else "向下", "upward": upward,
                  "condition": sign, "domain": domain,
                  "automatic": automatic, "delta_condition": condition,
                  "delta_solution": delta_solution, "viable": viable,
                  "solution": domain if automatic else sp.Intersection(domain, delta_solution)
                  if viable else sp.S.EmptySet,
                  "sign_evidence": sign_evidence}
        (branches if viable else excluded).append(branch)
    if (not exact_set_equal(sp.Union(*domains), case_domain)
            or not exact_set_equal(sp.Intersection(*domains), sp.S.EmptySet)):
        raise LocalCheckFailed("opening_branch_partition")
    combined = sp.Union(*(branch["solution"] for branch in branches))
    if not exact_set_equal(combined, solution):
        raise LocalCheckFailed("opening_branch_union")
    automatic = next((branch for branch in branches if branch["automatic"]), None)
    restricted = next((branch for branch in branches if not branch["automatic"]), None)
    certificate = {"relation": relation, "variable": variable, "parameter": parameter,
                   "quantifier": quantifier, "case_domain": case_domain, "delta": delta,
                   "delta_condition": condition, "delta_solution": delta_solution,
                   "branches": branches, "excluded": excluded, "solution": combined}
    operations = ["all_real_sign", "intersect_case_conditions"]
    if len(branches) > 1:
        operations.append("union_case_conditions")
    return result(
        {"branches": branches, "excluded": excluded, "automatic": automatic,
         "restricted": restricted, "automatic_up": bool(automatic and automatic["upward"]),
         "automatic_down": bool(automatic and not automatic["upward"]),
         "has_restricted": restricted is not None, "merge_required": len(branches) > 1,
         "none_viable": not branches, "solution": combined, "certificate": certificate},
        operations,
        [{"kind": "displayed_discriminant_solution", "passed": True, "evidence": evidence},
         {"kind": "opening_direction_partition", "passed": True, "domains": domains,
          "case_domain": case_domain},
         {"kind": "opening_branch_union", "passed": True,
          "branches": branches, "excluded": excluded, "solution": combined}],
    )
