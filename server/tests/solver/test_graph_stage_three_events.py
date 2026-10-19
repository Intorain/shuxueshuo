"""Atomic recovery, stable identities and math/QA publication boundaries."""

import json
from copy import deepcopy

import pytest
from jsonschema import ValidationError

from shuxueshuo_server.graph_lesson.stage_three.checkpoint import make_checkpoint
from shuxueshuo_server.graph_lesson.stage_three.events import (
    CursorExpired,
    EventStore,
    math_step_hash,
)
from shuxueshuo_server.graph_lesson.stage_three.handoff import (
    attach_qa,
    complete_route,
    enrichment_status,
    invalidate_goal,
)

IDENTITY = {"run_id": "run-01", "lesson_version": "lesson-01", "input_sha256": "a" * 64,
            "revisions": {"methods": "b" * 64, "presentation": "c" * 64}}
TARGET = "/root/goals/0"


def checkpoint(target=TARGET, *, position=1, status="running"):
    return make_checkpoint(IDENTITY, target, "discriminant", status=status,
                           driver_state={"position": position, "bindings": {"coefficient": "1"}},
                           frames=[{"method": "method-discriminant", "step_index": position,
                                    "call_index": 0, "bindings": {"coefficient": "1"}, "case_path": []}],
                           compute_seconds={"solve": 0.25, "verification": 0}, next_instance=position)


def fragment(target=TARGET, *, ordinal=1):
    step = {"contract": "graph-math-step/v1", "run_id": IDENTITY["run_id"],
            "lesson_version": IDENTITY["lesson_version"], "revisions": deepcopy(IDENTITY["revisions"]),
            "target_ref": target, "route_id": "discriminant", "step_id": f"step-{ordinal}", "ordinal": ordinal,
            "method_ref": "method-discriminant#conditions", "source_refs": ["/root/facts/0"], "case_path": [],
            "title": "二次项系数", "before": [{"expression": "x^2+a", "display": "x^2+a"}],
            "after": [{"expression": "1>0", "display": "1>0"}], "explanation": "开口向上。",
            "premise_refs": ["/root/facts/0"], "used_basis": ["skill-quadratic-sign"], "local_check": "passed"}
    step["math_step_sha256"] = math_step_hash(step, IDENTITY["revisions"])
    return step


def operation(target=TARGET):
    return {"type": "solver.step_completed", "target_ref": target, "route_id": "discriminant",
            "payload": {"call_id": "coefficient", "outputs": {"coefficient": "1"}, "local_check": "passed"}}


def store_with_step(tmp_path, target=TARGET):
    store = EventStore(tmp_path, IDENTITY, create=True)
    step = fragment(target)
    store.commit_route(checkpoint(target), commit_id="first", math_steps=[step], events=[operation(target)])
    return store, step


def finish(store, target=TARGET, *, commit_id="finish", consistency="consistent"):
    return complete_route(store, checkpoint(target, position=2, status="verified"),
                          route={"status": "verified", "target_ref": target, "route_id": "discriminant"},
                          verification={"status": "verified", "proof": "exact_partition"},
                          feasible_set="Interval(0,oo)", answer={"kind": "find_range", "status": "set", "set": "Interval(0,oo)"},
                          commit_id=commit_id, consistency=consistency)


def qa_chunk(step, task):
    return {key: step[key] for key in ("lesson_version", "run_id", "target_ref", "route_id", "step_id", "math_step_sha256")} | {
        "verified_route_sha256": task["verified_route_sha256"], "qa": {"questions": ["为什么开口向上？"], "feedback": "二次项系数为正。"},
    }


def test_running_route_already_exposes_committed_math_and_exact_checkpoint(tmp_path):
    store, step = store_with_step(tmp_path)
    snapshot = store.snapshot()
    assert snapshot["last_seq"] == 2
    assert snapshot["math_steps"] == [step]
    assert not snapshot["handoffs"] and not snapshot["goals"]
    saved = store.checkpoint(TARGET, "discriminant")
    assert saved["status"] == "running" and saved["driver_state"]["position"] == 1
    assert saved["frames"][0]["bindings"] == {"coefficient": "1"}
    assert saved["last_seq"] == 2
    assert [event["type"] for event in store.events()] == ["solver.step_completed", "lesson.chunk_ready"]
    assert store.events(1)[0]["payload"]["chunk"] == step
    store.export()
    assert json.loads((tmp_path / "checkpoint.json").read_text())["last_seq"] == 2
    assert len((tmp_path / "events.jsonl").read_text().splitlines()) == 2


@pytest.mark.parametrize("failure_point", ["before", "after"])
def test_interrupt_around_commit_resumes_without_duplicate_steps_or_events(tmp_path, failure_point):
    store = EventStore(tmp_path, IDENTITY, create=True)
    cp, step = checkpoint(), fragment()

    def interrupted():
        # A concurrent reader cannot see an uncommitted calculation or fragment.
        if failure_point == "before":
            assert not store.events()
            assert store.checkpoint(TARGET, "discriminant") is None
        raise RuntimeError("simulated process interruption")

    hooks = {f"{failure_point}_commit": interrupted}
    with pytest.raises(RuntimeError, match="simulated"):
        store.commit_route(cp, commit_id="first", math_steps=[step], events=[operation()], **hooks)
    reopened = EventStore(tmp_path, IDENTITY)
    assert len(reopened.events()) == (0 if failure_point == "before" else 2)
    first = reopened.commit_route(cp, commit_id="first", math_steps=[step], events=[operation()])
    again = reopened.commit_route(cp, commit_id="first", math_steps=[step], events=[operation()])
    assert first == again
    assert len(reopened.events()) == 2 and len(reopened.snapshot()["math_steps"]) == 1
    assert reopened.checkpoint(TARGET, "discriminant")["driver_state"] == cp["driver_state"]


@pytest.mark.parametrize("field", ["run_id", "lesson_version", "input_sha256", "revisions"])
def test_resume_rejects_every_identity_or_implementation_change(tmp_path, field):
    store_with_step(tmp_path)
    changed = deepcopy(IDENTITY)
    if field == "revisions":
        changed[field]["presentation"] = "d" * 64
    else:
        changed[field] = "d" * 64
    with pytest.raises(ValueError, match="identity_mismatch"):
        EventStore(tmp_path, changed)


def test_commit_id_cannot_be_reused_for_different_output(tmp_path):
    store, step = store_with_step(tmp_path)
    with pytest.raises(ValueError, match="commit_reuse_mismatch"):
        store.commit_route(checkpoint(position=2), commit_id="first", math_steps=[step], events=[operation()])
    assert store.checkpoint(TARGET, "discriminant")["next_instance"] == 1


@pytest.mark.parametrize("change", ["formula", "hash", "ordinal", "local_check", "scope"])
def test_bad_math_fragment_rolls_back_entire_calculation(tmp_path, change):
    store, step = store_with_step(tmp_path)
    bad = fragment(ordinal=2)
    if change == "formula":
        bad["step_id"], bad["ordinal"] = step["step_id"], step["ordinal"]
        bad["after"][0]["expression"] = "1<0"
        bad["math_step_sha256"] = math_step_hash(bad, IDENTITY["revisions"])
    elif change == "hash":
        bad["math_step_sha256"] = "f" * 64
    elif change == "ordinal":
        bad["ordinal"] = 4
        bad["math_step_sha256"] = math_step_hash(bad, IDENTITY["revisions"])
    elif change == "local_check":
        bad["local_check"] = "failed"
    else:
        bad["target_ref"] = "/root/children/0/goals/0"
    with pytest.raises((ValueError, ValidationError)):
        store.commit_route(checkpoint(position=2), commit_id="second", math_steps=[bad], events=[operation()])
    assert len(store.events()) == 2
    assert store.checkpoint(TARGET, "discriminant")["driver_state"]["position"] == 1


def test_target_namespace_keeps_repeated_route_and_step_names_separate(tmp_path):
    store, first = store_with_step(tmp_path)
    target = "/root/children/0/goals/0"
    second = fragment(target)
    store.commit_route(checkpoint(target), commit_id="sibling", math_steps=[second])
    assert {step["target_ref"] for step in store.snapshot()["math_steps"]} == {TARGET, target}
    assert first["math_step_sha256"] != second["math_step_sha256"]
    assert store.checkpoint(target, "discriminant")["math_steps"][0]["step_id"] == first["step_id"]


def test_expired_cursor_requires_snapshot_without_losing_checkpoint(tmp_path):
    store, step = store_with_step(tmp_path)
    store.prune_events(1)
    with pytest.raises(CursorExpired) as failure:
        store.events(0)
    assert failure.value.minimum_seq == 2
    assert store.snapshot()["math_steps"] == [step]
    assert store.snapshot()["last_seq"] == 2
    assert store.events(1)[0]["seq"] == 2
    with pytest.raises(ValueError, match="future_cursor"):
        store.events(3)


@pytest.mark.parametrize("reader", ["export", "snapshot_with_events"])
def test_snapshot_and_events_stay_consistent_during_retention_and_new_commits(tmp_path, monkeypatch, reader):
    store, first = store_with_step(tmp_path)
    original_events = store.events()
    writer = EventStore(tmp_path, IDENTITY)
    watermark = store._watermark
    interrupted = False

    def write_after_read_snapshot_begins(db):
        nonlocal interrupted
        value = watermark(db)
        if not interrupted:
            interrupted = True
            # A second connection commits while export still holds its old
            # read snapshot. Its old minimum cursor is no longer public.
            writer.prune_events(2)
            writer.commit_route(checkpoint(position=2), commit_id="second",
                                math_steps=[fragment(ordinal=2)], events=[operation()])
        return value

    monkeypatch.setattr(store, "_watermark", write_after_read_snapshot_begins)
    if reader == "export":
        exported = store.export()
        assert json.loads((tmp_path / "checkpoint.json").read_text()) == exported
        events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    else:
        exported, events = store.snapshot_with_events()
    assert interrupted
    assert exported["minimum_seq"] == 1 and exported["last_seq"] == 2
    assert exported["math_steps"] == [first]
    assert events == original_events

    current = writer.snapshot()
    assert current["minimum_seq"] == 3 and current["last_seq"] == 4
    assert len(current["math_steps"]) == 2
    with pytest.raises(CursorExpired) as failure:
        store.events(0)
    assert failure.value.minimum_seq == 3
    assert [event["seq"] for event in store.events(2)] == [3, 4]


def test_selection_snapshot_survives_retention_and_never_reads_uncommitted_choices(tmp_path):
    store, step = store_with_step(tmp_path)
    first = {"target_ref": TARGET, "kind": "D3", "chunk": {"id": "D3", "title": "选择方法"}}
    second = {"target_ref": "/root/children/0/goals/0", "kind": "D4",
              "chunk": {"id": "D4", "options": [{"route_id": "discriminant"}]}}

    def publish(chunk, commit_id, **hooks):
        return store.commit_events([{"type": "lesson.chunk_ready", "target_ref": chunk["target_ref"],
                                     "route_id": None, "payload": {"kind": chunk["kind"], "chunk": chunk["chunk"]}}],
                                   commit_id=commit_id, **hooks)

    publish(first, "first-selection")
    def before_commit():
        before = store.snapshot()
        assert before["selection_chunks"] == [first]
        assert before["last_seq"] == 3

    publish(second, "second-selection", before_commit=before_commit)
    store.prune_events(4)
    with pytest.raises(CursorExpired):
        store.events(0)
    snapshot = EventStore(tmp_path, IDENTITY).snapshot()
    assert snapshot["selection_chunks"] == [first, second]
    assert snapshot["last_seq"] == 4
    assert snapshot["math_steps"] == [step]


def test_verified_route_completion_and_handoff_are_one_idempotent_commit(tmp_path):
    store, step = store_with_step(tmp_path)
    result = finish(store)
    assert result == finish(store)
    assert result["checkpoint"]["status"] == "verified"
    assert result["handoff"]["math_steps"] == [{key: step[key] for key in ("step_id", "ordinal", "math_step_sha256")}]
    assert store.snapshot()["goals"][TARGET]["status"] == "solved"
    assert [event["payload"].get("kind") for event in result["events"]].count("route_completion") == 1
    assert result["checkpoint"]["last_seq"] == store.snapshot()["last_seq"]


def test_qa_is_appended_without_changing_math_or_checkpoint(tmp_path):
    store, step = store_with_step(tmp_path)
    task = finish(store)["handoff"]
    before = store.checkpoint(TARGET, "discriminant")
    chunk = qa_chunk(step, task)
    saved = attach_qa(store, chunk, commit_id="qa-step-1")
    assert saved == attach_qa(store, chunk, commit_id="qa-step-1")
    enrichment_status(store, TARGET, "discriminant", status="failed", commit_id="qa-failure", diagnostic="provider_timeout")
    assert store.checkpoint(TARGET, "discriminant") == before
    assert store.snapshot()["math_steps"] == [step]
    assert store.snapshot()["goals"][TARGET]["status"] == "solved"
    assert store.snapshot()["handoffs"][0]["status"] == "failed"


def test_enrichment_cannot_claim_completion_before_every_step_has_qa(tmp_path):
    store, step = store_with_step(tmp_path)
    task = finish(store)["handoff"]
    with pytest.raises(ValueError, match="incomplete_qa"):
        enrichment_status(store, TARGET, "discriminant", status="completed", commit_id="too-early")
    attach_qa(store, qa_chunk(step, task), commit_id="qa")
    enrichment_status(store, TARGET, "discriminant", status="completed", commit_id="qa-complete")
    assert store.snapshot()["handoffs"][0]["status"] == "completed"


@pytest.mark.parametrize("field", ["run_id", "lesson_version", "target_ref", "step_id", "math_step_sha256", "verified_route_sha256"])
def test_qa_wrong_identity_or_hash_cannot_attach(tmp_path, field):
    store, step = store_with_step(tmp_path)
    task = finish(store)["handoff"]
    chunk = qa_chunk(step, task)
    chunk[field] = "f" * 64 if field.endswith("sha256") else "different"
    before = store.snapshot()["last_seq"]
    with pytest.raises(ValueError):
        attach_qa(store, chunk, commit_id="wrong-qa")
    assert store.snapshot()["last_seq"] == before
    assert not store.snapshot()["qa"]


@pytest.mark.parametrize("status", ["conflict", "no_verified_route"])
def test_late_goal_failure_cancels_handoff_and_rejects_inflight_qa(tmp_path, status):
    store, step = store_with_step(tmp_path)
    task = finish(store)["handoff"]
    invalidate_goal(store, TARGET, status=status, reason="route_consistency_undecidable", commit_id="unavailable")
    snapshot = store.snapshot()
    assert snapshot["handoffs"][0]["status"] == "cancelled"
    assert not snapshot["handoffs"][0]["available"]
    assert snapshot["checkpoints"][0]["status"] == "verified"
    assert snapshot["math_steps"] == [step]
    with pytest.raises(ValueError, match="goal_unavailable"):
        attach_qa(store, qa_chunk(step, task), commit_id="late-qa")
    with pytest.raises(ValueError, match="invalid_goal_reactivation"):
        store.commit_events([{"type": "lesson.goal_status", "target_ref": TARGET, "route_id": None,
                              "payload": {"status": "running"}}], commit_id="reset-goal")


@pytest.mark.parametrize("consistency", ["conflict", "unknown"])
def test_inconsistent_verified_route_keeps_evidence_without_publication(tmp_path, consistency):
    store, step = store_with_step(tmp_path)
    finished = finish(store, consistency=consistency)
    assert finished["checkpoint"]["status"] == "verified"
    assert finished["handoff"] is None
    assert store.snapshot()["math_steps"] == [step]
    assert not any(event["payload"].get("kind") == "route_completion" for event in store.events())
