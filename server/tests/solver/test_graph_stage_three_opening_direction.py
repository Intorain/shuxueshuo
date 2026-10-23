"""Discuss upward and downward openings in a stable order, including exclusions."""

from copy import deepcopy

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import driver, interaction
from tests.solver.test_graph_stage_three_interaction_quadratic_direction import (
    OPERATORS,
    b,
    frozen,
)
from tests.solver.test_graph_stage_three_interactions import _seed
from tests.solver.test_graph_stage_three_methods import candidate, finish, start


@pytest.fixture(scope="module")
def registry():
    return interaction.load_registry()


def compile_opening(values, context, registry):
    seed = _seed("opening", values, context, method="method-discriminant#conditions")
    chunk, diagnostics = interaction.build_chunk([seed], registry, {"previous": 0})
    interaction.validate_chunk(chunk)
    return chunk, diagnostics


def correct_options(part):
    answer = part["expected_answer"]
    expected = answer.get("one_of", answer.get("required"))
    return [option for option in part["interaction"]["options"] if option["value"] in expected]


def direction_parts(chunk):
    assert [part["title"] for part in chunk["parts"]] == [
        "判断开口向上的情况", "判断开口向下的情况"]
    return dict(zip((1, -1), chunk["parts"], strict=True))


def completed_pictures(part):
    if "completion_graphs" in part:
        return part["completion_graphs"]
    return [part["completion_graph"]] if "completion_graph" in part else []


def assert_positions(part, direction, expected_heights):
    assert part["interaction"]["type"] == "multi"
    choices = part["interaction"]["options"]
    assert len(choices) == 3
    assert all(option["graph"]["params"]["coefficient"] == direction for option in choices)
    assert {option["graph"]["params"]["vertex"][1] for option in choices} == {-1, 0, 1}
    assert {option["graph"]["params"]["vertex"][1]
            for option in correct_options(part)} == expected_heights
    graphs = completed_pictures(part)
    assert {graph["params"]["vertex"][1] for graph in graphs} == expected_heights
    assert all(graph["params"]["coefficient"] == direction for graph in graphs)
    assert part["completion_group"] == f"开口{'向上' if direction > 0 else '向下'}"


def assert_excluded(part, label):
    assert part["interaction"]["type"] == "choice"
    correct, = correct_options(part)
    assert correct["label"] == label
    wrong, = [option for option in part["interaction"]["options"] if option != correct]
    assert wrong["label"] == "可继续判断图像位置"
    assert wrong["feedback"]
    assert not any("graph" in option for option in part["interaction"]["options"])
    assert not completed_pictures(part)


@pytest.mark.parametrize("operator", OPERATORS)
@pytest.mark.parametrize("coefficient", [b, b - 2])
def test_universal_parameter_problem_explicitly_rejects_the_opposite_opening(registry, operator, coefficient):
    values, context, side, _ = frozen("∀", operator, coefficient=coefficient)
    before = deepcopy((values, context))
    chunk, diagnostics = compile_opening(values, context, registry)
    assert (values, context) == before
    assert chunk["status"] == "interactive", diagnostics
    parts = direction_parts(chunk)
    positions, rejected = parts[side], parts[-side]
    assert all(interaction._latex(values["relation"]) in part["question"] for part in parts.values())
    assert "对所有实数成立" in positions["question"]
    condition = sp.Rel(coefficient, 0, ">" if side > 0 else "<", evaluate=False)
    assert interaction._latex(condition) in positions["question"]
    assert_excluded(rejected, "此开口不适合")
    feedback = rejected["feedback"]["answer"]
    assert "不能使该关系对所有实数成立" in feedback
    assert ("负无穷" if side > 0 else "正无穷") in feedback
    assert_positions(positions, side, {side} if operator in (">", "<") else {side, 0})


@pytest.mark.parametrize("operator", OPERATORS)
@pytest.mark.parametrize("coefficient", [sp.Integer(2), b**2 + 1])
def test_proven_opening_still_discusses_and_rejects_the_other_direction(registry, operator, coefficient):
    side = 1 if operator in (">", ">=") else -1
    values, context, _, _ = frozen("∀", operator, coefficient=side * coefficient)
    chunk, diagnostics = compile_opening(values, context, registry)
    assert chunk["status"] == "interactive", diagnostics
    parts = direction_parts(chunk)
    assert_excluded(parts[-side], "本题不存在这种开口")
    assert_positions(parts[side], side, {side} if operator in (">", "<") else {side, 0})


@pytest.mark.parametrize("operator", OPERATORS)
def test_existential_problem_does_not_claim_one_opening_is_necessary(registry, operator):
    values, context, side, direction = frozen("∃", operator, coefficient=b - 2)
    chunk, diagnostics = compile_opening(values, context, registry)
    assert chunk["status"] == "interactive", diagnostics
    parts = direction_parts(chunk)
    assert_positions(parts[side], side, {-1, 0, 1})
    assert_positions(parts[direction], direction, {side} if operator in (">", "<") else {side, 0})
    for part in parts.values():
        assert "至少有一个实数解" in part["question"]
        assert "对所有实数" not in part["question"]
        assert "必须" not in part["question"]


@pytest.mark.parametrize("change", ["missing_relation", "opposite_comparison", "changed_strictness", "changed_polynomial"])
def test_unverified_relation_cannot_supply_a_direction_or_position_question(registry, change):
    values, context, _, _ = frozen("∀", ">=", coefficient=b)
    if change == "missing_relation":
        del values["relation"]
    elif change == "opposite_comparison":
        values["relation"] = sp.Le(values["relation"].lhs, 0, evaluate=False)
    elif change == "changed_strictness":
        values["relation"] = sp.Gt(values["relation"].lhs, 0, evaluate=False)
    else:
        values["relation"] = sp.Ge(-values["relation"].lhs, 0, evaluate=False)
    chunk, _ = compile_opening(values, context, registry)
    assert chunk["status"] == "readonly"
    assert chunk["parts"] == []
    assert chunk["reason"].startswith("opening_evidence_")


def test_real_k_problem_driver_seed_compiles_the_two_questions(registry):
    state = finish(start(candidate("∀x∈ℝ:k*x^2-6*k*x+k+8>=0", "k")))
    assert state["status"] == "method_complete", state["diagnostics"]
    assert driver.export_values(state)["feasible_set"] == sp.Interval(0, 1)
    seed, = [seed for seed in state["interaction_seeds"] if seed["template"] == "opening"]
    chunk, diagnostics = interaction.build_chunk([seed], registry, {"previous": 0})
    assert chunk["status"] == "interactive", diagnostics
    interaction.validate_chunk(chunk)
    parts = direction_parts(chunk)
    assert "$k > 0$" in parts[1]["question"]
    assert_positions(parts[1], 1, {0, 1})
    assert_excluded(parts[-1], "此开口不适合")
