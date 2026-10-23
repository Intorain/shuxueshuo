"""Existence with an unknown leading sign discusses both possible openings."""

from copy import deepcopy

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import driver, interaction
from tests.solver.test_graph_stage_three_interaction_quadratic_direction import (
    OPERATORS,
    b,
    frozen,
)
from tests.solver.test_graph_stage_three_methods import candidate, finish, start
from tests.solver.test_graph_stage_three_opening_direction import (
    assert_excluded,
    assert_positions,
    compile_opening,
    completed_pictures,
    correct_options,
    direction_parts,
)


@pytest.fixture(scope="module")
def registry():
    return interaction.load_registry()


@pytest.mark.parametrize("operator", OPERATORS)
@pytest.mark.parametrize("coefficient", [b, b - 2])
def test_existential_parameter_interaction_discusses_upward_then_downward_branch(registry, operator, coefficient):
    values, context, side, direction = frozen("∃", operator, coefficient=coefficient)
    before = deepcopy((values, context))
    chunk, diagnostics = compile_opening(values, context, registry)
    assert (values, context) == before
    assert chunk["status"] == "interactive", diagnostics
    parts = direction_parts(chunk)
    automatic, conditional = parts[side], parts[direction]
    assert automatic["title"] == f"判断开口{'向上' if side > 0 else '向下'}的情况"
    assert all(part["interaction"]["type"] == "multi" for part in chunk["parts"])
    assert all(interaction._latex(values["relation"]) in part["question"] for part in chunk["parts"])
    assert all("必须" not in part["question"] for part in chunk["parts"])

    choices = automatic["interaction"]["options"]
    assert len(choices) == 3
    assert {option["value"] for option in correct_options(automatic)} == {option["value"] for option in choices}
    assert {option["graph"]["params"]["vertex"][1] for option in choices} == {-1, 0, 1}
    for option in choices:
        graph = option["graph"]
        interaction.graph_contract.validate_graph(graph)
        assert graph["params"]["coefficient"] == side
        vertex_height = sp.sympify(graph["params"]["vertex"][1])
        # Even when the vertex fails the relation, either tail supplies a
        # witness. All three positions work for strict comparisons as well.
        assert sp.Rel(4 * side + vertex_height, 0, operator) is sp.true
    assert any(sp.Rel(option["graph"]["params"]["vertex"][1], 0, operator) is sp.false
               for option in choices)

    assert conditional["title"] == f"判断开口{'向上' if direction > 0 else '向下'}的情况"
    condition = sp.Rel(coefficient, 0, ">" if direction > 0 else "<", evaluate=False)
    assert interaction._latex(condition) in conditional["question"]
    assert all(option["graph"]["params"]["coefficient"] == direction
               for option in conditional["interaction"]["options"])
    required_vertices = {side} if operator in (">", "<") else {side, 0}
    assert {option["graph"]["params"]["vertex"][1]
            for option in correct_options(conditional)} == required_vertices

    assert automatic["completion_group"] == f"开口{'向上' if side > 0 else '向下'}"
    assert conditional["completion_group"] == f"开口{'向上' if direction > 0 else '向下'}"
    automatic_graphs = completed_pictures(automatic)
    conditional_graphs = completed_pictures(conditional)
    assert len(automatic_graphs) == 3
    assert {graph["params"]["coefficient"] for graph in automatic_graphs} == {side}
    assert {graph["params"]["vertex"][1] for graph in automatic_graphs} == {-1, 0, 1}
    assert {graph["params"]["coefficient"] for graph in conditional_graphs} == {direction}
    assert {graph["params"]["vertex"][1] for graph in conditional_graphs} == required_vertices


@pytest.mark.parametrize("quantifier", ["∀", "∃"])
@pytest.mark.parametrize("operator", OPERATORS)
def test_known_signs_keep_two_questions_and_explain_the_missing_direction(registry, quantifier, operator):
    values, context, side, direction = frozen(quantifier, operator)
    chunk, diagnostics = compile_opening(values, context, registry)
    assert chunk["status"] == "interactive", diagnostics
    parts = direction_parts(chunk)
    assert_excluded(parts[-direction], "本题不存在这种开口")
    assert_positions(parts[direction], direction, {side} if operator in (">", "<") else {side, 0})


@pytest.mark.parametrize("operator", OPERATORS)
def test_universal_parameter_problem_explicitly_checks_both_directions(registry, operator):
    values, context, side, _ = frozen("∀", operator, coefficient=b)
    chunk, diagnostics = compile_opening(values, context, registry)
    assert chunk["status"] == "interactive", diagnostics
    parts = direction_parts(chunk)
    assert_excluded(parts[-side], "此开口不适合")
    assert_positions(parts[side], side, {side} if operator in (">", "<") else {side, 0})


@pytest.mark.parametrize("change", ["missing_relation", "opposite_comparison", "changed_strictness", "changed_polynomial"])
def test_neither_existential_branch_can_use_unverified_evidence(registry, change):
    values, context, _, _ = frozen("∃", ">", coefficient=b)
    if change == "missing_relation":
        del values["relation"]
    elif change == "opposite_comparison":
        values["relation"] = sp.Lt(values["relation"].lhs, 0, evaluate=False)
    elif change == "changed_strictness":
        values["relation"] = sp.Ge(values["relation"].lhs, 0, evaluate=False)
    else:
        values["relation"] = sp.Gt(-values["relation"].lhs, 0, evaluate=False)
    chunk, _ = compile_opening(values, context, registry)
    assert chunk["status"] == "readonly"
    assert chunk["parts"] == []
    assert chunk["reason"].startswith("opening_evidence_")


def test_real_k_existential_problem_retains_both_branches_and_correct_answer(registry):
    state = finish(start(candidate("∃x∈ℝ:k*x^2-k*x-1>0", "k")))
    assert state["status"] == "method_complete", state["diagnostics"]
    assert driver.export_values(state)["feasible_set"] == sp.Union(
        sp.Interval.open(-sp.oo, -4), sp.Interval.open(0, sp.oo))
    seed, = [seed for seed in state["interaction_seeds"] if seed["template"] == "opening"]
    chunk, diagnostics = interaction.build_chunk([seed], registry, {"previous": 0})
    assert chunk["status"] == "interactive", diagnostics
    interaction.validate_chunk(chunk)
    parts = direction_parts(chunk)
    automatic, conditional = parts[1], parts[-1]
    assert automatic["title"] == "判断开口向上的情况"
    assert len(correct_options(automatic)) == 3
    assert all(option["graph"]["params"]["coefficient"] == 1 for option in correct_options(automatic))
    downward, = correct_options(conditional)
    assert downward["graph"]["params"]["coefficient"] == -1
    assert downward["graph"]["params"]["vertex"][1] > 0
