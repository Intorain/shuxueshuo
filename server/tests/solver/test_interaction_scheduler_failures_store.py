"""Durable scheduler fallback is atomic and depends only on published card ids."""

import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest
from sqlalchemy import text

from shuxueshuo_server.graph_lesson.stage_three.events import EventStore
from tests.solver.test_graph_stage_three_events import (
    IDENTITY,
    TARGET,
    checkpoint,
    fragment,
)
from tests.solver.test_graph_stage_three_interaction_commit import _pending

ROUTE = "discriminant"
ERROR = {"exception_type": "ValueError", "message": "interaction.invalid_seed"}
EMPTY = {"count": 0, "disabled": False, "last_error": None}


def _failure(store, attempt, **options):
    pending = options.pop("pending_steps", None)
    return store.record_interaction_failure(TARGET, ROUTE, ERROR, attempt_id=attempt,
                                            pending_steps=_observed(store) if pending is None else pending, **options)


def _observed(store):
    return [{key: row[key] for key in ("step_id", "math_step_sha256")}
            for row in store.interaction_states(TARGET, ROUTE) if row["status"] == "pending"]


def _states(store):
    return [row["status"] for row in store.interaction_states(TARGET, ROUTE)]


def _second_card(store, seed):
    card = fragment(ordinal=2)
    follower = {**seed, **{key: card[key] for key in ("step_id", "ordinal", "math_step_sha256")}}
    cp = checkpoint(position=2)
    cp["driver_state"]["interaction_seeds"] = [seed, follower]
    store.commit_route(cp, commit_id="second-card", math_steps=[card])
    return card


def test_third_failed_invocation_closes_pending_cards_without_changing_mathematics(tmp_path):
    store, seed, _ = _pending(tmp_path)
    _second_card(store, seed)
    before = store.snapshot()
    assert store.interaction_failure(TARGET, ROUTE) == EMPTY
    for number in (1, 2):
        result = _failure(store, str(number))
        assert result["count"] == number and not result["disabled"] and result["resolved_count"] == 0
        assert _states(store) == ["pending", "pending"]
        assert store.snapshot()["last_seq"] == before["last_seq"]
    result = _failure(store, "3")
    assert result["count"] == 3 and result["disabled"] and result["resolved_count"] == 2
    after = store.snapshot()
    assert _states(store) == ["readonly", "readonly"]
    assert after["last_seq"] == before["last_seq"] + 2
    assert {chunk["reason"] for chunk in after["interactions"]} == {"scheduler_error"}
    assert all(chunk["parts"] == [] and len(chunk["steps"]) == 1 for chunk in after["interactions"])
    for name in ("math_steps", "checkpoints", "goals", "handoffs"):
        assert before[name] == after[name]
    assert store.interaction_failure(TARGET, ROUTE) == {"count": 3, "disabled": True, "last_error": ERROR}


def test_invocation_idempotency_survives_interleaved_attempts_and_changed_diagnostics(tmp_path):
    store, _, _ = _pending(tmp_path)
    first = _failure(store, "A")
    assert _failure(store, "B")["count"] == 2
    assert _failure(store, "A") == first
    assert store.record_interaction_failure(TARGET, ROUTE, {"message": "another failure in A"},
                                            attempt_id="A", pending_steps=_observed(store)) == first
    assert store.interaction_failure(TARGET, ROUTE)["count"] == 2
    with pytest.raises(ValueError, match="commit_reuse_mismatch"):
        _failure(store, "A", limit=9)
    assert store.interaction_failure(TARGET, ROUTE)["count"] == 2


def test_success_resets_failures_once_but_noop_success_does_not_create_commits(tmp_path):
    store, _, _ = _pending(tmp_path)
    before = store.commit_watermark()
    assert store.clear_interaction_failure(TARGET, ROUTE, attempt_id="empty") == EMPTY
    assert store.commit_watermark() == before
    _failure(store, "A")
    _failure(store, "B")
    cleared = store.clear_interaction_failure(TARGET, ROUTE, attempt_id="success")
    assert cleared["count"] == 0 and store.interaction_failure(TARGET, ROUTE) == EMPTY
    assert _failure(store, "C")["count"] == 1
    watermark = store.commit_watermark()
    assert store.clear_interaction_failure(TARGET, ROUTE, attempt_id="success") == cleared
    assert store.commit_watermark() == watermark and store.interaction_failure(TARGET, ROUTE)["count"] == 1


def test_disabled_route_never_reopens_and_future_cards_ignore_bad_seeds(tmp_path):
    store, _, _ = _pending(tmp_path)
    _failure(store, "terminal", limit=1)
    disabled = store.interaction_failure(TARGET, ROUTE)
    watermark = store.commit_watermark()
    assert store.clear_interaction_failure(TARGET, ROUTE, attempt_id="success") == disabled
    assert store.commit_watermark() == watermark
    # Future mathematical commits must not inspect these malformed seeds.
    cp = checkpoint(position=2)
    cp["driver_state"]["interaction_seeds"] = [None, {}]
    store.commit_route(cp, commit_id="later-card", math_steps=[fragment(ordinal=2)])
    assert _states(store) == ["readonly", "readonly"]
    assert {chunk["reason"] for chunk in store.snapshot()["interactions"]} == {"scheduler_error"}
    assert not store.has_pending_interactions()
    assert store.interaction_failure(TARGET, ROUTE) == disabled


def test_fallback_never_reads_or_parses_the_broken_checkpoint(tmp_path):
    store, _, _ = _pending(tmp_path)
    with store.transaction(write=True) as db:
        db.execute(text("UPDATE lesson_checkpoints SET value='broken JSON' "
                        "WHERE run_id=:run_id AND target=:target AND route=:route"),
                   {"run_id": store.identity["run_id"], "target": TARGET, "route": ROUTE})
    result = _failure(store, "terminal", limit=1)
    assert result["disabled"] and result["resolved_count"] == 1
    assert _states(store) == ["readonly"]
    assert store.events()[-1]["payload"]["chunk"]["reason"] == "scheduler_error"


def test_existing_terminal_results_are_untouched_and_stale_failures_are_ignored(tmp_path):
    store, seed, chunk = _pending(tmp_path)
    store.commit_interaction(chunk)
    ignored = _failure(store, "late-failure", limit=1)
    assert not ignored["disabled"] and ignored["count"] == ignored["resolved_count"] == 0
    assert store.interaction_failure(TARGET, ROUTE) == EMPTY
    _second_card(store, seed)
    result = _failure(store, "current-failure", limit=1)
    assert result["resolved_count"] == 1
    assert _states(store) == ["interactive", "readonly"]
    assert store.interaction(chunk["interaction_id"])["chunk"] == chunk
    before = store.snapshot()
    assert _failure(store, "later-failure")["resolved_count"] == 0
    assert store.snapshot() == before


@pytest.mark.parametrize("point", ["before", "after"])
def test_threshold_commit_crash_retries_once_without_partial_terminal_states(tmp_path, point):
    store, seed, _ = _pending(tmp_path)
    _second_card(store, seed)
    _failure(store, "first")
    _failure(store, "second")
    before = store.snapshot()
    observed = _observed(store)

    def interrupted():
        assert _states(store) == (["pending", "pending"] if point == "before" else ["readonly", "readonly"])
        raise RuntimeError("simulated interruption")

    with pytest.raises(RuntimeError, match="simulated interruption"):
        _failure(store, "third", pending_steps=observed, **{f"{point}_commit": interrupted})
    if point == "before":
        assert store.snapshot() == before
        assert store.interaction_failure(TARGET, ROUTE)["count"] == 2
    reopened = EventStore(tmp_path, IDENTITY)
    result = _failure(reopened, "third", pending_steps=observed)
    assert result == _failure(reopened, "third", pending_steps=observed)
    assert result["count"] == 3 and result["resolved_count"] == 2
    assert reopened.snapshot()["last_seq"] == before["last_seq"] + 2


def test_parallel_invocations_and_duplicate_delivery_count_each_invocation_once(tmp_path):
    store, _, _ = _pending(tmp_path)

    def record(attempt):
        return _failure(EventStore(tmp_path, IDENTITY), attempt)

    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(record, ("A", "B", "A")))
    assert results[0] == results[2]
    assert store.interaction_failure(TARGET, ROUTE)["count"] == 2 and _states(store) == ["pending"]
    assert _failure(store, "C")["resolved_count"] == 1


def test_fallback_storage_error_rolls_back_failure_count_and_all_card_results(tmp_path, monkeypatch):
    store, seed, _ = _pending(tmp_path)
    _second_card(store, seed)
    _failure(store, "first")
    _failure(store, "second")
    before = store.snapshot()
    original = store._put_interaction
    calls = []

    def interrupted(*args):
        result = original(*args)
        calls.append(result)
        if len(calls) == 2:
            raise OSError("disk failure")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(store, "_put_interaction", interrupted)
        with pytest.raises(OSError, match="disk failure"):
            _failure(store, "third")
    assert store.snapshot() == before and store.interaction_failure(TARGET, ROUTE)["count"] == 2
    assert _failure(store, "third")["resolved_count"] == 2


def test_failure_counts_are_scoped_by_target_and_route(tmp_path):
    store, _, _ = _pending(tmp_path)
    other = "/root/children/0/goals/0"
    cp, card = checkpoint(other), fragment(other)
    seed = {key: deepcopy(card[key]) for key in ("run_id", "lesson_version", "target_ref", "route_id", "step_id",
                                               "math_step_sha256", "ordinal", "case_path", "method_ref")}
    seed.update(status="ready", template="policy", display_unit="policy")
    cp["driver_state"]["interaction_seeds"] = [seed]
    store.commit_route(cp, commit_id="other-goal", math_steps=[card])
    _failure(store, "terminal", limit=1)
    assert store.interaction_failure(other, ROUTE) == EMPTY
    assert store.interaction_failure(TARGET, "another-route") == EMPTY
    assert store.interaction_states(other, ROUTE)[0]["status"] == "pending"


def test_interaction_context_preserves_checkpoint_identity_validation(tmp_path):
    store, _, _ = _pending(tmp_path)
    cp = store.checkpoint(TARGET, ROUTE)
    cp["run_id"] = "different-run"
    with store.transaction(write=True) as db:
        db.execute(text("UPDATE lesson_checkpoints SET value=:value "
                        "WHERE run_id=:run_id AND target=:target AND route=:route"),
                   {"value": json.dumps(cp), "run_id": store.identity["run_id"], "target": TARGET, "route": ROUTE})
    with pytest.raises(ValueError, match="checkpoint.identity_mismatch"):
        store.interaction_context(TARGET, ROUTE)


def test_late_error_for_a_resolved_card_cannot_disable_a_newly_published_card(tmp_path):
    store, seed, chunk = _pending(tmp_path)
    _failure(store, "first")
    _failure(store, "second")
    observed = _observed(store)
    # A failed on the old card but has not recorded its exception. B resolves
    # that card, and mathematics appends a new one before B clears the count.
    store.commit_interaction(chunk)
    _second_card(store, seed)
    before = store.snapshot()
    result = _failure(store, "late-A", pending_steps=observed)
    assert result["count"] == 2 and not result["disabled"] and result["resolved_count"] == 0
    assert _states(store) == ["interactive", "pending"]
    assert store.snapshot() == before
    store.clear_interaction_failure(TARGET, ROUTE, attempt_id="success-B")
    assert store.interaction_failure(TARGET, ROUTE) == EMPTY
    assert _states(store) == ["interactive", "pending"]


def test_observed_pending_set_binds_retries_and_a_live_observed_card_can_close_the_route(tmp_path):
    store, seed, _ = _pending(tmp_path)
    observed = _observed(store)
    first = _failure(store, "first", pending_steps=observed)
    _second_card(store, seed)
    with pytest.raises(ValueError, match="commit_reuse_mismatch"):
        _failure(store, "first")
    assert _failure(store, "first", pending_steps=observed) == first
    _failure(store, "second", pending_steps=observed)
    result = _failure(store, "third", pending_steps=observed)
    assert result["disabled"] and result["resolved_count"] == 2
    assert _states(store) == ["readonly", "readonly"]


def test_pending_observation_requires_the_current_hash_and_is_order_independent(tmp_path):
    store, seed, _ = _pending(tmp_path)
    wrong = [{**_observed(store)[0], "math_step_sha256": "0" * 64}]
    assert _failure(store, "wrong-hash", pending_steps=wrong)["count"] == 0
    _second_card(store, seed)
    observed = _observed(store)
    first = _failure(store, "first", pending_steps=observed)
    assert _failure(store, "first", pending_steps=list(reversed(observed))) == first


def test_interaction_context_reads_checkpoint_and_card_states_at_one_watermark(tmp_path, monkeypatch):
    store, seed, _ = _pending(tmp_path)
    other = EventStore(tmp_path, IDENTITY)
    original = store._checkpoint

    def concurrent_commit(db, target, route):
        result = original(db, target, route)
        _second_card(other, seed)
        return result

    with monkeypatch.context() as patch:
        patch.setattr(store, "_checkpoint", concurrent_commit)
        cp, states = store.interaction_context(TARGET, ROUTE)
    assert len(cp["driver_state"]["interaction_seeds"]) == len(states) == 1
    cp, states = store.interaction_context(TARGET, ROUTE)
    assert len(cp["driver_state"]["interaction_seeds"]) == len(states) == 2
