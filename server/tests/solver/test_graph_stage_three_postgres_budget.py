"""PostgreSQL budget authority, run isolation and lifecycle fencing."""

import json
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from PIL import Image
from sqlalchemy import create_engine, text

from shuxueshuo_server.graph_lesson.stage_three import budget as budget_module
from shuxueshuo_server.graph_lesson.stage_three.budget import (
    BudgetConflict,
    BudgetExhausted,
    BudgetLedger,
    BudgetPending,
)
from shuxueshuo_server.graph_lesson.stage_three.checkpoint import export_json
from shuxueshuo_server.graph_lesson.stage_three.events import EventStore
from shuxueshuo_server.graph_lesson.stage_three.storage import (
    RunNotFound,
    RunUnavailable,
    storage_context,
)
from shuxueshuo_server.search.repository import SearchRepository

TARGET = "/root/goals/0"
ROUTE = "discriminant"


@pytest.fixture
def ledger_factory(stage_three_storage, tmp_path):
    def create(*, submission_id=None, clock=None, directory=None):
        run_id = uuid4().hex
        identity = {"run_id": run_id, "lesson_version": "pg-budget", "input_sha256": "a" * 64,
                    "revisions": {"methods": "b" * 64}}
        with storage_context(stage_three_storage, submission_id, clock=clock):
            store = EventStore(directory or tmp_path / run_id, identity, create=True)
        return BudgetLedger(store), store

    return create


@pytest.fixture
def linked_submission(stage_three_storage, tmp_path):
    now = [datetime.now(UTC)]
    repository = SearchRepository(stage_three_storage, tmp_path / "private-v1", clock=lambda: now[0])
    phone = "139" + "".join(str(secrets.randbelow(10)) for _ in range(8))
    with stage_three_storage.begin() as connection:
        user = connection.scalar(text("SELECT register_student_phone(:phone,:id)"), {"phone": phone, "id": uuid4()})
    page_id, submission_id = secrets.token_hex(6), secrets.token_hex(6)
    page_directory = repository.storage.path(repository.storage.page_key(page_id))
    page_directory.mkdir()
    Image.new("RGB", (50, 50), "white").save(page_directory / "page.png")
    repository.register_page(user, page_id, {})
    submission_directory = repository.storage.path(repository.storage.submission_key(submission_id))
    submission_directory.mkdir()
    for filename in ("question.png", "original.png"):
        Image.new("RGB", (50, 50), "white").save(submission_directory / filename)
    row, created = repository.create_submission(user, submission_id, page_id, [0, 0, 1, 1])
    assert created
    yield SimpleNamespace(row=row, repository=repository, now=now)
    with stage_three_storage.begin() as connection:
        connection.execute(text("DELETE FROM search_submissions WHERE id=:id"), {"id": submission_id})


def receipt(attempt, *, elapsed=0.25, status="returned"):
    value = {"schema_version": "bounded-calculation-receipt/v1", "attempt_id": attempt["attempt_id"],
             "status": status, "elapsed_seconds": elapsed}
    if status == "returned":
        value["result"] = {"answer": ["rational", 1, 2], "text": "数学"}
    else:
        value["error"] = {"exception_type": "Interrupted", "message": "parent interrupted"}
    return value


def begin(ledger, owner, operation="advance:1", **kwargs):
    return ledger.begin(TARGET, ROUTE, "solve", operation, "input-a", owner, **kwargs)


def test_returned_receipt_survives_reopen_without_local_file(ledger_factory, stage_three_storage):
    ledger, store = ledger_factory()
    ledger.configure(TARGET, ROUTE, "solve", 10, initial_seconds=2)
    with ledger.route_lease(TARGET, ROUTE) as owner:
        attempt = begin(ledger, owner)
        assert attempt["summary"]["reserved_upper_seconds"] == 8
        export_json(attempt["receipt_path"], receipt(attempt))
    with storage_context(stage_three_storage):
        reopened = BudgetLedger(EventStore(store.directory, store.identity))
    with reopened.route_lease(TARGET, ROUTE) as owner:
        recovered = reopened.recover(TARGET, ROUTE, owner)
        assert recovered["summaries"]["solve"]["actual_seconds"] == 2.25
        Path(attempt["receipt_path"]).unlink()
        reused = begin(reopened, owner)
        assert reused["reused"] and reused["attempt_id"] == attempt["attempt_id"]
        assert reused["receipt"] == receipt(attempt)
        assert reopened.finish(attempt["attempt_id"], owner)["receipt"] == receipt(attempt)
        with pytest.raises(BudgetConflict, match="receipt_reuse_mismatch"):
            reopened.finish(attempt["attempt_id"], owner, receipt(attempt, elapsed=1))
    with store.transaction() as connection:
        stored = connection.scalar(text("""SELECT receipt FROM lesson_calculation_attempts
            WHERE run_id=:run_id AND attempt_id=:attempt_id"""),
            {"run_id": store.identity["run_id"], "attempt_id": attempt["attempt_id"]})
    assert json.loads(stored) == receipt(attempt)
    assert store.checkpoint(TARGET, ROUTE) is None


def test_equal_attempt_ids_in_different_runs_are_isolated(ledger_factory, monkeypatch):
    first, first_store = ledger_factory()
    second, second_store = ledger_factory()
    monkeypatch.setattr(budget_module, "uuid", SimpleNamespace(uuid4=lambda: SimpleNamespace(hex="same-budget-id")))
    first.configure(TARGET, ROUTE, "solve", 10)
    second.configure(TARGET, ROUTE, "solve", 20)
    with first.route_lease(TARGET, ROUTE) as first_owner, second.route_lease(TARGET, ROUTE) as second_owner:
        first_attempt, second_attempt = begin(first, first_owner), begin(second, second_owner)
        assert first_attempt["attempt_id"] == second_attempt["attempt_id"]
        first.finish(first_attempt["attempt_id"], first_owner, receipt(first_attempt, elapsed=1))
        second.finish(second_attempt["attempt_id"], second_owner, receipt(second_attempt, elapsed=3))
        assert begin(first, first_owner)["receipt"]["elapsed_seconds"] == 1
        assert begin(second, second_owner)["receipt"]["elapsed_seconds"] == 3
    assert first_store.identity["run_id"] != second_store.identity["run_id"]
    assert first.summary(TARGET, ROUTE, "solve")["remaining_seconds"] == 9
    assert second.summary(TARGET, ROUTE, "solve")["remaining_seconds"] == 17


def test_unknown_reservation_survives_resume_and_late_receipt_settles_once(ledger_factory):
    ledger, _store = ledger_factory()
    ledger.configure(TARGET, ROUTE, "solve", 10, initial_seconds=1)
    with ledger.route_lease(TARGET, ROUTE) as owner:
        attempt = begin(ledger, owner, allowance_seconds=3)
    with ledger.route_lease(TARGET, ROUTE) as owner:
        recovered = ledger.recover(TARGET, ROUTE, owner)
        summary = recovered["summaries"]["solve"]
        assert summary["actual_seconds"] == 1
        assert summary["reserved_upper_seconds"] == 3
        assert summary["remaining_seconds"] == 6
        assert summary["operations"][0]["status"] == "interrupted_unknown"
        with pytest.raises(BudgetPending):
            begin(ledger, owner)
        following = begin(ledger, owner, "advance:2", allowance_seconds=1)
        ledger.finish(following["attempt_id"], owner, receipt(following, elapsed=0.5))
        export_json(attempt["receipt_path"], receipt(attempt, elapsed=0.25))
        settled = ledger.recover(TARGET, ROUTE, owner)["summaries"]["solve"]
        assert settled["actual_seconds"] == 1.75
        assert settled["reserved_upper_seconds"] == 0
        assert [item["attempt_id"] for item in settled["operations"]] == [attempt["attempt_id"], following["attempt_id"]]
        assert ledger.recover(TARGET, ROUTE, owner)["summaries"]["solve"] == settled


@pytest.mark.parametrize("elapsed", [0.5, 10])
def test_parent_lost_receipt_is_committed_even_when_retry_exhausts_budget(ledger_factory, elapsed):
    ledger, _store = ledger_factory()
    ledger.configure(TARGET, ROUTE, "solve", 10)
    with ledger.route_lease(TARGET, ROUTE) as owner:
        attempt = begin(ledger, owner)
        export_json(attempt["receipt_path"], receipt(attempt, elapsed=elapsed, status="parent_lost"))
    with ledger.route_lease(TARGET, ROUTE) as owner:
        if elapsed == 10:
            with pytest.raises(BudgetExhausted):
                begin(ledger, owner)
        else:
            retry = begin(ledger, owner)
            assert not retry["reused"] and retry["ordinal"] == 2
            assert retry["remaining_seconds"] == 9.5
        summary = ledger.summary(TARGET, ROUTE, "solve")
        assert summary["actual_seconds"] == elapsed
        assert summary["operations"][0]["status"] == "settled"
        assert summary["operations"][0]["outcome"] == "parent_lost"


def test_lease_exclusion_and_stale_owner_fencing(ledger_factory):
    ledger, store = ledger_factory()
    contender = BudgetLedger(store)
    ledger.configure(TARGET, ROUTE, "solve", 10)
    with ledger.route_lease(TARGET, ROUTE) as first_owner:
        attempt = begin(ledger, first_owner)
        with pytest.raises(BudgetConflict, match="lease_busy"), contender.route_lease(TARGET, ROUTE):
            pytest.fail("a live owner must exclude a contender")
        with pytest.raises(BudgetConflict, match="lease_not_owned"):
            contender.finish(attempt["attempt_id"], first_owner, receipt(attempt))
    with contender.route_lease(TARGET, ROUTE) as second_owner:
        with pytest.raises(BudgetConflict, match="lease_not_owned"):
            ledger.finish(attempt["attempt_id"], first_owner, receipt(attempt))
        assert contender.finish(attempt["attempt_id"], second_owner, receipt(attempt))["summary"]["actual_seconds"] == 0.25


def test_same_run_in_different_directories_shares_database_lease(ledger_factory, stage_three_storage, tmp_path):
    ledger, store = ledger_factory()
    alternate = tmp_path / "alternate-directory"
    alternate.mkdir()
    with storage_context(stage_three_storage):
        contender = BudgetLedger(EventStore(alternate, store.identity))
    ledger.configure(TARGET, ROUTE, "solve", 10)
    with ledger.route_lease(TARGET, ROUTE) as owner:
        attempt = begin(ledger, owner)
        with pytest.raises(BudgetConflict, match="lease_busy"), contender.route_lease(TARGET, ROUTE):
            pytest.fail("the same database run cannot have two route owners")
        assert ledger.finish(attempt["attempt_id"], owner, receipt(attempt))["summary"]["actual_seconds"] == 0.25
    with contender.route_lease(TARGET, ROUTE) as owner:
        reused = begin(contender, owner)
        assert reused["reused"] and reused["receipt"] == receipt(attempt)


def test_database_lease_does_not_exhaust_the_application_connection_pool(ledger_factory, stage_three_storage):
    _ledger, store = ledger_factory()
    with stage_three_storage.connect() as connection:
        schema = connection.scalar(text("SELECT current_schema()"))
    database = create_engine(stage_three_storage.url, pool_size=1, max_overflow=0, pool_timeout=0.1,
                             connect_args={"options": f"-c search_path={schema},public"})
    try:
        with storage_context(database):
            ledger = BudgetLedger(EventStore(store.directory, store.identity))
        ledger.configure(TARGET, ROUTE, "solve", 10)
        with ledger.route_lease(TARGET, ROUTE) as owner:
            assert database.pool.checkedout() == 0
            with database.connect() as connection:
                activity = connection.execute(text("SELECT state,xact_start FROM pg_stat_activity WHERE pid=:pid"),
                                              {"pid": ledger._owners[owner][3]}).mappings().one()
            assert dict(activity) == {"state": "idle", "xact_start": None}
            attempt = begin(ledger, owner)
            assert ledger.finish(attempt["attempt_id"], owner, receipt(attempt))["summary"]["actual_seconds"] == 0.25
    finally:
        database.dispose()


def test_concurrent_configuration_cannot_change_the_first_limit(ledger_factory):
    ledger, store = ledger_factory()
    contender = BudgetLedger(store)
    barrier = Barrier(2)

    def configure(arguments):
        current, limit = arguments
        barrier.wait(timeout=5)
        try:
            return current.configure(TARGET, ROUTE, "solve", limit)
        except BudgetConflict as exc:
            return str(exc)

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(configure, [(ledger, 10), (contender, 20)]))
    assert results.count("budget.limit_mismatch") == 1
    winner = next(item for item in results if isinstance(item, dict))
    assert ledger.summary(TARGET, ROUTE, "solve")["limit_seconds"] == winner["limit_seconds"]


def test_concurrent_attempt_replay_reserves_only_once(ledger_factory):
    ledger, _store = ledger_factory()
    ledger.configure(TARGET, ROUTE, "solve", 10)
    barrier = Barrier(2)
    with ledger.route_lease(TARGET, ROUTE) as owner:
        def reserve(_index):
            barrier.wait(timeout=5)
            try:
                return begin(ledger, owner)
            except BudgetPending as exc:
                return exc

        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(reserve, [0, 1]))
        assert sum(isinstance(item, BudgetPending) for item in results) == 1
        summary = ledger.summary(TARGET, ROUTE, "solve")
        assert len(summary["operations"]) == 1
        assert summary["reserved_upper_seconds"] == 10


def test_deleted_run_cannot_recreate_budget_or_finish_an_old_attempt(ledger_factory, stage_three_storage):
    ledger, store = ledger_factory()
    ledger.configure(TARGET, ROUTE, "solve", 10)
    with ledger.route_lease(TARGET, ROUTE) as owner:
        attempt = begin(ledger, owner)
        with stage_three_storage.begin() as connection:
            connection.execute(text("DELETE FROM lesson_runs WHERE run_id=:run_id"), {"run_id": store.identity["run_id"]})
        for mutation in (
            lambda: ledger.configure(TARGET, ROUTE, "verification", 20),
            lambda: ledger.finish(attempt["attempt_id"], owner, receipt(attempt)),
            lambda: ledger.recover(TARGET, ROUTE, owner),
            lambda: BudgetLedger(store),
        ):
            with pytest.raises(RunNotFound):
                mutation()
    with stage_three_storage.connect() as connection:
        for table in ("lesson_calculation_budgets", "lesson_calculation_leases", "lesson_calculation_attempts"):
            assert connection.scalar(text(f"SELECT count(*) FROM {table} WHERE run_id=:run_id"),
                                     {"run_id": store.identity["run_id"]}) == 0


def test_expired_submission_blocks_all_budget_writes_without_refund(ledger_factory, linked_submission, stage_three_storage):
    linked = linked_submission
    ledger, store = ledger_factory(submission_id=linked.row["id"], clock=linked.repository.clock,
                                   directory=linked.row["path"] / "stage-two-1/stage-three")
    ledger.configure(TARGET, ROUTE, "solve", 10)
    with ledger.route_lease(TARGET, ROUTE) as owner:
        attempt = begin(ledger, owner)
        linked.now[0] += timedelta(days=31)
        for mutation in (
            lambda: ledger.configure(TARGET, ROUTE, "verification", 20),
            lambda: begin(ledger, owner, "advance:2"),
            lambda: ledger.finish(attempt["attempt_id"], owner, receipt(attempt)),
            lambda: ledger.recover(TARGET, ROUTE, owner),
            lambda: BudgetLedger(store),
        ):
            with pytest.raises(RunUnavailable):
                mutation()
    with stage_three_storage.connect() as connection:
        saved = connection.execute(text("""SELECT status,receipt,reserved_upper_seconds
            FROM lesson_calculation_attempts WHERE run_id=:run_id"""),
            {"run_id": store.identity["run_id"]}).mappings().one()
    assert dict(saved) == {"status": "pending", "receipt": None, "reserved_upper_seconds": 10}


def test_expiry_during_settlement_rolls_back_receipt_and_refund(
    ledger_factory, linked_submission, stage_three_storage, monkeypatch,
):
    linked = linked_submission
    ledger, store = ledger_factory(submission_id=linked.row["id"], clock=linked.repository.clock,
                                   directory=linked.row["path"] / "stage-two-1/stage-three")
    ledger.configure(TARGET, ROUTE, "solve", 10)
    settle = ledger._settle

    def expire_during_settle(connection, row, completed):
        settle(connection, row, completed)
        linked.now[0] += timedelta(days=31)

    with ledger.route_lease(TARGET, ROUTE) as owner:
        attempt = begin(ledger, owner)
        monkeypatch.setattr(ledger, "_settle", expire_during_settle)
        with pytest.raises(RunUnavailable):
            ledger.finish(attempt["attempt_id"], owner, receipt(attempt))
    with stage_three_storage.connect() as connection:
        saved = connection.execute(text("""SELECT status,receipt,reserved_upper_seconds
            FROM lesson_calculation_attempts WHERE run_id=:run_id"""),
            {"run_id": store.identity["run_id"]}).mappings().one()
    assert dict(saved) == {"status": "pending", "receipt": None, "reserved_upper_seconds": 10}
