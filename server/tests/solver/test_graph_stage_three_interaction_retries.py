"""Repeated scheduling failures terminate only pending interaction decisions."""

from copy import deepcopy

import pytest

from shuxueshuo_server.graph_lesson.stage_three import interaction, interaction_jobs
from shuxueshuo_server.graph_lesson.stage_three.budget import BudgetLedger
from shuxueshuo_server.graph_lesson.stage_three.events import EventStore
from tests.solver.test_graph_stage_three_events import fragment
from tests.solver.test_graph_stage_three_interaction_scheduler import _store

TARGET, ROUTE = "/root/goals/0", "discriminant"


def _math(durable):
    snapshot = durable.internal_snapshot()
    return {key: snapshot[key] for key in ("math_steps", "checkpoints", "goals", "handoffs")}


def _pending(durable):
    return [{key: row[key] for key in ("step_id", "math_step_sha256")}
            for row in durable.interaction_states(TARGET, ROUTE) if row["status"] == "pending"]


@pytest.mark.parametrize("damage", ["missing", "duplicate", "hash", "planning", "result", "budget"])
def test_three_failed_invocations_resolve_bad_input_or_output_from_stored_card_identity(tmp_path, damage):
    durable = _store(tmp_path, budget={"group_seconds": 5.0, "route_seconds": 30.0})
    cp = durable.checkpoint(TARGET, ROUTE)
    seed = deepcopy(cp["driver_state"]["interaction_seeds"][0])
    if damage == "missing":
        cp["driver_state"]["interaction_seeds"] = []
    elif damage == "duplicate":
        cp["driver_state"]["interaction_seeds"].append(deepcopy(seed))
    elif damage == "hash":
        cp["driver_state"]["interaction_seeds"][0]["math_step_sha256"] = "0" * 64
    elif damage == "planning":
        cp["driver_state"]["interaction_seeds"][0].pop("display_unit")
    elif damage == "budget":
        BudgetLedger(durable).configure(TARGET, ROUTE + "#interaction", "interaction", 1.2)
    durable.commit_route(cp, commit_id="damaged-input")
    original_math = _math(durable)
    for count in (1, 2, 3):
        # Reopen SQLite, just as a new process would after a student resumes.
        durable = EventStore(tmp_path, durable.identity)
        scheduler = interaction_jobs.InteractionScheduler(durable)
        if damage == "result":
            broken = interaction.readonly_chunk([seed], scheduler.settings["revision"], "compile_error")
            broken["interaction_sha256"] = "0" * 64
            scheduler._call = lambda *args, result=broken: {"chunk": result, "diagnostics": []}
        try:
            assert scheduler.step() == (1 if count == 3 else 0)
            assert len(scheduler.errors) == 1
            failure = durable.interaction_failure(TARGET, ROUTE)
            assert failure["count"] == count and failure["disabled"] is (count == 3)
            assert scheduler.step() == 0
            assert durable.interaction_failure(TARGET, ROUTE) == failure, "one invocation counts at most once"
        finally:
            scheduler.close()
        assert _math(durable) == original_math
        assert durable.has_pending_interactions() is (count < 3)
    chunk = durable.snapshot()["interactions"][0]
    assert chunk["status"] == "readonly" and chunk["reason"] == "scheduler_error"
    assert chunk["steps"] == [{"step_id": seed["step_id"], "math_step_sha256": seed["math_step_sha256"]}]
    assert interaction_jobs.run_pending(durable) == (0, [])


def test_busy_lease_never_spends_the_failure_allowance(tmp_path):
    durable = _store(tmp_path)
    with BudgetLedger(durable).route_lease(TARGET, ROUTE + "#interaction"):
        for _ in range(5):
            assert interaction_jobs.run_pending(durable) == (0, [])
    assert durable.interaction_failure(TARGET, ROUTE)["count"] == 0
    assert durable.has_pending_interactions()


def test_successful_progress_resets_the_persisted_consecutive_failure_count(tmp_path):
    durable = _store(tmp_path)
    seed = durable.checkpoint(TARGET, ROUTE)["driver_state"]["interaction_seeds"][0]
    for number in (1, 2):
        durable.record_interaction_failure(TARGET, ROUTE, {"message": "temporary"},
                                           pending_steps=_pending(durable), attempt_id=str(number))
    scheduler = interaction_jobs.InteractionScheduler(durable)
    chunk = interaction.readonly_chunk([seed], scheduler.settings["revision"], "compile_error")
    scheduler._call = lambda *args: {"chunk": chunk, "diagnostics": []}
    try:
        assert scheduler.step() == 1 and not scheduler.errors
    finally:
        scheduler.close()
    assert durable.interaction_failure(TARGET, ROUTE)["count"] == 0
    assert durable.interaction_failure(TARGET, ROUTE)["disabled"] is False


def test_merge_wait_is_not_a_successful_retry_or_a_failure(tmp_path):
    durable = _store(tmp_path)
    cp = durable.checkpoint(TARGET, ROUTE)
    cp["driver_state"]["interaction_seeds"][0]["display_unit"] = "boundary"
    durable.commit_route(cp, commit_id="merge-prefix")
    durable.record_interaction_failure(TARGET, ROUTE, {"message": "temporary"},
                                       pending_steps=_pending(durable), attempt_id="old")
    scheduler = interaction_jobs.InteractionScheduler(durable)
    try:
        assert scheduler.step() == 0 and not scheduler.errors
        assert durable.interaction_failure(TARGET, ROUTE)["count"] == 1
        assert durable.has_pending_interactions()
    finally:
        scheduler.close()


def test_late_failure_does_not_disable_new_cards_after_the_failed_work_was_resolved(tmp_path, monkeypatch):
    durable = _store(tmp_path)
    for number in (1, 2):
        durable.record_interaction_failure(TARGET, ROUTE, {"message": "temporary"},
                                           pending_steps=_pending(durable), attempt_id=str(number))
    scheduler = interaction_jobs.InteractionScheduler(durable)

    def competing_success_then_failure(target, route, checkpoint, rows):
        seed = checkpoint["driver_state"]["interaction_seeds"][0]
        durable.commit_interaction(interaction.readonly_chunk([seed], scheduler.settings["revision"], "compile_error"))
        card = fragment(ordinal=2)
        checkpoint["driver_state"]["interaction_seeds"].append({
            **seed, **{key: card[key] for key in ("step_id", "ordinal", "math_step_sha256")},
        })
        durable.commit_route(checkpoint, commit_id="new-card", math_steps=[card])
        raise ValueError("late failure processing the old card")

    monkeypatch.setattr(scheduler, "_route", competing_success_then_failure)
    try:
        assert scheduler.step() == 0 and len(scheduler.errors) == 1
        assert durable.interaction_failure(TARGET, ROUTE)["count"] == 2
        assert not durable.interaction_failure(TARGET, ROUTE)["disabled"]
        assert [row["status"] for row in durable.interaction_states()] == ["readonly", "pending"]
    finally:
        scheduler.close()
