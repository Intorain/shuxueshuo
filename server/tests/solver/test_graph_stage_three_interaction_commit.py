"""Availability is decided atomically when a worker's interaction is committed."""

from copy import deepcopy

import pytest

from shuxueshuo_server.graph_lesson.stage_three import interaction, interaction_jobs
from shuxueshuo_server.graph_lesson.stage_three.events import EventStore
from shuxueshuo_server.graph_lesson.stage_three.handoff import invalidate_goal
from tests.solver.test_graph_stage_three_events import (
    IDENTITY,
    TARGET,
    checkpoint,
    finish,
    fragment,
)

ROUTE = "discriminant"


def _pending(tmp_path):
    store = EventStore(tmp_path, IDENTITY, create=True)
    registry = interaction.load_registry()
    revision = interaction.registry_revision(registry)
    store.enable_interactions(registry, revision=revision, engine_revision=interaction.engine_revision())
    step = fragment()
    seed = {key: deepcopy(step[key]) for key in (
        "run_id", "lesson_version", "target_ref", "route_id", "step_id", "math_step_sha256", "ordinal",
        "case_path", "method_ref",
    )}
    seed.update(template="policy", display_unit="policy", status="ready", values={}, context={})
    cp = checkpoint()
    cp["driver_state"]["interaction_seeds"] = [seed]
    store.commit_route(cp, commit_id="math", math_steps=[step])
    chunk = interaction.readonly_chunk([seed], revision, "no_rule")
    chunk.pop("reason")
    chunk.update(status="interactive", parts=[{
        "id": chunk["interaction_id"] + "#1", "title": "二次项系数", "question": "二次项系数的符号是什么？",
        "interaction": {"type": "choice", "field": "coefficient", "options": [
            {"value": "o1", "label": "$1>0$"}, {"value": "o2", "label": "$1<0$"},
        ]},
        "expected_answer": {"one_of": ["o1"]}, "feedback": {"answer": "二次项系数为正。"}, "submit_label": "确定",
    }])
    chunk["interaction_sha256"] = interaction.chunk_sha256(chunk)
    interaction.validate_chunk(chunk)
    return store, seed, chunk


def _revoke(store, status="no_verified_route"):
    invalidate_goal(store, TARGET, status=status, reason="test.revoked", commit_id="revoke")


def _fail_route(store, status="math_failed"):
    cp = deepcopy(store.checkpoint(TARGET, ROUTE))
    cp["status"] = status
    store.commit_route(cp, commit_id="route-failed")


def _math_state(store):
    snapshot = store.internal_snapshot()
    return {key: snapshot[key] for key in ("math_steps", "checkpoints", "goals", "handoffs")}


def _assert_readonly(store, original):
    snapshot = store.snapshot()
    saved = snapshot["interactions"][0]
    assert saved["status"] == "readonly" and saved["reason"] == "route_unavailable"
    assert saved["parts"] == []
    assert saved["steps"] == original["steps"]
    assert saved["interaction_id"] == original["interaction_id"]
    assert saved["interaction_sha256"] == interaction.chunk_sha256(saved)
    interaction.validate_chunk(saved)
    assert all(row["status"] == "readonly" for row in snapshot["interaction_states"])
    event = store.events()[-1]
    assert event["payload"] == {"kind": "step_interaction", "interaction_id": saved["interaction_id"],
                                "status": "readonly", "chunk": saved}
    assert snapshot["last_seq"] == event["seq"]
    assert "request_sha256" not in saved and "diagnostics" not in saved
    record = store.interaction(saved["interaction_id"])
    assert record["request_sha256"] == original["interaction_sha256"]
    assert record["diagnostics"][-1] == {"result": "readonly", "reason": "route_unavailable"}


@pytest.mark.parametrize("status", ["no_verified_route", "conflict"])
def test_revoked_goal_downgrades_late_result_in_the_state_and_event(tmp_path, status):
    store, _, chunk = _pending(tmp_path)
    original, diagnostics = deepcopy(chunk), [{"result": "compiled"}]
    _revoke(store, status)
    math = _math_state(store)
    result = store.commit_interaction(chunk, diagnostics=diagnostics)
    assert result["committed"] is True
    _assert_readonly(store, original)
    assert _math_state(store) == math
    assert chunk == original and diagnostics == [{"result": "compiled"}]


def test_revoked_goal_resolves_both_cards_of_a_merged_result_together(tmp_path):
    store, seed, chunk = _pending(tmp_path)
    second = fragment(ordinal=2)
    follower = {**seed, **{key: second[key] for key in ("step_id", "math_step_sha256", "ordinal")}}
    cp = checkpoint(position=2)
    cp["driver_state"]["interaction_seeds"] = [seed, follower]
    store.commit_route(cp, commit_id="second-card", math_steps=[second])
    merged = interaction.readonly_chunk([seed, follower], chunk["interaction_revision"], "no_rule")
    chunk.update({key: merged[key] for key in ("steps", "interaction_id")})
    chunk["parts"][0]["id"] = chunk["interaction_id"] + "#1"
    chunk["interaction_sha256"] = interaction.chunk_sha256(chunk)
    _revoke(store)
    math, watermark = _math_state(store), store.snapshot()["last_seq"]
    store.commit_interaction(chunk)
    _assert_readonly(store, chunk)
    assert _math_state(store) == math
    assert store.snapshot()["last_seq"] == watermark + 1
    assert len(store.snapshot()["interaction_states"]) == 2


@pytest.mark.parametrize("status", ["capability_gap", "math_failed", "execution_error"])
def test_failed_route_downgrades_late_result_without_changing_mathematics(tmp_path, status):
    store, _, chunk = _pending(tmp_path)
    _fail_route(store, status)
    math = _math_state(store)
    store.commit_interaction(chunk)
    _assert_readonly(store, chunk)
    assert _math_state(store) == math


@pytest.mark.parametrize("unavailable", [_revoke, _fail_route])
def test_worker_returning_after_availability_changes_commits_readonly(tmp_path, monkeypatch, unavailable):
    store, seed, chunk = _pending(tmp_path)
    calls = []

    def returned(result, durable):
        assert result == chunk
        unavailable(durable)
        calls.append(_math_state(durable))

    scheduler = interaction_jobs.InteractionScheduler(store, hooks={"interaction_returned": returned})
    monkeypatch.setattr(scheduler, "_call", lambda *_: {"chunk": chunk, "diagnostics": [{"result": "compiled"}]})
    try:
        # Execute the real dispatch/return/commit path; the worker output is fixed
        # so the race does not depend on process timing or real model calls.
        assert scheduler._compile(TARGET, ROUTE, [seed], {}, scheduler.settings["registry"],
                                  scheduler.settings["revision"]) == 1
        assert scheduler.step() == 0
    finally:
        scheduler.close()
    _assert_readonly(store, chunk)
    assert len(calls) == 1 and _math_state(store) == calls[0]


@pytest.mark.parametrize("failure_point", ["before", "after"])
def test_downgrade_rollback_or_crash_replays_the_same_request_once(tmp_path, failure_point):
    store, _, chunk = _pending(tmp_path)
    _revoke(store)
    initial = store.snapshot()

    def interrupted():
        current = store.snapshot()
        if failure_point == "before":
            assert current == initial
        else:
            _assert_readonly(store, chunk)
        raise RuntimeError("simulated interruption")

    with pytest.raises(RuntimeError, match="simulated interruption"):
        store.commit_interaction(chunk, **{f"{failure_point}_commit": interrupted})
    if failure_point == "before":
        assert store.snapshot() == initial
    reopened = EventStore(tmp_path, IDENTITY)
    result = reopened.commit_interaction(chunk)
    assert result == reopened.commit_interaction(chunk)
    _assert_readonly(reopened, chunk)
    assert reopened.snapshot()["last_seq"] == initial["last_seq"] + 1
    # Also tolerate the same worker request delivered under a new transaction
    # id, while refusing different content for the resolved interaction.
    assert reopened.commit_interaction(chunk, commit_id="redelivery")["committed"] is False
    changed = deepcopy(chunk)
    changed["parts"][0]["question"] = "另一道题？"
    changed["interaction_sha256"] = interaction.chunk_sha256(changed)
    with pytest.raises(ValueError, match="immutable_interaction"):
        reopened.commit_interaction(changed, commit_id="changed")
    assert reopened.snapshot()["last_seq"] == initial["last_seq"] + 1


@pytest.mark.parametrize("status", ["running", "verified"])
def test_available_route_accepts_interaction_and_later_revocation_cannot_rewrite_it(tmp_path, status):
    store, _, chunk = _pending(tmp_path)
    if status == "verified":
        finish(store)
    math = _math_state(store)
    result = store.commit_interaction(chunk)
    assert result["committed"] is True
    assert store.snapshot()["interactions"] == [chunk]
    assert _math_state(store) == math
    _revoke(store)
    revoked = store.snapshot()
    assert store.commit_interaction(chunk) == result
    assert store.commit_interaction(chunk, commit_id="redelivery")["committed"] is False
    assert store.snapshot() == revoked
    changed = deepcopy(chunk)
    changed.update(status="readonly", parts=[], reason="route_unavailable")
    changed["interaction_sha256"] = interaction.chunk_sha256(changed)
    with pytest.raises(ValueError, match="immutable_interaction"):
        store.commit_interaction(changed, commit_id="rewrite-success")
    assert store.snapshot() == revoked
