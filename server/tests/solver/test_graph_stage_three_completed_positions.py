"""Completed quadratic pictures preserve the same checked relation as the question."""

import json
from copy import deepcopy

import pytest
import sympy as sp
from jsonschema import Draft202012Validator, ValidationError

from shuxueshuo_server.graph_lesson.stage_three import interaction
from shuxueshuo_server.graph_lesson.stage_three.contracts import ROOT
from shuxueshuo_server.graph_lesson.stage_three.presentation_templates import (
    render_highlight,
    validate_registry,
)
from tests.solver.test_graph_stage_three_interaction_quadratic_direction import (
    OPERATORS,
    frozen,
)
from tests.solver.test_graph_stage_three_interactions import _seed
from tests.solver.test_graph_stage_three_opening_direction import (
    assert_excluded,
    direction_parts,
)


@pytest.mark.parametrize("quantifier", ["∀", "∃"])
@pytest.mark.parametrize("operator", OPERATORS)
def test_completed_pictures_are_exactly_the_allowed_positions(quantifier, operator):
    values, context, side, direction = frozen(quantifier, operator)
    seed = _seed("opening", values, context, method="method-discriminant#conditions")
    chunk, diagnostics = interaction.build_chunk([seed], interaction.load_registry(), {"previous": 0})
    assert chunk["status"] == "interactive", diagnostics
    parts = direction_parts(chunk)
    part = parts[direction]
    assert_excluded(parts[-direction], "本题不存在这种开口")
    assert part["completion_group"] == f"开口{'向上' if direction > 0 else '向下'}"
    pictures = part.get("completion_graphs", [part.get("completion_graph")])
    assert len(pictures) == (1 if operator in (">", "<") else 2)
    vertices = {graph["params"]["vertex"][1] for graph in pictures}
    assert vertices == ({side} if operator in (">", "<") else {side, 0})
    for graph in pictures:
        interaction.graph_contract.validate_graph(graph)
        assert graph["params"]["coefficient"] == direction
        assert sp.Rel(graph["params"]["vertex"][1], 0, operator) is sp.true
        assert "位置示意" in graph["caption"]
        assert ("向上" in graph["caption"]) == (direction > 0)
    interaction.validate_chunk(chunk)


def test_completed_graph_cannot_accept_a_tampered_normalized_relation():
    values, context, _, _ = frozen("∃", "<=")
    values["relation"] = sp.Lt(values["relation"].lhs, 0, evaluate=False)
    seed = _seed("opening", values, context, method="method-discriminant#conditions")
    with pytest.raises(interaction.NotInteractive, match="opening_evidence_unverified"):
        interaction.COMPLETION_GRAPHS["opening_up_positions"]([seed])


@pytest.mark.parametrize("quantifier,coefficient,reason", [
    ("∃", 1, "existence_automatic"),
    ("∀", -1, "universal_opening_impossible"),
])
def test_inactive_discriminant_question_retains_its_actual_readonly_reason(quantifier, coefficient, reason):
    values, context, _, _ = frozen(quantifier, ">=", coefficient=coefficient)
    seed = _seed("discriminant", values, context, method="method-discriminant#conditions")
    chunk, diagnostics = interaction.build_chunk([seed], interaction.load_registry(), {"previous": 0})
    assert chunk["status"] == "readonly", diagnostics
    assert chunk["reason"] == reason


def test_graph_alternative_marker_is_explicit_validated_and_preserved():
    spec = {"title": "结论", "explanation": "推导", "required_bindings": ["expression"],
            "highlight": {"caption": "结论", "items": [{"label": "关系", "math": "{expression}"}],
                          "replace_with_graph": True}}
    registry = {"templates": {"sample": spec}, "case_prefix": ""}
    validate_registry(registry)
    highlight = render_highlight(spec, {"expression": sp.Symbol("t")})
    assert highlight["replace_with_graph"] is True
    schema = json.loads((ROOT / "internal/schemas/graph-math-step-v2.schema.json").read_text())
    validator = Draft202012Validator(schema["properties"]["highlight"])
    validator.validate(highlight)
    invalid = deepcopy(registry)
    invalid["templates"]["sample"]["highlight"]["replace_with_graph"] = 1
    with pytest.raises(ValueError, match="invalid_highlight"):
        validate_registry(invalid)
    with pytest.raises(ValidationError):
        validator.validate({**highlight, "replace_with_graph": "yes"})

    spec["required_bindings"].append("complete")
    spec["highlight"]["replace_with_graph"] = "complete"
    validate_registry(registry)
    assert "replace_with_graph" not in render_highlight(spec, {"expression": sp.Symbol("t"), "complete": False})
    assert render_highlight(spec, {"expression": sp.Symbol("t"), "complete": True})["replace_with_graph"] is True
    with pytest.raises(ValueError, match="invalid_graph_alternative"):
        render_highlight(spec, {"expression": sp.Symbol("t"), "complete": "yes"})
