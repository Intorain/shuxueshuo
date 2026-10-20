"""Interaction tables migrate once and preserve previously committed rows."""

import sqlite3
from contextlib import closing

import pytest

from shuxueshuo_server.graph_lesson.stage_three.events import EventStore
from tests.solver.test_graph_stage_three_events import IDENTITY


def tables(db):
    return {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_new_storage_includes_versioned_interaction_tables(tmp_path):
    store = EventStore(tmp_path, IDENTITY, create=True)
    with closing(sqlite3.connect(store.path)) as db:
        assert db.execute("SELECT value FROM metadata WHERE key='storage_version'").fetchone() == ("3",)
        assert {"interaction_states", "interactions"} <= tables(db)


@pytest.mark.parametrize("existing", [(), ("interaction_states",), ("interaction_states", "interactions")])
def test_v2_upgrade_preserves_existing_interaction_rows_without_replaying_receipts(tmp_path, monkeypatch, existing):
    store = EventStore(tmp_path, IDENTITY, create=True)
    state = ("target", "route", "step", 1, "e" * 64, "pending", None)
    chunk = ("f" * 24, "target", "route", 1, '{"saved":"interaction"}')
    with closing(sqlite3.connect(store.path, isolation_level=None)) as db:
        db.execute("UPDATE metadata SET value='2' WHERE key='storage_version'")
        for table in ("interaction_states", "interactions"):
            if table not in existing:
                db.execute(f"DROP TABLE {table}")
        if "interaction_states" in existing:
            db.execute("INSERT INTO interaction_states VALUES (?,?,?,?,?,?,?)", state)
        if "interactions" in existing:
            db.execute("INSERT INTO interactions VALUES (?,?,?,?,?)", chunk)
        db.execute("INSERT INTO metadata VALUES ('interactions','{\"saved\":\"settings\"}')")
        # v2 receipts have already been compacted; the upgrade must not read them.
        db.execute("INSERT INTO commits VALUES ('untouched','digest','not needed by v3')")
    statements, original = [], EventStore._connect

    def traced(self):
        db = original(self)
        db.set_trace_callback(statements.append)
        return db

    monkeypatch.setattr(EventStore, "_connect", traced)
    EventStore(tmp_path, IDENTITY)
    assert not any("FROM commits" in sql or "FROM steps" in sql for sql in statements)
    with closing(sqlite3.connect(store.path)) as db:
        assert db.execute("SELECT value FROM metadata WHERE key='storage_version'").fetchone() == ("3",)
        assert {"interaction_states", "interactions"} <= tables(db)
        assert db.execute("SELECT * FROM interaction_states").fetchall() == ([state] if "interaction_states" in existing else [])
        assert db.execute("SELECT * FROM interactions").fetchall() == ([chunk] if "interactions" in existing else [])
        assert db.execute("SELECT value FROM metadata WHERE key='interactions'").fetchone() == ('{"saved":"settings"}',)
    statements.clear()
    EventStore(tmp_path, IDENTITY)
    assert not any(sql.startswith(("CREATE", "INSERT", "UPDATE", "DELETE", "BEGIN IMMEDIATE")) for sql in statements)


@pytest.mark.parametrize("version", [None, "1"])
def test_legacy_migration_creates_compact_and_interaction_storage_atomically(tmp_path, version):
    store = EventStore(tmp_path, IDENTITY, create=True)
    with closing(sqlite3.connect(store.path, isolation_level=None)) as db:
        for table in ("selection_chunks", "step_summaries", "interaction_states", "interactions"):
            db.execute(f"DROP TABLE {table}")
        if version is None:
            db.execute("DELETE FROM metadata WHERE key='storage_version'")
        else:
            db.execute("UPDATE metadata SET value=? WHERE key='storage_version'", (version,))
    EventStore(tmp_path, IDENTITY)
    with closing(sqlite3.connect(store.path)) as db:
        assert db.execute("SELECT value FROM metadata WHERE key='storage_version'").fetchone() == ("3",)
        assert {"selection_chunks", "step_summaries", "interaction_states", "interactions"} <= tables(db)


def test_v3_migration_failure_rolls_back_new_tables_and_version(tmp_path, monkeypatch):
    store = EventStore(tmp_path, IDENTITY, create=True)
    with closing(sqlite3.connect(store.path, isolation_level=None)) as db:
        db.execute("UPDATE metadata SET value='2' WHERE key='storage_version'")
        db.execute("DROP TABLE interaction_states")
        db.execute("DROP TABLE interactions")
    original = EventStore._connect

    def fail_second_table(self):
        db = original(self)
        db.set_authorizer(lambda action, name, *_: sqlite3.SQLITE_DENY
                          if action == sqlite3.SQLITE_CREATE_TABLE and name == "interactions" else sqlite3.SQLITE_OK)
        return db

    with monkeypatch.context() as patch:
        patch.setattr(EventStore, "_connect", fail_second_table)
        with pytest.raises(sqlite3.DatabaseError):
            EventStore(tmp_path, IDENTITY)
    with closing(sqlite3.connect(store.path)) as db:
        assert db.execute("SELECT value FROM metadata WHERE key='storage_version'").fetchone() == ("2",)
        assert not {"interaction_states", "interactions"} & tables(db)
    EventStore(tmp_path, IDENTITY)
    with closing(sqlite3.connect(store.path)) as db:
        assert db.execute("SELECT value FROM metadata WHERE key='storage_version'").fetchone() == ("3",)
