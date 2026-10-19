"""Case mathematics checks completeness, direction and branch-local results."""

import json
from copy import deepcopy

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import capabilities as cap
from shuxueshuo_server.graph_lesson.stage_three import judgments
from shuxueshuo_server.graph_lesson.stage_three.trajectory import (
    decode_value,
    encode_value,
)

x, a = sp.symbols("x a", real=True)


def cases_for(relation):
    return judgments.degenerate_branches(relation, x, a, sp.S.Reals, "∀")["cases"]


def evaluate_cases(relation):
    cases = cases_for(relation)
    records = []
    for case in cases:
        if case["kind"] == "degenerate":
            outputs = cap.degenerate_case_check(relation, x, a, case)["outputs"]
        else:
            inputs = {"relation": relation, "variable": x, "domain": sp.S.Reals,
                      "quantifier": "∀", "case_domain": case["domain"]}
            opening = cap.quadratic_sign_condition(**inputs, mode="opening")["outputs"]["opening"]
            delta = cap.quadratic_sign_condition(**inputs, mode="delta")["outputs"]["condition"]
            conditions = [opening, delta]
            solutions = [cap.solve_parameter_relation(condition, a)["outputs"]["solution"]
                         for condition in conditions]
            outputs = cap.intersect_conditions(conditions, solutions, a, case["domain"])["outputs"]
        records.append({"case_id": case["id"], "case_path": [case["id"]],
                        "condition": case["condition"], "domain": case["domain"],
                        "outputs": outputs, "source_refs": [f"/cases/{case['id']}/calls/0"]})
    return cases, records


@pytest.mark.parametrize("expression,strict,expected", [
    (a*x*x + 2*a*x - a - 2, True, sp.Interval.Lopen(-1, 0)),
    (a*x*x + 2*a*x - a - 2, False, sp.Interval(-1, 0)),
    ((a*a - 1)*x*x - (a - 1)*x - 1, True, sp.Interval.Lopen(-sp.Rational(3, 5), 1)),
    ((a*a - 1)*x*x - (a - 1)*x - 1, False, sp.Interval(-sp.Rational(3, 5), 1)),
])
@pytest.mark.parametrize("orientation", ["less", "swapped", "negated"])
def test_case_union_retains_degenerate_points_and_strictness(expression, strict, expected, orientation):
    relation = (cap.relation(expression, "<" if strict else "<=") if orientation == "less" else
                cap.relation(sp.S.Zero, ">" if strict else ">=", expression) if orientation == "swapped" else
                cap.relation(-expression, ">" if strict else ">="))
    cases, records = evaluate_cases(relation)
    output = cap.merge_cases(cases, records)
    assert output["outputs"]["solution"] == expected
    assert output["operations"] == ["union_disjoint_cases"]
    assert all(check["passed"] is True for check in output["checks"])
    assert decode_value(json.loads(json.dumps(encode_value(output)))) == output


def test_q03_degenerate_cases_have_independent_substitution_and_outcomes():
    relation = cap.relation((a*a - 1)*x*x - (a - 1)*x - 1, "<")
    cases, records = evaluate_cases(relation)
    assert [case["value"] for case in cases[:2]] == [-1, 1]
    rejected, kept = [record["outputs"] for record in records[:2]]
    assert rejected["holds"] is False
    assert rejected["solution"] == sp.S.EmptySet
    assert rejected["substituted_relation"] == cap.relation(2*x - 1, "<")
    assert rejected["linear_coefficient"] == -2
    assert kept["holds"] is True
    assert kept["solution"] == sp.FiniteSet(1)
    assert kept["substituted_relation"] == cap.relation(sp.Integer(-1), "<")
    assert kept["linear_coefficient"] == 0
    assert cap.merge_cases(cases, records)["outputs"]["solution"] != sp.Intersection(
        *(record["outputs"]["solution"] for record in records))


@pytest.mark.parametrize("operator,expected", [(">", sp.S.EmptySet), (">=", sp.FiniteSet(0)),
                                              ("<", sp.S.EmptySet), ("<=", sp.FiniteSet(0))])
def test_zero_constant_degenerate_case_respects_strict_relation(operator, expected):
    relation = cap.relation(a*x*x, operator)
    case = cases_for(relation)[0]
    assert cap.degenerate_case_check(relation, x, a, case)["outputs"]["solution"] == expected


def test_normalization_negative_multiplier_preserves_residual_opening_and_delta():
    original = cap.relation(-x*x + a, ">=")
    normalized = cap.normalize_to_zero(original, x)["outputs"]["relation"]
    assert normalized.rel_op == "<="
    inputs = {"relation": normalized, "variable": x, "domain": sp.S.Reals,
              "quantifier": "∀", "case_domain": sp.S.Reals}
    opening = cap.quadratic_sign_condition(**inputs, mode="opening")["outputs"]
    assert opening["coefficient"] == -1
    assert opening["basis_expression"] == -x*x + a
    assert opening["opening"] == cap.relation(sp.Integer(-1), ">")
    assert cap.solve_parameter_relation(opening["opening"], a)["outputs"]["solution"] == sp.S.EmptySet
    cases, records = evaluate_cases(original)
    assert cap.merge_cases(cases, records)["outputs"]["solution"] == sp.S.EmptySet


def test_nonzero_premise_cannot_be_omitted_for_parameter_coefficient():
    relation = cap.relation(a*x*x + 1, ">=")
    with pytest.raises(cap.CapabilityGap, match="nondegenerate_case_required"):
        cap.quadratic_sign_condition(relation, x, sp.S.Reals, "∀", sp.S.Reals, "opening")


@pytest.mark.parametrize("omitted", [0, 1, 2])
def test_merge_rejects_missing_case_even_when_manifest_is_also_truncated(omitted):
    cases, records = evaluate_cases(cap.relation((a*a - 1)*x*x - (a - 1)*x - 1, "<"))
    cases.pop(omitted)
    records.pop(omitted)
    with pytest.raises(cap.LocalCheckFailed, match="incomplete_case_partition"):
        cap.merge_cases(cases, records)


@pytest.mark.parametrize("mutation", ["missing_result", "reordered_result", "wrong_condition", "wrong_domain",
                                     "outside_solution", "missing_source", "missing_case_path", "overlap"])
def test_merge_rejects_invalid_or_untraceable_branch_result(mutation):
    cases, records = evaluate_cases(cap.relation((a*a - 1)*x*x - (a - 1)*x - 1, "<"))
    if mutation == "missing_result":
        records.pop()
    elif mutation == "reordered_result":
        records.reverse()
    elif mutation == "wrong_condition":
        records[0]["condition"] = cases[1]["condition"]
    elif mutation == "wrong_domain":
        cases[0]["domain"] = sp.S.Reals
    elif mutation == "outside_solution":
        records[-1]["outputs"]["solution"] = sp.Interval(-1, 1)
    elif mutation == "missing_source":
        records[0]["source_refs"] = []
    elif mutation == "missing_case_path":
        records[0]["case_path"] = []
    else:
        duplicate = deepcopy(cases[0])
        duplicate["id"] = "duplicate"
        cases.append(duplicate)
        duplicate_record = deepcopy(records[0])
        duplicate_record["case_id"] = "duplicate"
        records.append(duplicate_record)
    with pytest.raises(cap.LocalCheckFailed):
        cap.merge_cases(cases, records)


def test_intersection_rechecks_each_condition_set_instead_of_trusting_branch_output():
    conditions = [cap.relation(1-a*a, ">"), cap.relation(5*a*a-2*a-3, "<")]
    true_solutions = [sp.Interval.open(-1, 1), sp.Interval.open(-sp.Rational(3, 5), 1)]
    actual = cap.intersect_conditions(conditions, true_solutions, a, sp.S.Reals)
    assert actual["outputs"]["solution"] == sp.Interval.open(-sp.Rational(3, 5), 1)
    wrong = [sp.Union(*true_solutions), sp.Union(*true_solutions)]
    with pytest.raises(cap.LocalCheckFailed, match="incorrect_condition_solution"):
        cap.intersect_conditions(conditions, wrong, a, sp.S.Reals)
    with pytest.raises(cap.LocalCheckFailed, match="incomplete_condition_solutions"):
        cap.intersect_conditions(conditions, true_solutions[:1], a, sp.S.Reals)


@pytest.mark.parametrize("expression,operator,expected", [
    ((a-1)**2*(a+1)**2, ">=", sp.S.Reals),
    ((a-1)**2*(a+1)**2, ">", sp.Complement(sp.S.Reals, sp.FiniteSet(-1, 1))),
    (a**4-1, "<=", sp.Interval(-1, 1)),
    (sp.S.Zero, ">=", sp.S.Reals),
    (sp.S.Zero, ">", sp.S.EmptySet),
])
def test_general_polynomial_solver_has_exact_repeated_root_endpoints(expression, operator, expected):
    relation = cap.relation(expression, operator)
    result = cap.solve_parameter_relation(relation, a)
    assert result["outputs"]["solution"] == expected
    assert all(check["passed"] is True for check in result["checks"])


def test_radical_degenerate_points_survive_partition_and_checkpoint():
    relation = cap.relation((a*a - 2)*x*x - 1, "<")
    cases, records = evaluate_cases(relation)
    merged = cap.merge_cases(cases, records)
    assert merged["outputs"]["solution"] == sp.Interval(-sp.sqrt(2), sp.sqrt(2))
    assert decode_value(json.loads(json.dumps(encode_value(cases)))) == cases


def test_unknown_parameter_class_is_gap_and_not_a_boolean_decision():
    with pytest.raises(cap.CapabilityGap, match="rational_parameter_polynomial_required"):
        cases_for(cap.relation(sp.sin(a)*x*x + 1, ">="))
    with pytest.raises(cap.CapabilityGap, match="checkpoint"):
        cap.solve_parameter_relation(cap.relation(a**3-a-1, ">="), a)


def test_repeated_zero_coefficient_root_creates_one_degenerate_case():
    cases, records = evaluate_cases(cap.relation((a-1)**2*x*x + 1, ">="))
    assert len(cases) == 2
    assert cases[0]["domain"] == sp.FiniteSet(1)
    assert cap.merge_cases(cases, records)["outputs"]["solution"] == sp.S.Reals


def test_single_nondegenerate_case_can_keep_the_existing_empty_case_path():
    cases, records = evaluate_cases(cap.relation(x*x+a, ">="))
    records[0]["case_path"] = []
    assert cap.merge_cases(cases, records)["outputs"]["solution"] == sp.Interval(0, sp.oo)


def test_undecidable_set_equality_is_a_gap_not_an_incorrect_math_result():
    from shuxueshuo_server.graph_lesson.stage_three.capabilities.cases import (
        exact_set_equal,
    )

    unknown = sp.ConditionSet(a, sp.Eq(sp.sin(a), a), sp.S.Reals)
    with pytest.raises(cap.CapabilityGap, match="set_equality_unknown"):
        exact_set_equal(unknown, sp.S.EmptySet)


@pytest.mark.parametrize("expression,expected", [(a*a-1, "quadratic"), (a**4-1, "polynomial")])
def test_parameter_solver_choice_comes_from_degree(expression, expected):
    assert judgments.parameter_solver(cap.relation(expression, ">="), a)["selected"] == expected
