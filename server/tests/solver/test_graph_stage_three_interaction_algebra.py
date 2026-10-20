"""Regression evidence for algebra questions, independent of later cards."""

from copy import deepcopy

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import interaction, interaction_algebra
from tests.solver.test_graph_stage_three_interactions import _known, _seed

x, a = sp.symbols("x a", real=True)


@pytest.fixture
def sources():
    return interaction_algebra.register(interaction.EXTENSION_API)["answers"]


def facts(source, values, context, known=sp.S.Reals):
    result = source["facts"](values, context)
    result["known"] = known
    return result


def candidates(source, data, item):
    return [candidate for generator in source["generators"].values() for candidate in generator(data, item)]


CONTEXT = {"x": x, "parameter": a, "domain": sp.S.Reals, "quantifier": "∀",
           "relation": sp.Ge(x**2+a, 0, evaluate=False), "expression": x**2+a}


def test_normalize_keeps_only_witnessed_direction_and_constant_mistakes(sources):
    source = sources["equivalent_relation"]
    original = sp.Le(-x**2 + 2*x + 3, a**2 - 3*a, evaluate=False)
    correct = sp.Ge(x**2 - 2*x + a**2 - 3*a - 3, 0, evaluate=False)
    values = {"before": [original], "after": [correct]}
    data = facts(source, values, CONTEXT)
    item, = source["answer"](data)
    equivalent = interaction.Candidate("equivalent", "same", sp.Le(0, correct.lhs, evaluate=False))
    kept, records, also_correct = source["validate"](data, values, CONTEXT, item,
                                                     [equivalent, *candidates(source, data, item)])
    assert len(kept) >= 2 and not also_correct
    assert records[0] == (equivalent, "unproven", None)
    for candidate, result, witness in records[1:]:
        if result == "witness":
            substitutions = {sp.Symbol(name, real=True): sp.sympify(value)
                             for name, value in (pair.split("=") for pair in witness.split(","))}
            assert candidate.value.subs(substitutions) != correct.subs(substitutions)


def test_relation_witness_respects_known_parameter_and_current_case(sources):
    source = sources["discriminant_condition"]
    relation = sp.Le(-a**2, 0, evaluate=False)
    values = {"before": [relation], "after": [sp.Ge(a**2, 0, evaluate=False)],
              "case": {"domain": sp.Interval(1, 3)}}
    data = facts(source, values, CONTEXT, known=sp.Interval(-2, 2))
    item, = source["answer"](data)
    strict = interaction.Candidate("strict", "strict", sp.Lt(-a**2, 0, evaluate=False))
    kept, records, _ = source["validate"](data, values, CONTEXT, item, [strict])
    assert not kept and records == [(strict, "unproven", None)]


def test_undefined_relation_sample_is_unknown_not_a_false_witness(sources):
    source = sources["discriminant_condition"]
    relation = sp.Ge(1/a, 0, evaluate=False)
    values = {"before": [relation], "after": [relation]}
    data = facts(source, values, CONTEXT)
    item, = source["answer"](data)
    strict = interaction.Candidate("strict", "strict", sp.Gt(1/a, 0, evaluate=False))
    kept, records, _ = source["validate"](data, values, CONTEXT, item, [strict])
    assert not kept and records == [(strict, "unproven", None)]


@pytest.mark.parametrize("reversed_relation", [False, True])
def test_discriminant_does_not_use_a_counterexample_outside_prior_opening(sources, reversed_relation):
    source = sources["discriminant_condition"]
    polynomial = a*x**2 + (a+1)**2
    relation = sp.Le(-polynomial, 0, evaluate=False) if reversed_relation else sp.Ge(polynomial, 0, evaluate=False)
    context = {**CONTEXT, "relation": relation, "expression": polynomial}
    delta = -4*a*(a+1)**2
    values = {"before": [sp.Le(delta, 0, evaluate=False)], "after": [sp.Ge(-delta, 0, evaluate=False)],
              "case": {"domain": sp.Complement(sp.S.Reals, sp.FiniteSet(0)), "condition": sp.Ne(a, 0)}}
    data = facts(source, values, context)
    item, = source["answer"](data)
    strict = interaction.Candidate("strict", "strict", sp.Lt(delta, 0, evaluate=False))
    kept, records, _ = source["validate"](data, values, context, item, [strict])
    assert kept == [] and records == [(strict, "unproven", None)]


def test_algebra_solution_comparison_also_respects_prior_opening(sources):
    source = sources["algebra_solution"]
    polynomial = a*x**2 + (a+1)**2
    context = {**CONTEXT, "relation": sp.Ge(polynomial, 0, evaluate=False), "expression": polynomial}
    answer = sp.Interval.open(0, sp.oo)
    values = {"before": [sp.Ge(a*(a+1)**2, 0, evaluate=False)], "after": [answer],
              "case": {"domain": sp.Complement(sp.S.Reals, sp.FiniteSet(0)), "condition": sp.Ne(a, 0)}}
    data = facts(source, values, context)
    item, = source["answer"](data)
    same_on_opening = interaction._set_candidate("same", sp.Union(answer, sp.FiniteSet(-1)))
    wrong = interaction._set_candidate("wrong", sp.Interval(1, sp.oo))
    kept, records, _ = source["validate"](data, values, context, item, [same_on_opening, wrong])
    assert kept == [wrong]
    assert records[0] == (same_on_opening, "unproven", None)
    assert records[1][2] == interaction._latex(sp.Rational(1, 2))


def test_missing_or_inconsistent_opening_evidence_is_readonly(sources):
    source = sources["discriminant_condition"]
    values = {"before": [sp.Le(-4*a, 0, evaluate=False)], "after": [sp.Ge(a, 0, evaluate=False)]}
    missing = {key: value for key, value in CONTEXT.items() if key != "expression"}
    with pytest.raises(interaction.NotInteractive, match="opening_evidence_missing"):
        source["facts"](values, missing)
    with pytest.raises(interaction.NotInteractive, match="opening_evidence_unverified"):
        source["facts"](values, {**CONTEXT, "expression": -x**2-a})


def test_degree_basis_is_coefficient_zero_not_merely_positive_or_negative(sources):
    source = sources["zero_coefficient"]
    values = {"coefficient": a**2 - 1, "parameter": a}
    data = facts(source, values, CONTEXT)
    item, = source["answer"](data)
    assert item["answer"].value == sp.Eq(a**2 - 1, 0, evaluate=False)
    kept, records, _ = source["validate"](data, values, CONTEXT, item, candidates(source, data, item))
    assert len(kept) == 3 and all(row[1] == "witness" for row in records)


@pytest.mark.parametrize("strict,allowed", [(False, {0, 1}), (True, {1})])
def test_opening_multi_uses_exact_vertex_values_and_matching_graphs(sources, strict, allowed):
    source = sources["opening_positions"]
    relation = (sp.Gt if strict else sp.Ge)(x**2+a, 0, evaluate=False)
    values = {"strict": strict, "expression": x**2+a, "positive_relation": relation}
    data = facts(source, values, CONTEXT)
    item, = source["answer"](data)
    kept, records, additional = source["validate"](data, values, CONTEXT, item, candidates(source, data, item))
    correct = [item["answer"], *additional]
    assert {int(candidate.value) for candidate in correct} == allowed
    assert all(row[1] in ("witness", "also_correct") for row in records)
    builder = interaction_algebra.register(interaction.EXTENSION_API)["option_graphs"]["opening_positions"][1]
    images, note = builder(data, values, CONTEXT,
                           [(candidate, True) for candidate in correct] + [(candidate, False) for candidate in kept])
    assert len(images) == 3 and "相对位置" in note
    for image in images:
        interaction.graph_contract.validate_graph(image)
        assert image["params"]["coefficient"] == 1
    with pytest.raises(interaction.GraphUnavailable, match="representative_unverified"):
        builder(data, values, CONTEXT, [(item["answer"], False)])


def test_opening_rejects_finite_domain_and_existential_question(sources):
    source = sources["opening_positions"]
    values = {"strict": False, "expression": x**2+a, "positive_relation": sp.Ge(x**2+a, 0)}
    for context in ({**CONTEXT, "domain": sp.Interval(0, 1)}, {**CONTEXT, "quantifier": "∃"}):
        with pytest.raises(interaction.NotInteractive, match="opening_domain_unsupported"):
            source["facts"](values, context)


@pytest.mark.parametrize("holds", [False, True])
def test_degenerate_checklist_uses_boolean_certificate(sources, holds):
    source = sources["degenerate_decision"]
    values = {"holds": holds, "value": -1, "parameter": a, "after": [sp.Ge(2*x, 0, evaluate=False)]}
    data = facts(source, values, CONTEXT)
    item, = source["answer"](data)
    wrong, = source["generators"]["flip_degenerate"](data, item)
    assert item["answer"].value is holds and wrong.value is not holds


@pytest.mark.parametrize("function,vertex,bound", [(-x**2+2*x+3, 1, 4), (2*x**2, 0, 0),
                                                 (x**2-2*sp.sqrt(2)*x+3, sp.sqrt(2), 1)])
def test_square_answer_is_checked_against_function_and_equivalent_values(sources, function, vertex, bound):
    source = sources["square_extremum"]
    leading = sp.Poly(function, x).nth(2)
    values = {"x": x, "function": function, "vertex": sp.sympify(vertex), "extremum": sp.sympify(bound),
              "square": leading*(x-vertex)**2+bound}
    data = facts(source, values, CONTEXT)
    item, = source["answer"](data)
    equivalent = interaction.Candidate("algebraically_equal", "same", (sp.sympify(vertex), sp.sympify(bound)))
    kept, records, _ = source["validate"](data, values, CONTEXT, item,
                                        [equivalent, *candidates(source, data, item)])
    assert records[0] == (equivalent, "duplicate", None)
    assert len(kept) >= 2
    broken = {**values, "extremum": values["extremum"]+1}
    with pytest.raises(interaction.NotInteractive, match="square_evidence_unverified"):
        source["facts"](broken, CONTEXT)


def test_set_answers_drop_equivalence_under_known_and_case_conditions(sources):
    source = sources["algebra_solution"]
    answer = sp.Interval(4, sp.oo)
    values = {"before": [sp.Ge(a, 4)], "after": [answer],
              "case": {"domain": sp.Interval(0, sp.oo), "condition": sp.Ge(a, 0)}}
    data = facts(source, values, CONTEXT)
    item, = source["answer"](data)
    equivalent = interaction._set_candidate("equivalent", sp.Union(sp.Interval(-sp.oo, -1), answer))
    kept, records, _ = source["validate"](data, values, CONTEXT, item,
                                        [equivalent, *candidates(source, data, item)])
    assert records[0] == (equivalent, "unproven", None)
    assert all(candidate is not equivalent for candidate in kept)


def test_degree_merge_rejects_mismatched_frozen_union(sources):
    source = sources["degree_merged_set"]
    values = {"before": [], "after": [sp.Interval(0, sp.oo)], "case_results": [
        {"outputs": {"solution": sp.FiniteSet(0)}}, {"outputs": {"solution": sp.Interval.open(0, sp.oo)}}]}
    data = facts(source, values, CONTEXT)
    assert data["answer"] == sp.Interval(0, sp.oo)
    broken = deepcopy(values)
    broken["after"] = [sp.Interval.open(0, sp.oo)]
    with pytest.raises(interaction.NotInteractive, match="merge_evidence_unverified"):
        source["facts"](broken, CONTEXT)


def test_real_registry_compiles_algebra_seeds_and_does_not_read_later_cards():
    registry = interaction.load_registry()
    before = sp.Le(-x**2+2*x+3, a**2-3*a, evaluate=False)
    relation = sp.Ge(x**2-2*x+a**2-3*a-3, 0, evaluate=False)
    seed = _seed("normalize", {"before": [before], "after": [relation]}, CONTEXT,
                 method="method-discriminant#normalize", known=_known("∀x∈ℝ:-x^2+2*x+3<=a^2-3*a"))
    chunk, diagnostics = interaction.build_chunk([seed], registry, {"previous": 0})
    assert chunk["status"] == "interactive", diagnostics
    interaction.validate_chunk(chunk)
    assert len(chunk["parts"]) == 1
    assert all(row.get("result") != "compile_error" for row in diagnostics)
