"""A known coefficient sign never hides the other opening discussion."""

from copy import deepcopy

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import interaction
from tests.solver.test_graph_stage_three_interaction_quadratic_direction import (
    OPERATORS,
    b,
    frozen,
)
from tests.solver.test_graph_stage_three_opening_direction import (
    assert_excluded,
    assert_positions,
    compile_opening,
    correct_options,
    direction_parts,
)


@pytest.fixture(scope="module")
def registry():
    return interaction.load_registry()


@pytest.mark.parametrize("quantifier", ["∀", "∃"])
@pytest.mark.parametrize("operator", OPERATORS)
@pytest.mark.parametrize("coefficient,actual", [
    (sp.Integer(2), 1), (-sp.Integer(2), -1), (b**2 + 1, 1), (-b**2 - 1, -1),
    (b**2, 1), (-b**2, -1),
])
def test_fixed_sign_discussion_checks_absence_before_tail_and_vertex_conditions(
        registry, quantifier, operator, coefficient, actual):
    values, context, side, _ = frozen(quantifier, operator, coefficient=coefficient)
    before = deepcopy((values, context))
    chunk, diagnostics = compile_opening(values, context, registry)
    assert chunk["status"] == "interactive", diagnostics
    assert (values, context) == before
    parts = direction_parts(chunk)
    assert_excluded(parts[-actual], "本题不存在这种开口")
    excluded_direction = "向下" if actual == 1 else "向上"
    assert f"因此不存在开口{excluded_direction}的情况" in parts[-actual]["feedback"]["answer"]

    if quantifier == "∀" and actual != side:
        assert_excluded(parts[actual], "此开口不适合")
        assert "不能使该关系对所有实数成立" in parts[actual]["feedback"]["answer"]
        return

    automatic = quantifier == "∃" and actual == side
    expected = {-1, 0, 1} if automatic else ({side} if operator in (">", "<") else {side, 0})
    part = parts[actual]
    assert_positions(part, actual, expected)
    selected = {option["value"] for option in correct_options(part)}
    for option in part["interaction"]["options"]:
        graph = option["graph"]
        interaction.graph_contract.validate_graph(graph)
        height = sp.sympify(graph["params"]["vertex"][1])
        # Independent witness/extremum check: a tail supplies a witness in
        # the automatic existence case; otherwise the vertex is decisive.
        ordinate = 4 * actual + height if automatic else height
        holds = sp.Rel(ordinate, 0, operator) is sp.true
        assert (option["value"] in selected) == holds


def test_zero_leading_coefficient_cannot_create_quadratic_position_questions(registry):
    values, context, _, _ = frozen("∃", ">=", coefficient=sp.S.Zero)
    chunk, _ = compile_opening(values, context, registry)
    assert chunk["status"] == "readonly"
    assert chunk["parts"] == []
    assert chunk["reason"] == "opening_evidence_unverified"
