"""Exact parameter partitions and checked unions, independent of verification."""

from itertools import combinations, pairwise

import sympy as sp

from ....problem_understanding.notation_semantics import bounded_expand
from . import CapabilityGap, LocalCheckFailed, polynomial, residual, result


def parameter_symbols(expression, variable):
    symbols = expression.free_symbols - {variable}
    if len(symbols) > 1:
        raise CapabilityGap("single_parameter_required")
    return symbols


def exact_set_equal(left, right):
    """Only a proved empty symmetric difference establishes equality."""
    if not isinstance(left, sp.Set) or not isinstance(right, sp.Set):
        return False
    difference = sp.SymmetricDifference(left, right)
    if difference == sp.S.EmptySet or difference.is_empty is True:
        return True
    if difference.is_empty is False:
        return False
    raise CapabilityGap("set_equality_unknown")


def _rational_poly(expression, variable):
    if variable is None:
        if expression.free_symbols or expression.is_Rational is not True:
            raise CapabilityGap("rational_parameter_coefficients_required")
        return None
    try:
        value = sp.Poly(expression, variable, domain=sp.QQ)
    except (sp.PolynomialError, sp.polys.polyerrors.CoercionFailed) as exc:
        raise CapabilityGap("rational_parameter_polynomial_required") from exc
    if value.degree() > 48:
        raise CapabilityGap("parameter_polynomial_degree")
    return value


def _real_roots(poly):
    """Root isolation supplies completeness; substitution checks each value."""
    roots = list(dict.fromkeys(sp.polys.polytools.real_roots(poly)))
    if any(root.has(sp.CRootOf) for root in roots):
        # Current checkpoint values encode radicals, not isolated root objects.
        raise CapabilityGap("parameter_root_checkpoint_unavailable")
    if poly.count_roots(-sp.oo, sp.oo) != len(roots):
        raise LocalCheckFailed("parameter_root_count")
    for root in roots:
        value = bounded_expand(poly.eval(root))
        if root.is_real is not True or value.is_zero is not True:
            raise CapabilityGap("parameter_root_substitution_unknown")
    if any((right - left).is_positive is not True for left, right in pairwise(roots)):
        raise CapabilityGap("parameter_root_order_unknown")
    return roots


def coefficient_zeros(coefficient, parameter):
    poly = _rational_poly(coefficient, parameter)
    if coefficient == 0:
        return sp.S.Reals
    if poly is None or poly.degree() == 0:
        return sp.S.EmptySet
    return sp.FiniteSet(*_real_roots(poly))


def partition_cases(relation, variable, parameter, domain, quantifier):
    if relation.rel_op not in (">", ">=", "<", "<="):
        raise CapabilityGap("ordered_relation_required")
    if domain != sp.S.Reals or quantifier not in ("∀", "∃"):
        raise CapabilityGap("all_real_quantified_quadratic_required")
    expression = residual(relation)
    poly = polynomial(expression, variable)
    if poly.degree() != 2 or expression.free_symbols - {variable, parameter}:
        raise CapabilityGap("single_parameter_quadratic_required")
    coefficient = poly.nth(2)
    zeros = coefficient_zeros(coefficient, parameter)
    cases = [
        {"id": f"degenerate-{index}", "kind": "degenerate",
         "condition": sp.Eq(parameter, value, evaluate=False),
         "domain": sp.FiniteSet(value), "value": value}
        for index, value in enumerate(zeros)
    ]
    cases.append({
        "id": "nondegenerate", "kind": "nondegenerate",
        "condition": sp.Ne(coefficient, 0, evaluate=False),
        "domain": sp.Complement(sp.S.Reals, zeros), "value": None,
    })
    return coefficient, zeros, cases


def _relation_set(relation, variable):
    if relation is sp.true:
        return sp.S.Reals, [{"kind": "constant_condition", "passed": True}]
    if relation is sp.false:
        return sp.S.EmptySet, [{"kind": "constant_condition", "passed": True}]
    if relation.rel_op in ("==", "!="):
        if relation.lhs == variable and not relation.rhs.free_symbols and relation.rhs.is_real is True:
            zeros = sp.FiniteSet(relation.rhs)
        elif relation.rhs == variable and not relation.lhs.free_symbols and relation.lhs.is_real is True:
            zeros = sp.FiniteSet(relation.lhs)
        else:
            value = bounded_expand(relation.lhs - relation.rhs)
            zeros = coefficient_zeros(value, variable)
        return (zeros if relation.rel_op == "==" else sp.Complement(sp.S.Reals, zeros)), [
            {"kind": "parameter_zero_set", "passed": True, "zero_set": zeros}
        ]
    if relation.rel_op not in (">", ">=", "<", "<="):
        raise CapabilityGap("ordered_relation_required")
    expression = residual(relation)
    poly = _rational_poly(expression, variable)
    strict = relation.rel_op in (">", "<")
    if expression == 0:
        return (sp.S.EmptySet if strict else sp.S.Reals), [
            {"kind": "identically_zero_relation", "passed": True, "strict": strict}
        ]
    roots = _real_roots(poly) if poly.degree() > 0 else []
    checks = [{"kind": "complete_real_roots", "passed": True, "count": len(roots)}]
    parts = []
    for left, right in pairwise([-sp.oo, *roots, sp.oo]):
        sample = (right - 1 if left == -sp.oo and right != sp.oo else
                  left + 1 if right == sp.oo and left != -sp.oo else
                  sp.S.Zero if left == -sp.oo else (left + right) / 2)
        value = bounded_expand(expression.subs(variable, sample))
        if value.is_positive is None:
            raise CapabilityGap("parameter_partition_sign_unknown")
        checks.append({"kind": "parameter_root_partition", "passed": True,
                       "sample": sample, "value": value})
        if value.is_positive is True:
            parts.append(sp.Interval.open(left, right))
    if not strict:
        parts.extend(sp.FiniteSet(root) for root in roots)
    return sp.Union(*parts), checks


def solve_parameter_relation(relation, variable):
    solution, checks = _relation_set(relation, variable)
    return result({"solution": solution}, ["parameter_polynomial_signs"], checks)


def degenerate_case_check(relation, variable, parameter, case, quantifier):
    if quantifier not in ("∀", "∃"):
        raise CapabilityGap("unsupported_quantifier")
    if case["kind"] != "degenerate" or case["value"] is None:
        raise LocalCheckFailed("degenerate_case_required")
    value = case["value"]
    expected_condition = sp.Eq(parameter, value, evaluate=False)
    if (case["condition"] != expected_condition or
            not exact_set_equal(case["domain"], sp.FiniteSet(value))):
        raise LocalCheckFailed("invalid_degenerate_case_domain")
    substituted = relation.func(
        relation.lhs.subs(parameter, value), relation.rhs.subs(parameter, value),
        evaluate=False,
    )
    expression = residual(substituted)
    poly = polynomial(expression, variable)
    if poly.degree() > 1 or expression.free_symbols - {variable}:
        raise LocalCheckFailed("case_does_not_remove_quadratic_term")
    slope, constant = poly.nth(1), poly.nth(0)
    if slope.is_zero is False:
        # A nonconstant affine residual takes every real value on R.
        holds = quantifier == "∃"
        reason = "nonconstant_affine_full_real_range"
    elif slope.is_zero is True:
        truth = constant.is_positive if relation.rel_op in (">", "<") else constant.is_nonnegative
        if truth not in (True, False):
            raise CapabilityGap("degenerate_constant_sign_unknown")
        holds = truth
        reason = "constant_sign"
    else:
        raise CapabilityGap("degenerate_linear_coefficient_unknown")
    solution = case["domain"] if holds else sp.S.EmptySet
    return result(
        {"substituted_relation": substituted, "holds": holds, "solution": solution,
         "linear_coefficient": slope, "constant": constant},
        ["degenerate_linear_or_constant"],
        [{"kind": "case_substitution", "passed": True, "parameter": parameter,
          "value": value, "condition": case["condition"], "residual": expression},
         {"kind": "whole_real_affine_sign", "passed": True, "reason": reason,
          "slope": slope, "constant": constant, "holds": holds, "quantifier": quantifier}],
    )


def _combine_conditions(conditions, solutions, variable, case_domain, combiner):
    if not conditions or len(conditions) != len(solutions):
        raise LocalCheckFailed("incomplete_condition_solutions")
    checks = []
    for condition, solution in zip(conditions, solutions, strict=True):
        expected, evidence = _relation_set(condition, variable)
        if not exact_set_equal(solution, expected):
            raise LocalCheckFailed("incorrect_condition_solution")
        checks.append({"kind": "condition_solution", "passed": True,
                       "condition": condition, "solution": solution, "evidence": evidence})
    combined = sp.Intersection(*solutions) if combiner == "all" else sp.Union(*solutions)
    solution = sp.Intersection(case_domain, combined)
    checks.append({"kind": "same_case_intersection" if combiner == "all" else "same_case_condition_union",
                   "passed": True, "case_domain": case_domain, "condition_sets": solutions,
                   "combiner": combiner, "combined": combined})
    return result({"solution": solution},
                  ["intersect_case_conditions" if combiner == "all" else "union_case_conditions"], checks)


def combine_condition_solutions(conditions, solutions, variable, case_domain, combiner, quantifier):
    """Combine quantified sign alternatives, then restrict to this degree case."""
    if quantifier not in ("∀", "∃"):
        raise CapabilityGap("unsupported_quantifier")
    expected_combiner = "all" if quantifier == "∀" else "any"
    if combiner != expected_combiner:
        raise LocalCheckFailed("quantifier_condition_combiner_mismatch")
    combined = _combine_conditions(conditions, solutions, variable, case_domain, combiner)
    return result(combined["outputs"], combined["operations"], [
        *combined["checks"],
        {"kind": "quantifier_condition_combiner", "passed": True,
         "quantifier": quantifier, "combiner": combiner},
    ])


def merge_cases(cases, results):
    if not cases or len(cases) != len(results):
        raise LocalCheckFailed("incomplete_case_results")
    identifiers = [case["id"] for case in cases]
    result_ids = [record["case_id"] for record in results]
    if len(set(identifiers)) != len(cases) or result_ids != identifiers:
        raise LocalCheckFailed("case_result_identity")
    symbols = set().union(*(case["condition"].free_symbols for case in cases))
    if len(symbols) > 1:
        raise CapabilityGap("single_parameter_cases_required")
    # A constant coefficient produces one whole-real nondegenerate case.
    parameter = next(iter(symbols), sp.Symbol("_case_parameter", real=True))
    domains = []
    for case in cases:
        expected, _ = _relation_set(case["condition"], parameter)
        if not exact_set_equal(case["domain"], expected):
            raise LocalCheckFailed("case_condition_domain_mismatch")
        domains.append(case["domain"])
    if not exact_set_equal(sp.Union(*domains), sp.S.Reals):
        raise LocalCheckFailed("incomplete_case_partition")
    if any(not exact_set_equal(sp.Intersection(left, right), sp.S.EmptySet)
           for left, right in combinations(domains, 2)):
        raise LocalCheckFailed("overlapping_case_partition")
    solutions, checks = [], [{"kind": "complete_disjoint_cases", "passed": True,
                              "case_ids": identifiers, "domains": domains}]
    for case, record in zip(cases, results, strict=True):
        path = record.get("case_path")
        valid_path = (isinstance(path, list) and
                      ((path and path[-1] == case["id"]) or
                       (not path and len(cases) == 1 and case["kind"] == "nondegenerate"
                        and exact_set_equal(case["domain"], sp.S.Reals))))
        if (record["condition"] != case["condition"] or
                not exact_set_equal(record["domain"], case["domain"]) or
                not valid_path or not record.get("source_refs")):
            raise LocalCheckFailed("case_result_provenance")
        solution = record["outputs"]["solution"]
        if not exact_set_equal(sp.Complement(solution, case["domain"]), sp.S.EmptySet):
            raise LocalCheckFailed("case_solution_outside_domain")
        solutions.append(solution)
        checks.append({"kind": "case_result", "passed": True, "case_id": case["id"],
                       "condition": case["condition"], "domain": case["domain"],
                       "solution": solution, "source_refs": record["source_refs"]})
    return result({"solution": sp.Union(*solutions), "case_solutions": solutions},
                  ["union_disjoint_cases"], checks)
