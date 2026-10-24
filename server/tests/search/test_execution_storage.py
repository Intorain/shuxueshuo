"""Real PostgreSQL execution transactions and private submission lifecycle."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import text

from shuxueshuo_server.graph_lesson.stage_three.events import EventStore
from shuxueshuo_server.graph_lesson.stage_three.storage import (
    RunNotFound,
    RunUnavailable,
    read_run,
    storage_context,
)
from tests.search.test_repository import identity, student, submission
from tests.search.test_repository import repository as repository_fixture

repository = repository_fixture


def execution(repo):
    user = student(repo)
    row, _ = submission(repo, user)
    value = {"run_id": uuid4().hex, "lesson_version": "fixture", "input_sha256": "a" * 64,
             "revisions": {"fixture": "b" * 64}}
    with storage_context(repo.db, row["id"], clock=repo.clock):
        store = EventStore(row["path"] / "execution", value, create=True)
    return user, row, store


def status_event():
    return {"type": "lesson.goal_status", "target_ref": "/root/goals/0", "route_id": None,
            "payload": {"status": "solved", "available": True}}


def test_atomic_rollback_retry_and_parallel_sequence(repository):
    _, _, store = execution(repository)

    def fail():
        raise RuntimeError("abort before commit")

    with pytest.raises(RuntimeError, match="abort before commit"):
        store.commit_events([status_event()], commit_id="same", before_commit=fail)
    assert store.events() == []
    assert store.commit_watermark() == 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        receipts = list(pool.map(lambda _: store.commit_events([status_event()], commit_id="same"), range(4)))
    assert all(receipt == receipts[0] for receipt in receipts)
    assert [event["seq"] for event in store.events()] == [1]
    assert store.committed_events("same") == receipts[0]["events"]
    assert not (store.directory / "events.sqlite3").exists()


def test_snapshot_and_events_use_one_repeatable_read_view(repository, monkeypatch):
    _, _, store = execution(repository)
    store.commit_events([status_event()], commit_id="first")
    entered, release = Event(), Event()
    original = store._internal_snapshot

    def pause(connection):
        snapshot = original(connection)
        entered.set()
        assert release.wait(5)
        return snapshot

    monkeypatch.setattr(store, "_internal_snapshot", pause)
    with ThreadPoolExecutor(max_workers=2) as pool:
        reader = pool.submit(store.snapshot_with_events)
        assert entered.wait(5)
        store.commit_events([status_event()], commit_id="second")
        release.set()
        snapshot, events = reader.result(timeout=5)
    assert snapshot["last_seq"] == 1
    assert [event["seq"] for event in events] == [1]
    assert len(store.events()) == 2


def test_delete_serializes_with_commit_and_cascades_all_execution_rows(repository):
    user, row, store = execution(repository)
    entered, release = Event(), Event()

    def pause():
        entered.set()
        assert release.wait(5)

    with ThreadPoolExecutor(max_workers=2) as pool:
        writer = pool.submit(store.commit_events, [status_event()], commit_id="first", before_commit=pause)
        assert entered.wait(5)
        deletion = pool.submit(repository.delete, user, row["id"])
        assert not deletion.done()
        release.set()
        assert writer.result(timeout=5)["last_seq"] == 1
        deletion.result(timeout=5)
    with pytest.raises(RunNotFound):
        store.commit_events([status_event()], commit_id="late")
    with repository.db.connect() as connection:
        for name in ("runs", "metadata", "events", "commits", "goals"):
            assert connection.scalar(text(f"SELECT count(*) FROM lesson_{name} WHERE run_id=:run"),
                                     {"run": store.identity["run_id"]}) == 0


def test_expiry_at_commit_boundary_rolls_back_all_mutations(repository):
    _, row, store = execution(repository)

    def expire():
        repository.test_time[0] = row["expires_at"]

    with pytest.raises(RunUnavailable, match="events.submission_expired"):
        store.commit_events([status_event()], commit_id="expired", before_commit=expire)
    with repository.db.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM lesson_events WHERE run_id=:run"),
                                 {"run": store.identity["run_id"]}) == 0
        assert connection.scalar(text("SELECT value FROM lesson_metadata WHERE run_id=:run AND key='last_seq'"),
                                 {"run": store.identity["run_id"]}) == "0"


def test_scope_mismatch_and_disabled_problem_cannot_read_or_write(repository):
    _, row, store = execution(repository)
    _, foreign, _ = execution(repository)
    with storage_context(repository.db, foreign["id"], clock=repository.clock), pytest.raises(RunNotFound):
        read_run(store.identity["run_id"])
    with storage_context(repository.db), pytest.raises(RunNotFound):
        read_run(store.identity["run_id"])
    problem = repository.link_identity(row["id"], identity())
    repository.disable(problem["id"])
    with pytest.raises(RunUnavailable, match="events.problem_disabled"):
        store.commit_events([status_event()], commit_id="late")
    with pytest.raises(RunUnavailable, match="events.problem_disabled"):
        store.snapshot()


def test_recreated_run_never_adopts_an_old_store(repository, tmp_path):
    value = {"run_id": uuid4().hex, "lesson_version": "fixture", "input_sha256": "a" * 64,
             "revisions": {"fixture": "b" * 64}}
    with storage_context(repository.db):
        old = EventStore(tmp_path / "old", value, create=True)
        with repository.db.begin() as connection:
            connection.execute(text("DELETE FROM lesson_runs WHERE run_id=:run"), {"run": value["run_id"]})
        current = EventStore(tmp_path / "new", value, create=True)
    with pytest.raises(RunNotFound, match="events.run_replaced"):
        old.commit_events([status_event()], commit_id="stale")
    assert current.events() == []


def test_cleanup_expires_execution_without_removing_shared_history(repository):
    user, row, store = execution(repository)
    problem = repository.link_identity(row["id"], identity())
    store.commit_events([status_event()], commit_id="first")
    repository.test_time[0] = row["expires_at"] + timedelta(seconds=1)
    repository.cleanup()
    with repository.db.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM lesson_runs WHERE run_id=:run"),
                                 {"run": store.identity["run_id"]}) == 0
    assert repository.history(user)["items"][0]["problem_id"] == str(problem["id"])
