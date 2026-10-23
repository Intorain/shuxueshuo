"""Identity normalization stays internal; case transitions remain explicit."""

import json
from copy import deepcopy

import pytest
import sympy as sp
from jsonschema import Draft202012Validator

from shuxueshuo_server.graph_lesson.stage_three import driver, interaction
from shuxueshuo_server.graph_lesson.stage_three.math_values import math_value
from shuxueshuo_server.graph_lesson.stage_three.presentation import (
    math_step_hash,
    omit_unchanged_unit,
)
from shuxueshuo_server.graph_lesson.stage_three.trajectory import decode_value
from tests.solver.test_graph_stage_three_methods import ROOT, candidate, finish, start

t, b = sp.symbols("t b", real=True)


def test_only_opted_in_structural_identity_is_hidden():
    before = sp.Ge(t*t+b, 0, evaluate=False)
    same = {"before": [before], "after": [before]}
    assert omit_unchanged_unit({"template": "normalize"}, same)
    assert not omit_unchanged_unit({"template": "opening"}, same)
    assert not omit_unchanged_unit({"template": "normalize"}, {"before": [], "after": []})
    # Mathematically equivalent is not enough: these transformations must be shown.
    for after in (sp.Le(-t*t-b, 0, evaluate=False), sp.Ge(2*t*t+2*b, 0, evaluate=False)):
        assert not omit_unchanged_unit({"template": "normalize"}, {"before": [before], "after": [after]})


@pytest.mark.parametrize("fact,expected", [
    ("∀t∈ℝ:b*t^2-6*b*t+b+8>=0", sp.Interval(0, 1)),
    ("∀t∈ℝ:t^2+b>=0", sp.Interval(0, sp.oo)),
    ("∃t∈ℝ:t^2+b<=0", sp.Interval(-sp.oo, 0)),
])
def test_unchanged_relation_has_no_card_or_quiz_but_keeps_math_and_call_sources(fact, expected):
    state = finish(start(candidate(fact, "b")))
    assert state["status"] == "method_complete", state["diagnostics"]
    assert driver.export_values(state)["feasible_set"] == expected
    assert "normalized" not in [card["display_unit"] for card in state["fragments"]]
    assert "normalize" not in [seed["template"] for seed in state["interaction_seeds"]]
    opening = next(card for card in state["fragments"] if card["display_unit"] == "opening")
    trace_index, normalize = next((i, trace) for i, trace in enumerate(state["trajectory"]["steps"])
                                 if trace["step"] == "normalize" and trace["calls"])
    assert [call["capability"] for call in normalize["calls"]] == ["normalize_to_zero", "simplify_expression"]
    assert all(f"/steps/{trace_index}/calls/{i}" in opening["source_refs"]
               for i in range(len(normalize["calls"])))
    assert [card["ordinal"] for card in state["fragments"]] == list(range(1, len(state["fragments"])+1))
    assert [seed["step_id"] for seed in state["interaction_seeds"]] == [card["step_id"] for card in state["fragments"]]
    compiled, pending = interaction.compile_route(state["interaction_seeds"], interaction.load_registry())
    assert pending == []
    assert not any(part["title"] == "整理不等式" for chunk, _ in compiled for part in chunk["parts"])


@pytest.mark.parametrize("fact", ["∃t∈ℝ:-t^2+b*t-1>=0", "∀t∈ℝ:t^2+b>=1"])
def test_actual_rearrangement_still_publishes_its_relation_and_seed(fact):
    state = finish(start(candidate(fact, "b")))
    assert state["status"] == "method_complete", state["diagnostics"]
    card = next(card for card in state["fragments"] if card["display_unit"] == "normalized")
    assert card["before"] != card["after"]
    assert card["highlight"]["connector"] == "⇔" and len(card["highlight"]["items"]) == 2
    assert any(seed["template"] == "normalize" and seed["step_id"] == card["step_id"]
               for seed in state["interaction_seeds"])


def test_resume_across_hidden_step_keeps_case_metadata_and_trace_immutable():
    state = start(candidate("∀t∈ℝ:b*t^2-6*b*t+b+8>=0", "b"))
    checkpoint = None
    while state["status"] == "running":
        state = driver.advance(state)
        if any("pending_display_trace" in frame for frame in state["frames"]):
            checkpoint = json.loads(json.dumps(state))
    assert checkpoint is not None
    resumed = finish(checkpoint)
    assert resumed["fragments"] == state["fragments"]
    assert resumed["trajectory"] == state["trajectory"]
    assert resumed["result"] == state["result"]
    schema = json.loads((ROOT / "internal/schemas/graph-math-step-v2.schema.json").read_text())
    validator = Draft202012Validator(schema)
    for card in state["fragments"]:
        validator.validate(card)
        assert card["math_step_sha256"] == math_step_hash(card)
        if not card["case_path"]:
            assert "case_condition" not in card
            continue
        seed = next(seed for seed in state["interaction_seeds"] if seed["step_id"] == card["step_id"])
        scoped_condition = decode_value(seed["values"])["case"]["condition"]
        if "branch_id" in card:
            # The source still belongs to the nonzero-coefficient execution case.
            condition = sp.Ne(b, 0, evaluate=False)
            assert card["branch_id"] == seed["branch_id"]
            assert card["branch_condition"] == seed["branch_condition"] == math_value(scoped_condition)
            for field, replacement in (("branch_id", "opening-wrong"),
                                       ("branch_condition", math_value(sp.Gt(b, 999)))):
                tampered = deepcopy(card)
                tampered[field] = replacement
                assert math_step_hash(tampered) != card["math_step_sha256"]
        else:
            condition = scoped_condition
        assert card["case_condition"] == math_value(condition)
        for reference in card["source_refs"]:
            trace = state["trajectory"]["steps"][int(reference.split("/")[2])]
            assert trace["case_path"] == card["case_path"]
        tampered = deepcopy(card)
        tampered["case_condition"]["latex"] = "b=999"
        assert math_step_hash(tampered) != card["math_step_sha256"]


def test_multiple_zero_coefficients_do_not_mix_cases_in_metadata_or_call_sources():
    state = finish(start(candidate("∀t∈ℝ:(b^2-1)*t^2+t+2>0", "b")))
    assert state["status"] == "method_complete", state["diagnostics"]
    cases = {}
    for card in state["fragments"]:
        if not card["case_path"]:
            continue
        path = tuple(card["case_path"])
        previous = cases.setdefault(path, card["case_condition"])
        assert previous == card["case_condition"]
        for reference in card["source_refs"]:
            trace_index = int(reference.split("/")[2])
            assert state["trajectory"]["steps"][trace_index]["case_path"] == card["case_path"]
    assert len(cases) == 3
    assert {condition["expression"] for condition in cases.values()} == {
        "Eq(b, -1)", "Eq(b, 1)", "Ne(b**2 - 1, 0)"}
    assert not any(card["display_unit"] == "normalized" for card in state["fragments"])
