"""Polling interaction status is a read, including for databases from older runs."""

import json
import sqlite3
import time
from contextlib import closing

import pytest

from shuxueshuo_server.graph_lesson.stage_three.events import EventStore
from shuxueshuo_server.problem_understanding.identity import revision
from shuxueshuo_server.problem_understanding.workflow_ledger import save
from shuxueshuo_server.search import stage_three

SEED = {"run_id": "a" * 32, "lesson_version": "lesson-01",
        "stage_one": {"sha256": "b" * 64}, "stage_two": {"sha256": "c" * 64}}
IDENTITY = {"run_id": SEED["run_id"], "lesson_version": SEED["lesson_version"],
            "input_sha256": revision({"stage_one": SEED["stage_one"]["sha256"],
                                      "stage_two": SEED["stage_two"]["sha256"]}),
            "revisions": {"methods": "d" * 64}}


def make_store(directory):
    store = EventStore(directory, IDENTITY, create=True)
    save(directory / "run.json", SEED)
    return store


def insert_state(db, step="step-1", status="pending"):
    db.execute("INSERT INTO interaction_states VALUES (?,?,?,?,?,?,?)",
               ("/root/goals/0", "interval", step, 1, "e" * 64, status, None))


def file_state(directory):
    return {path.name: (path.read_bytes(), path.stat().st_mtime_ns)
            for path in directory.iterdir() if path.is_file()}


def test_legacy_status_query_leaves_database_files_schema_and_version_unchanged(tmp_path, monkeypatch, caplog):
    store = make_store(tmp_path)
    with closing(sqlite3.connect(store.path, isolation_level=None)) as db:
        db.execute("PRAGMA journal_mode=DELETE")
        db.execute("DROP TABLE interactions")
        db.execute("DROP TABLE interaction_states")
        db.execute("UPDATE metadata SET value='2' WHERE key='storage_version'")
        schema = db.execute("SELECT name,sql FROM sqlite_master ORDER BY name").fetchall()
    before = file_state(tmp_path)
    statements, original = [], sqlite3.connect

    def read_only_connect(database, **kwargs):
        assert database.endswith("?mode=ro") and kwargs.get("uri") is True
        db = original(database, **kwargs)
        db.set_trace_callback(statements.append)
        return db

    def forbid_store(*args, **kwargs):
        raise AssertionError("a status read must not construct or migrate EventStore")

    with monkeypatch.context() as patch:
        patch.setattr(stage_three, "open_store", forbid_store)
        patch.setattr(stage_three.sqlite3, "connect", read_only_connect)
        assert stage_three.has_pending_interactions(tmp_path) is False
    assert file_state(tmp_path) == before
    assert all(sql.startswith(("BEGIN", "SELECT")) for sql in statements)
    assert not caplog.records
    with closing(original(store.path)) as db:
        assert db.execute("SELECT name,sql FROM sqlite_master ORDER BY name").fetchall() == schema
        assert db.execute("SELECT value FROM metadata WHERE key='storage_version'").fetchone() == ("2",)


def test_status_reads_committed_pending_rows_from_the_live_wal(tmp_path):
    store = make_store(tmp_path)
    with closing(sqlite3.connect(store.path, isolation_level=None)) as writer:
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        insert_state(writer, "already-resolved", "readonly")
        insert_state(writer)
        assert store.path.with_name("events.sqlite3-wal").stat().st_size > 0
        assert stage_three.has_pending_interactions(tmp_path) is True
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("UPDATE interaction_states SET status='readonly' WHERE status='pending'")
        # An uncommitted resolution cannot hide the last committed pending state.
        assert stage_three.has_pending_interactions(tmp_path) is True
        writer.commit()
        assert stage_three.has_pending_interactions(tmp_path) is False


def test_existing_unversioned_interaction_tables_remain_readable_without_upgrading(tmp_path, caplog):
    store = make_store(tmp_path)
    with closing(sqlite3.connect(store.path, isolation_level=None)) as db:
        db.execute("PRAGMA journal_mode=DELETE")
        db.execute("UPDATE metadata SET value='2' WHERE key='storage_version'")
        insert_state(db)
    before = file_state(tmp_path)
    assert stage_three.has_pending_interactions(tmp_path) is True
    assert file_state(tmp_path) == before
    assert not caplog.records


@pytest.mark.parametrize("damage", ["database", "metadata_json", "run_id", "lesson_version", "input_sha256",
                                    "missing_identity", "missing_run", "run_json", "missing_status_column"])
def test_status_query_logs_database_and_identity_errors_and_keeps_math_status(tmp_path, caplog, damage):
    store = make_store(tmp_path)
    with closing(sqlite3.connect(store.path, isolation_level=None)) as db:
        db.execute("PRAGMA journal_mode=DELETE")
        insert_state(db)
        if damage == "metadata_json":
            db.execute("UPDATE metadata SET value='{' WHERE key='identity'")
        elif damage in {"run_id", "lesson_version", "input_sha256"}:
            changed = {**IDENTITY, damage: "different"}
            db.execute("UPDATE metadata SET value=? WHERE key='identity'", (json.dumps(changed),))
        elif damage == "missing_identity":
            db.execute("DELETE FROM metadata WHERE key='identity'")
        elif damage == "missing_status_column":
            db.execute("DROP TABLE interaction_states")
            db.execute("CREATE TABLE interaction_states (other TEXT)")
    if damage == "database":
        store.path.write_bytes(b"not a SQLite database")
    elif damage == "missing_run":
        (tmp_path / "run.json").unlink()
    elif damage == "run_json":
        (tmp_path / "run.json").write_text("{")
    assert stage_three.has_pending_interactions(tmp_path) is False
    assert len(caplog.records) == 1
    assert "Could not read pending interaction status" in caplog.records[0].message
    assert caplog.records[0].exc_info is not None


def test_missing_database_is_normal_and_never_created(tmp_path, caplog):
    assert stage_three.has_pending_interactions(tmp_path) is False
    assert list(tmp_path.iterdir()) == []
    assert not caplog.records


@pytest.mark.parametrize("damage", ["database", "run_json", "run_id", "metadata_json"])
def test_presentation_preserves_completed_math_when_stream_storage_is_invalid(tmp_path, caplog, damage):
    attempt = tmp_path / "stage-two-1"
    output = attempt / "stage-three"
    store = make_store(output)
    save(output / "stage-three-result.json", {"status": "completed"})
    with closing(sqlite3.connect(store.path, isolation_level=None)) as db:
        db.execute("PRAGMA journal_mode=DELETE")
        insert_state(db)
        if damage == "metadata_json":
            db.execute("UPDATE metadata SET value='{' WHERE key='identity'")
    if damage == "database":
        store.path.write_bytes(b"not a SQLite database")
    elif damage == "run_json":
        (output / "run.json").write_text("{")
    elif damage == "run_id":
        save(output / "run.json", {**SEED, "run_id": "different"})
    # The status endpoint calls presentation: broken optional stream state must
    # not raise through it and turn a valid mathematical result into an HTTP 500.
    assert stage_three.presentation(tmp_path, "search-id", attempt=attempt) == {
        "execution_status": "completed", "stream": None,
    }
    assert len(caplog.records) == 2
    assert "Could not read pending interaction status" in caplog.records[0].message
    assert "Could not read stage-three stream identity" in caplog.records[1].message
    assert all(record.exc_info is not None for record in caplog.records)


def test_presentation_survives_busy_database_and_recovers_pending_after_lock_release(tmp_path, monkeypatch, caplog):
    attempt = tmp_path / "stage-two-1"
    output = attempt / "stage-three"
    store = make_store(output)
    save(output / "stage-three-result.json", {"status": "completed"})
    with closing(sqlite3.connect(store.path, isolation_level=None)) as writer:
        writer.execute("PRAGMA journal_mode=DELETE")
        insert_state(writer)
        writer.execute("BEGIN EXCLUSIVE")
        timeouts, original = [], sqlite3.connect

        def timed_read(database, **kwargs):
            assert database.endswith("?mode=ro") and kwargs.get("uri") is True
            timeouts.append(kwargs.get("timeout"))
            return original(database, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(stage_three.sqlite3, "connect", timed_read)
            started = time.monotonic()
            result = stage_three.presentation(tmp_path, "search-id", attempt=attempt)
            elapsed = time.monotonic() - started
        assert result == {"execution_status": "completed", "stream": None}
        assert timeouts == [0.2, 0.2]
        assert elapsed < 2
        assert len(caplog.records) == 2
        assert all(record.exc_info is not None for record in caplog.records)
        writer.rollback()
    caplog.clear()
    recovered = stage_three.presentation(tmp_path, "search-id", attempt=attempt)
    assert recovered["execution_status"] == "interrupted"
    assert recovered["stream"]["run_id"] == SEED["run_id"]
    assert recovered["stream"]["lesson_version"] == SEED["lesson_version"]
    assert not caplog.records
