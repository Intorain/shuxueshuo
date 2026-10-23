"""Degree classification and substitution cards retain concise, exact conclusions."""

import json
from copy import deepcopy
from functools import cache
from pathlib import Path

import pytest
import sympy as sp
from jsonschema import Draft202012Validator

from shuxueshuo_server.graph_lesson.stage_three import (
    driver,
    interaction,
    interaction_algebra,
)
from shuxueshuo_server.graph_lesson.stage_three.math_values import math_value
from shuxueshuo_server.graph_lesson.stage_three.trajectory import decode_value
from tests.solver.test_graph_stage_three_methods import candidate, finish, start


@cache
def validator():
    path = Path(__file__).resolve().parents[3] / "internal/schemas/graph-math-step-v2.schema.json"
    return Draft202012Validator(json.loads(path.read_text()))


@cache
def route(fact):
    state = finish(start(candidate(fact, "b")))
    assert state["status"] == "method_complete", state["diagnostics"]
    for card in state["fragments"]:
        validator().validate(card)
    return state


def cards(state, unit):
    return [card for card in state["fragments"] if card["display_unit"] == unit]


def test_classification_highlight_contains_actual_conditions_and_matches_interaction_title():
    state = route("∀t∈ℝ:b*t^2-6*b*t+b+8>=0")
    assert driver.export_values(state)["feasible_set"] == sp.Interval(0, 1)
    card, = cards(state, "case_basis")
    assert card["title"] == "判断二次项系数是否为 0"
    assert [item["math"] for item in card["highlight"]["items"]] == ["b = 0", r"b \neq 0"]
    assert "Longleftrightarrow" not in card["explanation"]  # Do not repeat b=0 on both sides.
    seed = next(item for item in state["interaction_seeds"] if item["template"] == "case_basis")
    chunk, diagnostics = interaction.build_chunk([seed], interaction.load_registry(), {"previous": 0})
    assert chunk["status"] == "interactive", diagnostics
    assert chunk["parts"][0]["title"] == card["title"]


def test_constant_case_highlight_keeps_the_parameter_and_verdict_without_bare_solution_set():
    state = route("∀t∈ℝ:b*t^2-6*b*t+b+8>=0")
    card, = cards(state, "degenerate_case")
    assert card["title"] == "检查二次项系数为 0 的情况"
    highlight = card["highlight"]
    assert highlight["show_result"] is True
    assert [item["math"] for item in highlight["items"]] == ["b = 0", r"8 \geq 0"]
    assert highlight["result"] == "满足原题，保留 $b = 0$。"
    assert r"\left\{0\right\}" not in str(highlight)
    assert card["explanation"] == r"$b = 0$ 时，原不等式化为 $8 \geq 0$。对所有实数成立。"
    # Rendering must not replace the certified numeric constant with a boolean.
    seed = next(item for item in state["interaction_seeds"] if item["template"] == "degenerate_case")
    assert decode_value(seed["values"])["constant"] == sp.Integer(8)
    chunk, diagnostics = interaction.build_chunk([seed], interaction.load_registry(), {"previous": 0})
    assert chunk["status"] == "interactive", diagnostics
    assert chunk["parts"][0]["title"] == card["title"]


def test_less_than_relation_preserves_the_visible_leading_coefficient():
    state = route("∃t∈ℝ:b*t^2+b*t<=0")
    assert driver.export_values(state)["feasible_set"] == sp.S.Reals
    card, = cards(state, "case_basis")
    assert card["explanation"].startswith("二次项系数为 $b$，令其为零：")
    assert [item["math"] for item in card["highlight"]["items"]] == ["b = 0", r"b \neq 0"]
    seed = next(item for item in state["interaction_seeds"] if item["template"] == "case_basis")
    values = decode_value(seed["values"])
    assert values["coefficient"] == -values["degree_coefficient"]
    chunk, diagnostics = interaction.build_chunk([seed], interaction.load_registry(), {"previous": 0})
    assert chunk["status"] == "interactive", diagnostics
    assert "二次项系数为 $b$" in chunk["parts"][0]["question"]
    assert "二次项系数为 $- b$" not in chunk["parts"][0]["question"]
    # Historical seeds use the frozen original relation in context as the direction evidence.
    source = interaction_algebra.register(interaction.EXTENSION_API)["answers"]["zero_coefficient"]
    old_values = {"coefficient": values["coefficient"], "parameter": values["parameter"]}
    context = decode_value(seed["context"])
    assert source["facts"](old_values, context)["display"]["coefficient"] == values["degree_coefficient"]
    inconsistent = deepcopy(values)
    inconsistent["degree_coefficient"] = values["coefficient"]
    with pytest.raises(interaction.NotInteractive, match="degree_coefficient_unverified"):
        source["facts"](inconsistent, context)


@pytest.mark.parametrize("quantifier,retained", [("∀", False), ("∃", True)])
def test_multiple_degenerate_values_keep_each_affine_check_and_quantifier(quantifier, retained):
    state = route(f"{quantifier}t∈ℝ:(b^2-1)*t^2+t+2>0")
    classification, = cards(state, "case_basis")
    zero_tex = classification["highlight"]["items"][0]["math"]
    assert "b = -1" in zero_tex and "b = 1" in zero_tex
    assert r"\Longleftrightarrow" in classification["explanation"]
    outcomes = cards(state, "degenerate_case")
    assert len(outcomes) == 2
    assert {card["highlight"]["items"][0]["math"] for card in outcomes} == {"b = -1", "b = 1"}
    for card in outcomes:
        assert card["highlight"]["items"][1]["math"] == "t + 2 > 0"
        assert ("保留" in card["highlight"]["result"]) is retained
        assert ("排除" in card["highlight"]["result"]) is not retained
        assert r"一次式的值域为 $\mathbb{R}$" in card["explanation"]
        assert ("存在实数解" in card["explanation"]) is retained


@pytest.mark.parametrize("operator,retained", [(">", False), (">=", True)])
def test_constant_zero_keeps_strictness_when_deciding_whether_to_retain(operator, retained):
    state = route(f"∃t∈ℝ:b*t^2+b*t{operator}0")
    card, = cards(state, "degenerate_case")
    relation = (sp.Gt if operator == ">" else sp.Ge)(0, 0, evaluate=False)
    assert card["highlight"]["items"][1]["math"] == math_value(relation)["latex"]
    assert r"\Longrightarrow" not in card["explanation"]  # Substitution must not imply a false inequality.
    assert ("保留" in card["highlight"]["result"]) is retained
    assert ("无实数解" in card["explanation"]) is not retained
