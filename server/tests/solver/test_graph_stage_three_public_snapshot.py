"""Browser projections keep graph evidence, never resumable execution payloads."""

import json
from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator
from test_graph_stage_three_events import (
    IDENTITY,
    TARGET,
    checkpoint,
    finish,
    fragment,
    operation,
    qa_chunk,
    store_with_step,
)

from shuxueshuo_server.graph_lesson.stage_three.contracts import ROOT
from shuxueshuo_server.graph_lesson.stage_three.events import (
    CursorExpired,
    EventStore,
    math_step_hash,
)
from shuxueshuo_server.graph_lesson.stage_three.handoff import (
    attach_qa,
    invalidate_goal,
)
from shuxueshuo_server.graph_lesson.stage_three.public_snapshot import (
    project_snapshot,
    source_evidence,
)
from shuxueshuo_server.graph_lesson.stage_three.revision_manifest import manifest_ref


def rich_store(tmp_path):
    store = EventStore(tmp_path, IDENTITY, create=True)
    cp, card = checkpoint(), fragment()
    card["source_refs"] = ["/steps/3/calls/1"]
    card["math_step_sha256"] = math_step_hash(card, IDENTITY["revisions"])
    cp["driver_state"].update(
        input_values={"private_input": "internal-only"}, fragments=[deepcopy(card)],
        solve_timing=[{"large_private_log": "x" * 100_000}],
        trajectory={"revisions": deepcopy(IDENTITY["revisions"]), "steps": [{
            "seq": 4, "method": "method-interval-extremum", "step": "select", "case_path": ["positive"],
            "judgments": [{"private_expression": "not-browser-data"}],
            "calls": [
                {"public_ref": None, "inputs": {"private": "hidden"}, "postconditions": []},
                {"public_ref": "quadratic-interval-extremum", "rule_ref": "rule-interval-skill",
                 "branch": "quadratic", "case_path": ["positive"],
                 "used_basis": ["quadratic-interval-extremum"], "outputs": {"private": "hidden"},
                 "postconditions": [{"kind": "certificate", "passed": True, "proof": "x" * 10_000}]},
            ],
        }], "finalization": [{"processing": "private"}, {}, {
            "capability": "endpoint_check", "public_ref": None,
            "used_basis": ["function-range-extrema#attainability"],
            "postconditions": [{"kind": "endpoint", "passed": True, "proof": "private"}],
        }]},
    )
    store.commit_route(cp, commit_id="first", math_steps=[card], events=[operation()])
    return store, card


def test_public_snapshot_has_no_execution_checkpoint_or_duplicate_cards(tmp_path):
    store, card = rich_store(tmp_path)
    public = store.snapshot()
    schema = json.loads((ROOT / "internal/schemas/graph-stage-three-snapshot-v2.schema.json").read_text())
    Draft202012Validator(schema).validate(public)
    assert public["contract"] == "graph-stage-three-snapshot/v2"
    assert public["revisions_ref"] == manifest_ref(IDENTITY["revisions"])
    assert "revisions" not in public
    assert public["math_steps"] == [card]  # Published legacy cards retain their original hash/content.
    assert set(public["checkpoints"][0]) == {"target_ref", "route_id", "status", "phase", "commit_id", "last_seq"}
    wire = json.dumps(public)
    for private in ("driver_state", "bindings", "input_values", "fragments", "solve_timing", "private", "proof"):
        assert private not in wire
    assert len(wire) < len(json.dumps(store.internal_snapshot())) // 5


def test_projection_keeps_source_positions_and_real_rule_path(tmp_path):
    store, _ = rich_store(tmp_path)
    trajectory = store.snapshot()["trajectories"][0]
    row = trajectory["steps"][0]
    assert row["seq"] == 4 and row["case_path"] == ["positive"]
    assert row["calls"][0] == {"public_ref": None, "postconditions": []}
    assert row["calls"][1] == {
        "public_ref": "quadratic-interval-extremum", "rule_ref": "rule-interval-skill", "branch": "quadratic",
        "case_path": ["positive"], "used_basis": ["quadratic-interval-extremum"], "postconditions": [{"passed": True}],
    }
    assert [record["index"] for record in trajectory["finalization"]] == [0, 1, 2]
    assert trajectory["finalization"][2]["record"]["postconditions"] == [{"passed": True}]
    assert trajectory["finalization"][0]["record"] == {}


@pytest.mark.parametrize("checks", [[], [{}], [{"passed": False}], [{"passed": "true"}], [{"passed": True}, {}]])
def test_projection_never_promotes_missing_or_unproved_local_checks(checks):
    projected = source_evidence({"postconditions": checks})
    assert projected["postconditions"] == checks
    assert not projected["postconditions"] or not all(check.get("passed") is True for check in projected["postconditions"])


def test_projection_does_not_mutate_internal_state_and_export_stays_complete(tmp_path):
    store, _ = rich_store(tmp_path)
    full = store.internal_snapshot()
    before = deepcopy(full)
    public = project_snapshot(full)
    public["trajectories"][0]["steps"][0]["calls"][1]["used_basis"].append("changed")
    assert full == before
    exported = store.export()
    assert exported == before
    assert json.loads((tmp_path / "checkpoint.json").read_text()) == before
    assert exported["checkpoints"][0]["driver_state"]["input_values"] == {"private_input": "internal-only"}
    assert store.checkpoint(TARGET, "discriminant")["driver_state"] == before["checkpoints"][0]["driver_state"]


def test_public_watermark_and_projection_are_one_read_snapshot(tmp_path, monkeypatch):
    store, first = rich_store(tmp_path)
    writer = EventStore(tmp_path, IDENTITY)
    watermark = store._watermark
    changed = False

    def concurrent_commit(db):
        nonlocal changed
        value = watermark(db)
        if not changed:
            changed = True
            writer.prune_events(2)
            writer.commit_route(checkpoint(position=2), commit_id="second", math_steps=[fragment(ordinal=2)])
        return value

    monkeypatch.setattr(store, "_watermark", concurrent_commit)
    snapshot = store.snapshot()
    assert changed and snapshot["last_seq"] == 2 and snapshot["minimum_seq"] == 1
    assert snapshot["math_steps"] == [first]
    assert snapshot["checkpoints"][0]["last_seq"] == 2
    current = writer.snapshot()
    assert current["last_seq"] == 3 and current["minimum_seq"] == 3
    assert len(current["math_steps"]) == 2
    with pytest.raises(CursorExpired):
        writer.events(0)


def test_conflict_snapshot_revokes_handoff_and_preserves_committed_math(tmp_path):
    store, card = store_with_step(tmp_path)
    finished = finish(store)
    task = finished["handoff"]
    attach_qa(store, qa_chunk(card, task), commit_id="qa")
    before = store.snapshot()
    invalidate_goal(store, TARGET, status="conflict", reason="route_conflict", commit_id="conflict")
    after = store.snapshot()
    assert after["math_steps"] == before["math_steps"]
    assert after["last_seq"] > before["last_seq"]
    assert after["goals"][TARGET]["available"] is False
    assert after["handoffs"][0]["available"] is False
    assert after["handoffs"][0]["status"] == "cancelled"
    assert "driver_state" not in json.dumps(after)
