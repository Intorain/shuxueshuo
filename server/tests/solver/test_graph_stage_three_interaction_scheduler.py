"""Lightweight scheduling recovery with real SQLite leases and durable receipts."""

import json
import threading
from pathlib import Path

import pytest

from shuxueshuo_server.graph_lesson.stage_three import interaction, interaction_jobs
from shuxueshuo_server.graph_lesson.stage_three.budget import (
    BudgetConflict,
    BudgetLedger,
)
from shuxueshuo_server.graph_lesson.stage_three.events import EventStore
from tests.solver.test_graph_stage_three_events import (
    IDENTITY,
    TARGET,
    checkpoint,
    fragment,
)

ROUTE = "discriminant" + interaction_jobs.LEASE_SUFFIX


@pytest.fixture
def sessions(monkeypatch):
    """Only the process is replaced; lease, budgeting, receipt and commit are real."""
    runs = []

    class Session:
        def __init__(self, dispatch):
            self.dispatch = dispatch

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def run(self, payload, *, timeout_seconds, receipt_path, attempt_id):
            runs.append({"payload": payload, "timeout_seconds": timeout_seconds})
            result = {"chunk": interaction.readonly_chunk(payload["seeds"], payload["revision"], "compile_error"),
                      "diagnostics": [{"result": "readonly", "reason": "compile_error"}]}
            Path(receipt_path).write_text(json.dumps({
                "schema_version": "bounded-calculation-receipt/v1", "attempt_id": attempt_id,
                "elapsed_seconds": 0.001, "status": "returned", "result": result,
            }))

    monkeypatch.setattr(interaction_jobs.bounded, "JsonCalculationSession", Session)
    return runs


def _store(directory, *, budget=None):
    registry = interaction.load_registry()
    durable = EventStore(directory, IDENTITY, create=True)
    durable.enable_interactions(registry, revision=interaction.registry_revision(registry),
                                engine_revision=interaction.engine_revision(), budget=budget)
    card = fragment()
    seed = {key: card[key] for key in ("run_id", "lesson_version", "target_ref", "route_id", "step_id",
                                      "math_step_sha256", "ordinal", "method_ref", "case_path")}
    seed.update(contract="graph-interaction-seed/v1", status="ready", template="policy", display_unit="policy",
                values={}, context={})
    cp = checkpoint()
    cp["driver_state"]["interaction_seeds"] = [seed]
    durable.commit_route(cp, commit_id="first", math_steps=[card])
    return durable


def _statuses(durable):
    return [row["status"] for row in durable.interaction_states()]


def test_busy_lease_is_retried_after_release_without_recreating_scheduler(tmp_path, sessions):
    durable = _store(tmp_path)
    scheduler = interaction_jobs.InteractionScheduler(durable)
    try:
        with BudgetLedger(durable).route_lease(TARGET, ROUTE):
            assert scheduler.step() == 0
            assert scheduler._busy == {(TARGET, "discriminant")}
            assert scheduler._skipped == set() and scheduler.errors == []
            assert _statuses(durable) == ["pending"] and sessions == []
        assert scheduler.step() == 1
        assert not scheduler._busy and not scheduler.errors
        assert _statuses(durable) == ["readonly"] and len(sessions) == 1
        assert scheduler.step() == 0 and len(sessions) == 1
    finally:
        scheduler.close()


def test_finish_remains_running_during_contention_and_drains_after_release(tmp_path, sessions, monkeypatch):
    durable = _store(tmp_path)
    scheduler = interaction_jobs.InteractionScheduler(durable)
    attempted = threading.Event()
    original = scheduler._route

    def observe(*args):
        try:
            return original(*args)
        except BudgetConflict:
            attempted.set()
            raise

    monkeypatch.setattr(scheduler, "_route", observe)
    try:
        with BudgetLedger(durable).route_lease(TARGET, ROUTE):
            scheduler.start(poll_seconds=0.01)
            assert attempted.wait(2)
            assert scheduler.finish(timeout=0.02) is False
            assert scheduler._thread.is_alive() and _statuses(durable) == ["pending"]
        assert scheduler.finish(timeout=2) is True
        assert _statuses(durable) == ["readonly"] and len(sessions) == 1
        assert scheduler.errors == [] and not scheduler._calculators
    finally:
        scheduler.stop()


def test_finish_drains_normal_work_and_releases_the_route_lease(tmp_path, sessions):
    durable = _store(tmp_path)
    scheduler = interaction_jobs.InteractionScheduler(durable).start(poll_seconds=0.01)
    try:
        assert scheduler.finish(timeout=2) is True
        assert _statuses(durable) == ["readonly"] and len(sessions) == 1
        assert not scheduler.errors and not scheduler._calculators
        with BudgetLedger(durable).route_lease(TARGET, ROUTE):
            pass
    finally:
        scheduler.stop()


def test_frozen_budget_wins_over_resume_overrides(tmp_path, sessions):
    durable = _store(tmp_path, budget={"group_seconds": 0.5, "route_seconds": 1.2})
    total, errors = interaction_jobs.run_pending(durable, group_seconds=8, route_seconds=90)
    assert total == 1 and errors == []
    assert sessions[0]["timeout_seconds"] == 0.5
    assert BudgetLedger(durable).summary(TARGET, ROUTE, "interaction")["limit_seconds"] == 1.2


def test_legacy_run_keeps_the_previously_configured_route_budget(tmp_path, sessions):
    durable = _store(tmp_path)
    ledger = BudgetLedger(durable)
    ledger.configure(TARGET, ROUTE, "interaction", 1.2)
    scheduler = interaction_jobs.InteractionScheduler(durable)
    try:
        assert scheduler.group_seconds == interaction_jobs.GROUP_SECONDS
        assert scheduler.step() == 1 and scheduler.errors == []
        assert ledger.summary(TARGET, ROUTE, "interaction")["limit_seconds"] == 1.2
        assert sessions[0]["timeout_seconds"] == 1.2
    finally:
        scheduler.close()


def test_legacy_run_without_a_ledger_budget_uses_defaults(tmp_path, sessions):
    durable = _store(tmp_path)
    assert interaction_jobs.run_pending(durable) == (1, [])
    assert sessions[0]["timeout_seconds"] == interaction_jobs.GROUP_SECONDS
    assert BudgetLedger(durable).summary(TARGET, ROUTE, "interaction")["limit_seconds"] == interaction_jobs.ROUTE_SECONDS


def test_real_budget_configuration_conflict_is_diagnosed_instead_of_retried(tmp_path, sessions):
    durable = _store(tmp_path, budget={"group_seconds": 5, "route_seconds": 30})
    ledger = BudgetLedger(durable)
    ledger.configure(TARGET, ROUTE, "interaction", 1.2)
    scheduler = interaction_jobs.InteractionScheduler(durable).start(poll_seconds=0.01)
    try:
        assert scheduler.finish(timeout=2) is True
        assert scheduler.errors == [{"route": [TARGET, "discriminant"], "exception_type": "BudgetConflict",
                                     "message": "budget.limit_mismatch"}]
        assert not scheduler._busy and scheduler._skipped == {(TARGET, "discriminant")}
        assert _statuses(durable) == ["pending"] and sessions == []
        assert ledger.summary(TARGET, ROUTE, "interaction")["limit_seconds"] == 1.2
        with ledger.route_lease(TARGET, ROUTE):
            pass
    finally:
        scheduler.stop()


def test_contention_releases_other_idle_leases_before_retrying(tmp_path, sessions):
    durable = _store(tmp_path)
    scheduler = interaction_jobs.InteractionScheduler(durable)
    try:
        scheduler._calculator(TARGET, "other-route")
        with BudgetLedger(durable).route_lease(TARGET, ROUTE):
            assert scheduler.step() == 0
            assert not scheduler._calculators
            with BudgetLedger(durable).route_lease(TARGET, "other-route" + interaction_jobs.LEASE_SUFFIX):
                pass
        assert scheduler.step() == 1
        assert not scheduler.errors
    finally:
        scheduler.close()


def test_unchanged_commit_watermark_skips_full_checkpoint_reads(tmp_path, sessions, monkeypatch):
    durable = _store(tmp_path)
    cp = durable.checkpoint(TARGET, "discriminant")
    cp["driver_state"]["interaction_seeds"][0]["display_unit"] = "boundary"
    durable.commit_route(cp, commit_id="wait-for-merge")
    reads = []
    read = durable.interaction_context

    def observed(*args):
        reads.append(args)
        return read(*args)

    monkeypatch.setattr(durable, "interaction_context", observed)
    scheduler = interaction_jobs.InteractionScheduler(durable)
    try:
        assert scheduler.step() == 0 and len(reads) == 1
        for _ in range(30):
            assert scheduler.step() == 0
        assert len(reads) == 1 and sessions == []
        # A legal checkpoint-only commit has no event and still closes a merge
        # prefix. Event last_seq alone would miss this transition forever.
        before = durable.snapshot()["last_seq"]
        cp["status"] = "math_failed"
        durable.commit_route(cp, commit_id="failed-without-event")
        assert durable.snapshot()["last_seq"] == before
        assert scheduler.step() == 1 and len(reads) == 2
        assert _statuses(durable) == ["readonly"]
    finally:
        scheduler.close()


def test_idle_polling_backs_off_and_resets_when_a_commit_arrives(tmp_path, sessions):
    durable = _store(tmp_path)
    cp = durable.checkpoint(TARGET, "discriminant")
    cp["driver_state"]["interaction_seeds"][0]["display_unit"] = "boundary"
    durable.commit_route(cp, commit_id="wait-for-merge")
    scheduler = interaction_jobs.InteractionScheduler(durable)
    delays = []

    class Wake:
        def wait(self, delay):
            delays.append(delay)
            if len(delays) == 7:
                durable.commit_route(cp, commit_id="new-checkpoint")
            elif len(delays) == 8:
                scheduler._stop.set()

        def clear(self):
            pass

        def set(self):
            pass

    scheduler._wake = Wake()
    scheduler.start()
    scheduler._thread.join(2)
    assert not scheduler._thread.is_alive()
    assert delays == pytest.approx([0.05, 0.1, 0.2, 0.4, 0.8, 1, 1, 0.05])
    assert scheduler.errors == [] and sessions == []
