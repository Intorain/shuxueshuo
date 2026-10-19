"""Whole-step guards remain explicit in checkpoints, reports, and event replay."""

import json
from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator

from shuxueshuo_server.graph_lesson.stage_three import (
    driver,
    execution_contracts,
    runner,
)
from tests.solver.test_graph_stage_three_case_driver import Q03
from tests.solver.test_graph_stage_three_contracts import upstream
from tests.solver.test_graph_stage_three_execution import Interrupted, events, store
from tests.solver.test_graph_stage_three_methods import ROOT, finish, start
from tests.solver.test_graph_stage_three_trace_stream import _replay_and_compare


def _skipped_steps(state):
    return [step for step in state["trajectory"]["steps"] if "step_skip" in step]


def test_degenerate_case_records_each_skipped_step_with_resolvable_guard_evidence():
    state = finish(start(Q03))
    assert state["status"] == "method_complete", state["diagnostics"]
    steps = state["trajectory"]["steps"]
    skipped = _skipped_steps(state)
    assert [(step["case_path"], step["step"]) for step in skipped] == [
        (["degenerate-0"], "normalize"),
        (["degenerate-0"], "conditions"),
        (["degenerate-1"], "normalize"),
        (["degenerate-1"], "conditions"),
    ]
    assert [step["seq"] for step in steps] == list(range(1, len(steps) + 1))
    calls = [call for step in steps for call in step["calls"]]
    # Parent rows can receive calls after a child returns; global call IDs still
    # remain unique and contiguous, regardless of the enclosing row order.
    assert sorted(call["seq"] for call in calls) == list(range(1, len(calls) + 1))
    for step in skipped:
        assert all(step[category] == [] for category in ("calls", "skipped_calls", "judgments", "merges"))
        skip = step["step_skip"]
        assert skip["reason"] == "guard_false"
        assert skip["case_path"] == step["case_path"]
        assert skip["guard"] == {"ref": "case.kind", "equals": "nondegenerate"}
        descriptor = skip["guard_bindings"]["case"]
        assert descriptor["kind"] == "degenerate"
        assert descriptor["id"] == step["case_path"][-1]
        assert skip["source_refs"]
        for reference in skip["source_refs"]:
            _, _, index, category, position = reference.split("/")
            assert int(index) < step["seq"] - 1
            source = steps[int(index)][category][int(position)]
            assert source["evidence"]["has_degenerate"] is True
            assert descriptor in source["evidence"]["cases"]
    schema = json.loads((ROOT / "internal/schemas/graph-stage-three-route-v1.schema.json").read_text())
    Draft202012Validator(schema).validate(state["trajectory"])
    malformed = deepcopy(state["trajectory"])
    del next(step for step in malformed["steps"] if "step_skip" in step)["step_skip"]["source_refs"]
    assert list(Draft202012Validator(schema).iter_errors(malformed))


def test_constant_step_guard_records_the_reason_without_fabricating_evidence(monkeypatch):
    contracts = execution_contracts.load_contracts()
    contracts["method-discriminant"]["steps"][0]["guard"] = {"constant": False}
    monkeypatch.setattr(execution_contracts, "load_contracts", lambda: deepcopy(contracts))
    initial = start(Q03)
    skipped = driver.advance(initial)
    assert initial["trajectory"]["steps"] == []
    assert skipped["status"] == "running"
    step = _skipped_steps(skipped)[0]
    assert step["step"] == "degree"
    assert step["step_skip"] == {
        "reason": "guard_false",
        "guard": {"constant": False},
        "guard_bindings": {},
        "source_refs": [],
        "case_path": [],
    }
    assert step["calls"] == step["judgments"] == step["merges"] == []
    assert skipped["frames"][-1]["step_index"] == 1
    assert skipped["fragments"] == []


@pytest.mark.parametrize("position", ["before_commit", "after_commit"])
def test_step_skip_is_streamed_and_resume_never_duplicates_it(tmp_path, position):
    output = tmp_path / "run"
    interrupted = []

    def stop_after_skip(state, _durable):
        if not interrupted and _skipped_steps(state):
            interrupted.append(True)
            raise Interrupted()

    with pytest.raises(Interrupted):
        runner.run_sample(upstream(tmp_path, "q03"), output, milestone="2",
                          hooks={position: stop_after_skip})
    prefix = events(output)
    checkpoint = next(
        item["driver_state"] for item in store(output).snapshot()["checkpoints"]
        if item["route_id"] == "discriminant"
    )
    assert bool(_skipped_steps(checkpoint)) is (position == "after_commit")
    resumed = runner.resume_sample(output)
    assert resumed["status"] == "completed", resumed
    assert events(output)[:len(prefix)] == prefix
    delivered = _replay_and_compare(output)
    skips = [record for record in delivered if "step_skip" in record]
    assert len(skips) == 4
    assert len({(tuple(step["case_path"]), step["step"]) for step in skips}) == 4
    assert all(step["step_skip"]["source_refs"] for step in skips)
