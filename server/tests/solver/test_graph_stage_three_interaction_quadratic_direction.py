"""Quadratic option graphs retain the frozen normalized inequality direction."""

from copy import deepcopy

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import interaction, interaction_algebra
from tests.solver.test_graph_stage_three_interaction_algebra import candidates, facts
from tests.solver.test_graph_stage_three_interactions import _seed

t, b = sp.symbols("t b", real=True)
OPERATORS = (">", ">=", "<", "<=")


def frozen(quantifier, operator, *, coefficient=None):
    side = 1 if operator in (">", ">=") else -1
    direction = side if quantifier == "∀" else -side
    polynomial = (direction if coefficient is None else coefficient)*t**2+b
    relation = sp.Rel(polynomial, 0, operator, evaluate=False)
    # The original context has not been normalized, while the card has. Only
    # the frozen card relation may be presented; the residual checks equality.
    context = {"x": t, "parameter": b, "domain": sp.S.Reals, "quantifier": quantifier,
               "relation": sp.Rel(polynomial+2, 2, operator, evaluate=False), "expression": side*polynomial}
    values = {"relation": relation, "expression": side*polynomial, "strict": operator in (">", "<"),
              "before": [], "after": []}
    return values, context, side, direction


@pytest.fixture
def extension():
    return interaction_algebra.register(interaction.EXTENSION_API)


def direction_source(extension, direction, *, unavailable=False):
    name = "up" if direction > 0 else "down"
    suffix = "unavailable" if unavailable else "positions"
    return extension["answers"][f"opening_{name}_{suffix}"]


@pytest.mark.parametrize("quantifier", ["∀", "∃"])
@pytest.mark.parametrize("operator", OPERATORS)
def test_all_quantifiers_and_comparisons_keep_actual_vertex_height_and_opening(extension, quantifier, operator):
    values, context, side, direction = frozen(quantifier, operator)
    source = direction_source(extension, direction)
    data = facts(source, values, context)
    item, = source["answer"](data)
    wrong, _, additional = source["validate"](data, values, context, item, candidates(source, data, item))
    correct = [item["answer"], *additional]
    expected = {side} if operator in (">", "<") else {side, 0}
    assert {int(option.value) for option in correct} == expected
    assert data["display"]["relation"] == values["relation"]
    assert data["display"]["expression"] == values["relation"].lhs
    extreme, opening = ("最低点", "向上") if direction > 0 else ("最高点", "向下")
    assert extreme in data["display"]["opening_feedback"]
    assert f"横轴{'上方' if side > 0 else '下方'}" in data["display"]["opening_feedback"]
    options = [(option, True) for option in correct] + [(option, False) for option in wrong]
    graphs, note = extension["option_graphs"]["opening_positions"][1](data, values, context, options)
    assert opening in note
    for graph, (option, correct) in zip(graphs, options, strict=True):
        interaction.graph_contract.validate_graph(graph)
        assert graph["params"]["coefficient"] == direction
        assert graph["params"]["vertex"] == [0, float(option.value)]
        assert (sp.Rel(option.value, 0, operator) is sp.true) is correct
        if option.value == 0:
            assert "相切" in option.label
        elif direction*option.value < 0:
            assert "两个公共点" in option.label
        else:
            assert ("上方" in option.label) == (option.value > 0)


@pytest.mark.parametrize("operator", OPERATORS)
def test_automatic_existence_follows_normalized_coefficient_and_comparison(extension, operator):
    side = 1 if operator in (">", ">=") else -1
    values, context, _, _ = frozen("∃", operator, coefficient=2*side)
    source = direction_source(extension, side)
    data = facts(source, values, context)
    item, = source["answer"](data)
    wrong, _, additional = source["validate"](data, values, context, item, candidates(source, data, item))
    assert wrong == []
    assert {option.value for option in [item["answer"], *additional]} == {-1, 0, 1}
    assert "三种位置都可以" in data["display"]["opening_feedback"]
    absent = direction_source(extension, -side, unavailable=True)["facts"](values, context)
    assert absent["unavailable_label"] == "本题不存在这种开口"
    chunk, diagnostics = interaction.build_chunk(
        [_seed("opening", values, context, method="method-discriminant#conditions")],
        interaction.load_registry(), {"previous": 0})
    assert chunk["status"] == "interactive", diagnostics
    assert [part["title"] for part in chunk["parts"]] == [
        "判断开口向上的情况", "判断开口向下的情况"]


@pytest.mark.parametrize("operator", OPERATORS)
def test_impossible_universal_opening_does_not_draw_the_opposite_parabola(extension, operator):
    side = 1 if operator in (">", ">=") else -1
    values, context, _, _ = frozen("∀", operator, coefficient=-2*side)
    rejected = direction_source(extension, -side, unavailable=True)["facts"](values, context)
    assert rejected["direction"] == -side and rejected["unavailable_label"] == "此开口不适合"
    absent = direction_source(extension, side, unavailable=True)["facts"](values, context)
    assert absent["unavailable_label"] == "本题不存在这种开口"
    for direction in (-1, 1):
        with pytest.raises(interaction.NotInteractive, match="opening_direction_part_not_needed"):
            direction_source(extension, direction)["facts"](values, context)
    chunk, diagnostics = interaction.build_chunk(
        [_seed("opening", values, context, method="method-discriminant#conditions")],
        interaction.load_registry(), {"previous": 0})
    assert chunk["status"] == "interactive", diagnostics
    assert [part["title"] for part in chunk["parts"]] == [
        "判断开口向上的情况", "判断开口向下的情况"]


@pytest.mark.parametrize("quantifier", ["∀", "∃"])
@pytest.mark.parametrize("operator", OPERATORS)
def test_parameter_coefficient_is_a_conditional_opening_question(extension, quantifier, operator):
    values, context, _, direction = frozen(quantifier, operator, coefficient=b)
    data = direction_source(extension, direction)["facts"](values, context)
    condition = sp.Rel(b, 0, ">" if direction > 0 else "<", evaluate=False)
    assert data["display"]["opening_question"].startswith("当 ")
    assert interaction._latex(condition) in data["display"]["opening_question"]
    assert f"图像开口{'向上' if direction > 0 else '向下'}" in data["display"]["opening_question"]
    assert ("至少有一个实数解" in data["display"]["opening_question"]) == (quantifier == "∃")


@pytest.mark.parametrize("quantifier", ["∀", "∃"])
@pytest.mark.parametrize("operator", OPERATORS)
def test_discriminant_scope_and_feedback_use_same_normalized_parabola(extension, quantifier, operator):
    values, context, side, direction = frozen(quantifier, operator)
    delta = -4*direction*b
    delta_operator = ("<" if values["strict"] else "<=") if quantifier == "∀" else (">" if values["strict"] else ">=")
    values.update(before=[sp.Rel(delta, 0, delta_operator, evaluate=False)], after=[])
    data = extension["answers"]["discriminant_condition"]["facts"](values, context)
    opening, extreme = ("向上", "最低点") if direction > 0 else ("向下", "最高点")
    assert opening in data["display"]["scope_note"]
    assert extreme in data["display"]["delta_feedback"]
    assert f"横轴{'上方' if side > 0 else '下方'}" in data["display"]["delta_feedback"]
    if quantifier == "∃":
        assert "对所有" not in data["display"]["scope_note"]


@pytest.mark.parametrize("change", ["missing_relation", "opposite_relation", "strictness", "nonzero_rhs"])
def test_unverified_normalized_relation_does_not_generate_inconsistent_graphs(extension, change):
    values, context, _, _ = frozen("∃", "<=")
    if change == "missing_relation":
        del values["relation"]
    elif change == "opposite_relation":
        values["relation"] = sp.Ge(values["relation"].lhs, 0, evaluate=False)
    elif change == "strictness":
        values["strict"] = True
    else:
        values["relation"] = context["relation"]
    with pytest.raises(interaction.NotInteractive, match="opening_evidence"):
        direction_source(extension, 1)["facts"](values, context)


def test_discriminant_rejects_changed_strictness_without_a_strict_binding(extension):
    values, context, _, _ = frozen("∃", "<=")
    del values["strict"]
    values.update(relation=sp.Lt(values["relation"].lhs, 0, evaluate=False),
                  before=[sp.Gt(-4*b, 0, evaluate=False)])
    with pytest.raises(interaction.NotInteractive, match="opening_evidence_unverified"):
        extension["answers"]["discriminant_condition"]["facts"](values, context)


def test_equivalent_normalization_can_reverse_direction_while_preserving_strictness(extension):
    values, context, _, _ = frozen("∃", "<")
    context["relation"] = sp.Gt(-values["relation"].lhs, 0, evaluate=False)
    data = direction_source(extension, 1)["facts"](values, context)
    assert data["display"]["relation"] == values["relation"]
    assert data["direction"] == 1 and data["strict"] is True


def test_compiled_less_equal_question_preserves_formula_and_upward_graphs():
    values, context, _, _ = frozen("∃", "<=")
    snapshot = deepcopy(values)
    chunk, diagnostics = interaction.build_chunk(
        [_seed("opening", values, context, method="method-discriminant#conditions")],
        interaction.load_registry(), {"previous": 0})
    assert values == snapshot
    assert chunk["status"] == "interactive", diagnostics
    interaction.validate_chunk(chunk)
    part, excluded = chunk["parts"]
    assert excluded["interaction"]["type"] == "choice"
    assert interaction._latex(values["relation"]) in part["question"]
    assert "最低点" in part["feedback"]["answer"]
    assert "最高点" not in part["feedback"]["answer"] and "向下" not in part["question"]
    assert all(option["graph"]["params"]["coefficient"] == 1 for option in part["interaction"]["options"])


def test_only_current_opening_question_sources_are_registered(extension):
    retired = {"opening_positions", "opening_direction", "automatic_opening_positions"}
    assert not retired & extension["answers"].keys()
    assert not retired & extension["completion_graphs"].keys()
    supported, _ = extension["option_graphs"]["opening_positions"]
    assert supported == {"opening_up_positions", "opening_down_positions"}
