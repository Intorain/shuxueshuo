"""Coalesce invisible guarded calls without moving observable checkpoints."""

import json
from copy import deepcopy

import pytest

from shuxueshuo_server.graph_lesson.stage_three import driver, execution_contracts
from tests.solver.test_graph_stage_three_methods import CORPUS, Q01, candidate, start


def _insert_empty_skips(step):
    for number in (1, 2):
        step["calls"].append({
            "id": f"unused-{number}",
            "capability": "must_not_execute",
            "public_ref": None,
            "inputs": {},
            "outputs": {},
            "guard": {"constant": False},
            "skip_reason": "not_selected",
            "order": -10 + number,
        })


@pytest.mark.parametrize("method,category", [
    ("method-separation", "calls"),
    ("method-discriminant", "judgments"),
])
def test_invisible_skips_stop_after_the_next_real_action(method, category):
    contracts = execution_contracts.load_contracts()
    _insert_empty_skips(contracts[method]["steps"][0])
    initial = start(method=method)
    updated = driver.advance(initial, contracts=contracts)
    trace, = updated["trajectory"]["steps"]
    assert initial["trajectory"]["steps"] == []
    assert updated["status"] == "running", updated["diagnostics"]
    assert [call["action_id"] for call in trace["skipped_calls"]] == ["unused-1", "unused-2"]
    assert all(call["guard"] == {"constant": False} for call in trace["skipped_calls"])
    assert len(trace[category]) == 1
    assert trace["merges"] == []
    assert updated["frames"][-1]["step_index"] == 0
    assert updated["frames"][-1]["call_index"] == 3


def test_original_skip_evidence_is_kept_and_merge_remains_a_checkpoint():
    contracts = execution_contracts.load_contracts()
    state = driver.advance(start(method="method-separation"), contracts=contracts)
    prefix = deepcopy(state["fragments"])
    updated = driver.advance(state, contracts=contracts)
    trace, = updated["trajectory"]["steps"]
    assert [call["action_id"] for call in trace["skipped_calls"]] == ["inequality", "equality"]
    assert trace["skipped_calls"][0]["guard_bindings"] == {"already_separated": True}
    assert trace["skipped_calls"][0]["evidence_refs"] == ["/steps/0/calls/0"]
    assert trace["skipped_calls"][1]["guard_bindings"] == {"relation_kind": "inequality"}
    assert [item["id"] for item in trace["merges"]] == ["separation_result"]
    assert len(trace["calls"]) == 1
    assert updated["frames"][-1]["step_index"] == 0
    assert updated["frames"][-1]["call_index"] == 4
    assert updated["fragments"] == prefix
    assert state["trajectory"]["steps"][0]["skipped_calls"] == []


def test_a_skipped_call_that_publishes_a_card_stops_before_the_next_skip():
    contracts = execution_contracts.load_contracts()
    step = contracts["method-separation"]["steps"][0]
    step["calls"][1]["outputs"] = {}
    visible_skip = deepcopy(step["display_units"][0])
    visible_skip.update(id="skip-visible", after="inequality")
    # This fixture intentionally exercises a valid output-free skip display.
    # Its values were already checked by inspect; no skipped output is read.
    step["display_units"] = [step["display_units"][0], visible_skip]
    state = driver.advance(start(method="method-separation"), contracts=contracts)
    first_card = deepcopy(state["fragments"][0])
    updated = driver.advance(state, contracts=contracts)
    trace, = updated["trajectory"]["steps"]
    assert [item["action_id"] for item in trace["skipped_calls"]] == ["inequality"]
    assert trace["merges"] == []
    assert updated["frames"][-1]["call_index"] == 2
    assert [card["display_unit"] for card in updated["fragments"]] == ["separated", "skip-visible"]
    assert updated["fragments"][0] == first_card
    assert updated["fragments"][1]["source_refs"] == ["/steps/0/skipped_calls/0"]
    cards = deepcopy(updated["fragments"])
    continued = driver.advance(updated, contracts=contracts)
    assert continued["fragments"] == cards
    assert len(continued["trajectory"]["steps"][0]["skipped_calls"]) == 2
    assert len(continued["trajectory"]["steps"][0]["merges"]) == 1


@pytest.mark.parametrize("value,method", [
    (Q01, "method-separation"),
    (candidate("∀x∈[2,3]:a*x^2-a*x-1<0"), "method-interval-extremum"),
])
def test_json_restart_keeps_uncoalesced_trace_and_published_card_boundaries(value, method):
    contracts = execution_contracts.load_contracts()
    initial = start(value, method=method)
    expected = deepcopy(initial)
    for _ in range(300):
        if expected["status"] != "running":
            break
        driver._advance(expected, contracts)
    assert expected["status"] == "method_complete"
    state = initial
    for _ in range(300):
        if state["status"] != "running":
            break
        prefix = deepcopy(state["fragments"])
        state = driver.advance(json.loads(json.dumps(state)), contracts=contracts)
        assert state["fragments"][:len(prefix)] == prefix
    assert state["status"] == "method_complete", state["diagnostics"]
    assert state["trajectory"] == expected["trajectory"]
    assert state["fragments"] == expected["fragments"]
    assert state["result"] == expected["result"]


def test_coalesced_skip_budget_is_checked_and_uncommitted_trace_is_discarded(monkeypatch):
    contracts = execution_contracts.load_contracts()
    state = driver.advance(start(method="method-separation"), contracts=contracts)
    prefix = deepcopy(state)
    times = iter([0.0, 0.0, 20.0, 20.0])
    monkeypatch.setattr(driver, "perf_counter", lambda: next(times))
    failed = driver.advance(state, contracts=contracts)
    assert failed["status"] == "execution_error"
    assert failed["trajectory"]["error"]["exception_type"] == "TimeoutError"
    assert failed["trajectory"]["steps"] == prefix["trajectory"]["steps"]
    assert failed["fragments"] == prefix["fragments"]
    assert state == prefix


def _completed_step(*, cases):
    """An older checkpoint can stop after its last action, before moving on."""
    contracts = execution_contracts.load_contracts()
    value = json.loads((CORPUS / "q03/notation.gold.json").read_text()) if cases else Q01
    state = start(value, method="method-discriminant" if cases else "method-separation")
    for _ in range(50):
        frame = state["frames"][-1]
        step = contracts[frame["method"]]["steps"][frame["step_index"]]
        if frame["call_index"] == len(execution_contracts.actions(step)):
            assert bool(step.get("cases")) == cases
            return json.loads(json.dumps(state)), contracts
        driver._advance(state, contracts)
    raise AssertionError("fixture did not reach the step boundary")


def _real_actions(state):
    return sum(len(step[kind]) for step in state["trajectory"]["steps"]
               for kind in ("calls", "judgments", "merges"))


@pytest.mark.parametrize("cases", [False, True])
def test_completed_step_restart_stops_at_the_next_real_action(cases):
    state, contracts = _completed_step(cases=cases)
    before = deepcopy(state)
    updated = driver.advance(state, contracts=contracts)
    assert state == before
    assert updated["status"] == "running"
    assert _real_actions(updated) == _real_actions(before) + 1
    assert updated["fragments"][:len(before["fragments"])] == before["fragments"]
    assert len(updated["trajectory"]["steps"]) == len(before["trajectory"]["steps"]) + 1
    if cases:
        assert updated["frames"][-1]["case_path"] == ["degenerate-0"]
    else:
        assert updated["frames"][-1]["step_index"] == before["frames"][-1]["step_index"] + 1


@pytest.mark.parametrize("cases", [False, True])
def test_completed_step_budget_expiry_discards_only_uncommitted_cursor_move(cases, monkeypatch):
    state, contracts = _completed_step(cases=cases)
    before = deepcopy(state)
    times = iter([0.0, 0.0, 20.0, 20.0])
    monkeypatch.setattr(driver, "perf_counter", lambda: next(times))
    failed = driver.advance(state, contracts=contracts)
    assert failed["status"] == "execution_error"
    assert failed["trajectory"]["error"]["exception_type"] == "TimeoutError"
    assert failed["trajectory"]["steps"] == before["trajectory"]["steps"]
    assert failed["fragments"] == before["fragments"]
    assert failed["frames"] == before["frames"]
    assert state == before
