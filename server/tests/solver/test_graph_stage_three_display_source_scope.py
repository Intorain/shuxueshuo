"""Combined displays retain explicit, case-local evidence from several steps."""

import json

import pytest
from jsonschema import ValidationError

from shuxueshuo_server.graph_lesson.stage_three import driver, execution_contracts
from shuxueshuo_server.graph_lesson.stage_three.presentation import math_step_hash
from tests.solver.test_graph_stage_three_batch_five import _finish_swap
from tests.solver.test_graph_stage_three_execution import simple
from tests.solver.test_graph_stage_three_methods import candidate, start


def scoped_contract(scope):
    contract = execution_contracts.read("method-discriminant")
    step = next(step for step in contract["steps"] if step["id"] == "solve")
    next(unit for unit in step["display_units"] if unit["id"] == "solution")["source_scope"] = scope
    return contract


@pytest.mark.parametrize("scope", [
    {"step": "conditions", "actions": ["delta"]},
    {"steps": ["conditions", "solve"]},
    {"steps": ["conditions", "solve"], "actions": ["delta", "opening_branches"]},
])
def test_single_and_multiple_step_scopes_validate(scope):
    execution_contracts.validate_contract(scoped_contract(scope))


@pytest.mark.parametrize("scope", [
    {}, {"steps": []}, {"steps": ["solve", "solve"]},
    {"step": "solve", "steps": ["conditions"]},
])
def test_scope_requires_one_unambiguous_nonempty_step_selection(scope):
    with pytest.raises(ValidationError):
        execution_contracts.validate_contract(scoped_contract(scope))


@pytest.mark.parametrize("scope", [
    {"steps": ["conditions", "missing"]},
    {"steps": ["conditions", "merge"]},
    {"steps": ["conditions", "solve"], "actions": ["missing"]},
])
def test_multiple_step_scopes_cannot_claim_future_or_unknown_operations(scope):
    with pytest.raises(ValueError, match="execution.invalid_display_source_scope"):
        execution_contracts.validate_contract(scoped_contract(scope))


@pytest.mark.parametrize("scope,expected_steps,expected_ref", [
    ({"step": "conditions", "actions": ["delta"]}, {"conditions"}, "conditions"),
    ({"steps": ["conditions", "solve"]}, {"conditions", "solve"}, "solve"),
])
def test_scoped_sources_are_case_local_and_keep_the_display_method_step(scope, expected_steps, expected_ref):
    contracts = execution_contracts.load_contracts()
    contracts["method-discriminant"] = scoped_contract(scope)
    state = start(candidate("∀x∈ℝ:a*x^2+x+1>=0"))
    for _ in range(200):
        if state["status"] != "running":
            break
        previous = state["fragments"]
        state = driver.advance(json.loads(json.dumps(state)), contracts=contracts)
        assert state["fragments"][:len(previous)] == previous
    assert state["status"] == "method_complete", state["diagnostics"]
    cards = [card for card in state["fragments"] if card["display_unit"] == "solution"]
    assert cards
    for card in cards:
        records = []
        for reference in card["source_refs"]:
            _, _, index, category, item = reference.split("/")
            trace = state["trajectory"]["steps"][int(index)]
            records.append((trace, trace[category][int(item)]))
        assert {trace["step"] for trace, _ in records} == expected_steps
        assert {trace["method"] for trace, _ in records} == {"method-discriminant"}
        paths = {tuple(trace["case_path"]) for trace, _ in records}
        assert len(paths) == 1
        path, = paths
        assert tuple(card["case_path"][:len(path)]) == path
        assert card["method_ref"] == "method-discriminant#" + expected_ref
        if scope.get("actions"):
            assert {item.get("action_id", item.get("id")) for _, item in records} == set(scope["actions"])
        else:
            assert any(item.get("action_id") == "delta" for _, item in records)
            assert any(item.get("capability") == "quadratic_opening_solutions" for _, item in records)


@pytest.mark.parametrize("fact,case_count", [
    ("∀m∈[1,3]:m*(x^2-x+1)-6<0", 1),
    ("∀m∈[-1,1]:x*m-1<0", 3),
])
def test_combined_affine_cards_include_range_and_solve_without_sibling_sources(fact, case_count):
    state = _finish_swap(simple(fact, symbol="x"))
    assert state["status"] == "method_complete", state["diagnostics"]
    cards = [card for card in state["fragments"] if card["display_unit"] == "sign_case"]
    assert len(cards) == case_count
    for card in cards:
        records = []
        for reference in card["source_refs"]:
            _, _, index, category, item = reference.split("/")
            trace = state["trajectory"]["steps"][int(index)]
            assert trace["case_path"] == card["case_path"]
            assert trace["method"] == "method-variable-swap"
            records.append((trace, trace[category][int(item)]))
        assert {trace["step"] for trace, _ in records} == {"range", "solve"}
        assert card["method_ref"] == "method-variable-swap#solve"
        assert any(item.get("capability") == "parameter_linear_case_range" for _, item in records)
        assert any(item.get("capability") == "intersect_variable_case_solution" for _, item in records)
        if card["case_path"]:
            assert not any(item.get("id") == "plan" and trace["step"] == "range" for trace, item in records)


@pytest.mark.parametrize("hidden_after,hidden_actions", [
    ("move", {"move"}),
    ("simplify", {"move", "simplify"}),
])
def test_scoped_display_retains_exact_hidden_sources_without_intervening_operations(hidden_after, hidden_actions):
    contracts = execution_contracts.load_contracts()
    contract = contracts["method-discriminant"]
    normalize = next(step for step in contract["steps"] if step["id"] == "normalize")
    normalize["display_units"][0]["after"] = hidden_after
    conditions = next(step for step in contract["steps"] if step["id"] == "conditions")
    opening = conditions["display_units"][0]
    # Publish after unrelated operations have appended to both trace records.
    # Its explicit scope still selects only the opening operation.
    opening.update(after="transform", source_scope={"step": "conditions", "actions": ["opening"]})
    execution_contracts.validate_contract(contract)

    def finish(state):
        for _ in range(200):
            if state["status"] != "running":
                return state
            state = driver.advance(json.loads(json.dumps(state)), contracts=contracts)
        raise AssertionError("nonterminating")

    state = start(candidate("∀x∈ℝ:(a^2-1)*x^2+x+1>=0"))
    while not any("pending_display_trace" in frame for frame in state["frames"]):
        assert state["status"] == "running", state["diagnostics"]
        state = driver.advance(state, contracts=contracts)
    checkpoint = json.loads(json.dumps(state))
    finished, resumed = finish(state), finish(checkpoint)
    assert finished["status"] == "method_complete", finished["diagnostics"]
    assert resumed["fragments"] == finished["fragments"]
    assert resumed["interaction_seeds"] == finished["interaction_seeds"]
    assert resumed["trajectory"] == finished["trajectory"]
    assert resumed["result"] == finished["result"]

    card, = [card for card in finished["fragments"] if card["display_unit"] == "opening"]
    assert "normalized" not in {card["display_unit"] for card in finished["fragments"]}
    records = []
    for reference in card["source_refs"]:
        _, _, index, category, item = reference.split("/")
        trace = finished["trajectory"]["steps"][int(index)]
        assert trace["case_path"] == card["case_path"] == ["nondegenerate"]
        assert trace["method"] == "method-discriminant"
        records.append((trace["step"], trace[category][int(item)]))
    assert {(step, item["action_id"]) for step, item in records} == {
        *(('normalize', action) for action in hidden_actions), ("conditions", "opening"),
    }
    assert len(card["source_refs"]) == len(set(card["source_refs"])) == len(hidden_actions) + 1
    assert card["used_basis"] == sorted({basis for _, item in records for basis in item.get("used_basis", [])})
    assert card["math_step_sha256"] == math_step_hash(card)
    hidden_sources = {reference for reference in card["source_refs"]
                      if finished["trajectory"]["steps"][int(reference.split("/")[2])]["step"] == "normalize"}
    assert all(not hidden_sources.intersection(other["source_refs"])
               for other in finished["fragments"] if other["ordinal"] > card["ordinal"])
