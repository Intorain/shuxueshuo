"""Avoid repeated history scans and duplicate state, without timing assertions."""

import fcntl
import json
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
from threading import Event

import pytest
from jsonschema import ValidationError
from test_graph_stage_three_events import (
    IDENTITY,
    TARGET,
    checkpoint,
    fragment,
    operation,
    store_with_step,
)

from shuxueshuo_server.graph_lesson.stage_three import events as event_module
from shuxueshuo_server.graph_lesson.stage_three import storage_validation
from shuxueshuo_server.graph_lesson.stage_three.events import EventStore


def _selection(store, commit_id, title):
    return store.commit_events([{
        "type": "lesson.chunk_ready", "target_ref": TARGET, "route_id": None,
        "payload": {"kind": "D3", "chunk": {"title": title}},
    }], commit_id=commit_id)


def _trace(store, monkeypatch):
    statements = []
    connect = store._connect

    def traced():
        db = connect()
        db.set_trace_callback(statements.append)
        return db

    monkeypatch.setattr(store, "_connect", traced)
    return statements


def _read_group(directory):
    # A generation is retained only while current; pair readers pin it with
    # the same lock used by publishers and garbage collection.
    with (directory / ".export.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_SH)
        return _read_group_locked(directory)


def _read_group_locked(directory):
    manifest = json.loads((directory / "export-manifest.json").read_text())
    values = {}
    for key in ("checkpoint", "events"):
        raw = (directory / manifest[key]["path"]).read_bytes()
        assert sha256(raw).hexdigest() == manifest[key]["sha256"]
        values[key] = (json.loads(raw) if key == "checkpoint" else
                       [json.loads(line) for line in raw.splitlines()])
    assert values["checkpoint"]["last_seq"] == manifest["last_seq"]
    assert values["checkpoint"]["minimum_seq"] == manifest["minimum_seq"]
    assert [event["seq"] for event in values["events"]] == list(
        range(manifest["minimum_seq"], manifest["last_seq"] + 1),
    )
    return values


def test_selection_snapshots_read_materialized_rows_not_historical_receipts(tmp_path, monkeypatch):
    store, _ = store_with_step(tmp_path)
    for index in range(20):
        _selection(store, f"choice-{index}", str(index))
    store.prune_events(22)
    statements = _trace(store, monkeypatch)
    for _ in range(3):
        assert store.snapshot()["selection_chunks"] == [
            {"target_ref": TARGET, "kind": "D3", "chunk": {"title": "19"}},
        ]
    assert not any("FROM commits" in sql for sql in statements)
    assert sum("FROM selection_chunks" in sql for sql in statements) == 3


def test_checkpoint_uses_summary_index_without_loading_prior_card_bodies(tmp_path, monkeypatch):
    store, _ = store_with_step(tmp_path)
    statements = _trace(store, monkeypatch)

    def full_steps_forbidden(*args):
        raise AssertionError("checkpoint must not deserialize previous cards")

    monkeypatch.setattr(store, "_steps", full_steps_forbidden)
    store.commit_route(checkpoint(position=2), commit_id="second", math_steps=[fragment(ordinal=2)])
    assert [item["ordinal"] for item in store.checkpoint(TARGET, "discriminant")["math_steps"]] == [1, 2]
    assert any("SELECT step,ordinal,hash FROM step_summaries" in sql for sql in statements)
    assert not any("FROM steps" in sql and "ORDER BY" in sql for sql in statements)


def test_receipts_never_retain_growing_driver_history(tmp_path):
    store = EventStore(tmp_path, IDENTITY, create=True)
    for index in range(1, 10):
        cp = checkpoint(position=index)
        cp["driver_state"]["history"] = ["x" * 2000] * index
        result = store.commit_route(cp, commit_id=f"commit-{index}", events=[operation()])
        assert "driver_state" not in result["checkpoint"]
        assert result["checkpoint"]["last_seq"] == index
        assert store.commit_route(cp, commit_id=f"commit-{index}", events=[operation()]) == result
    with sqlite3.connect(store.path) as db:
        receipts = [json.loads(row[0]) for row in db.execute("SELECT result FROM commits")]
    assert all("history" not in json.dumps(receipt) for receipt in receipts)
    assert len({len(json.dumps(receipt["checkpoint"])) for receipt in receipts}) == 1
    assert len(store.checkpoint(TARGET, "discriminant")["driver_state"]["history"]) == 9


def _legacy_database(tmp_path):
    store, _ = store_with_step(tmp_path)
    _selection(store, "z-older", "old")
    _selection(store, "a-newer", "new")
    saved = store.checkpoint(TARGET, "discriminant")
    store.prune_events(4)
    with sqlite3.connect(store.path) as db:
        db.execute("DROP TABLE selection_chunks")
        db.execute("DROP TABLE step_summaries")
        db.execute("DELETE FROM metadata WHERE key='storage_version'")
        receipt = json.loads(db.execute("SELECT result FROM commits WHERE id='first'").fetchone()[0])
        receipt["checkpoint"] = saved
        db.execute("UPDATE commits SET result=? WHERE id='first'", (json.dumps(receipt),))
    return store


def test_legacy_database_migrates_pruned_selection_receipts_and_summary_index_once(tmp_path, monkeypatch):
    _legacy_database(tmp_path)
    reopened = EventStore(tmp_path, IDENTITY)
    assert reopened.snapshot()["selection_chunks"] == [
        {"target_ref": TARGET, "kind": "D3", "chunk": {"title": "new"}},
    ]
    reopened.commit_route(checkpoint(position=2), commit_id="second", math_steps=[fragment(ordinal=2)])
    assert len(reopened.checkpoint(TARGET, "discriminant")["math_steps"]) == 2
    with sqlite3.connect(reopened.path) as db:
        receipt = json.loads(db.execute("SELECT result FROM commits WHERE id='first'").fetchone()[0])
        assert "driver_state" not in receipt["checkpoint"]
    statements = []
    original = EventStore._connect

    def traced(self):
        db = original(self)
        db.set_trace_callback(statements.append)
        return db

    monkeypatch.setattr(EventStore, "_connect", traced)
    again = EventStore(tmp_path, IDENTITY)
    assert again.snapshot()["selection_chunks"] == reopened.snapshot()["selection_chunks"]
    assert not any("FROM commits" in sql for sql in statements)


def test_failed_legacy_migration_rolls_back_and_can_retry(tmp_path, monkeypatch):
    legacy = _legacy_database(tmp_path)
    original = EventStore._put_selection

    def fail(db, event):
        original(db, event)
        raise RuntimeError("migration interrupted")

    with monkeypatch.context() as patch:
        patch.setattr(EventStore, "_put_selection", staticmethod(fail))
        with pytest.raises(RuntimeError, match="migration interrupted"):
            EventStore(tmp_path, IDENTITY)
    with sqlite3.connect(legacy.path) as db:
        assert db.execute("SELECT value FROM metadata WHERE key='storage_version'").fetchone() is None
        assert db.execute("SELECT name FROM sqlite_master WHERE name='selection_chunks'").fetchone() is None
    assert EventStore(tmp_path, IDENTITY).snapshot()["selection_chunks"][0]["chunk"] == {"title": "new"}


def test_schema_compilation_is_per_revision_not_per_step(tmp_path, monkeypatch):
    storage_validation._validator.cache_clear()
    builds = []
    original = storage_validation.Draft202012Validator

    def counted(schema):
        builds.append(schema)
        return original(schema)

    monkeypatch.setattr(storage_validation, "Draft202012Validator", counted)
    store = EventStore(tmp_path, IDENTITY, create=True)
    for index in range(1, 11):
        store.commit_route(checkpoint(position=index), commit_id=f"step-{index}",
                           math_steps=[fragment(ordinal=index)], events=[operation()])
        store.checkpoint(TARGET, "discriminant")
    assert len(builds) == 3  # checkpoint, math card, event


def test_schema_cache_detects_same_size_mtime_rewrites_and_different_paths(tmp_path):
    path = tmp_path / "schema.json"
    path.write_text('{"const":1}')
    storage_validation.validate_schema(path, 1)
    before = path.stat()
    path.write_text('{"const":2}')
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    with pytest.raises(ValidationError):
        storage_validation.validate_schema(path, 1)
    storage_validation.validate_schema(path, 2)
    alternate = tmp_path / "alternate.json"
    alternate.write_text('{"const":3}')
    storage_validation.validate_schema(alternate, 3)
    storage_validation.validate_schema(path, 2)


def test_schema_modified_while_reading_is_not_cached_under_old_revision(tmp_path, monkeypatch):
    path = tmp_path / "schema.json"
    path.write_text('{"const":1}')
    read = Path.read_bytes
    changed = False

    def racing_read(current):
        nonlocal changed
        raw = read(current)
        if current == path and not changed:
            changed = True
            path.write_text('{"const":2}')
        return raw

    monkeypatch.setattr(Path, "read_bytes", racing_read)
    storage_validation.validate_schema(path, 2)
    with pytest.raises(ValidationError):
        storage_validation.validate_schema(path, 1)


def test_export_manifest_keeps_only_the_current_pair_after_retention(tmp_path):
    store, _ = store_with_step(tmp_path)
    store.export()
    previous_manifest = json.loads((tmp_path / "export-manifest.json").read_text())
    store.prune_events(2)
    store.commit_route(checkpoint(position=2), commit_id="second", math_steps=[fragment(ordinal=2)])
    store.export()
    assert _read_group(tmp_path)["checkpoint"]["last_seq"] == 3
    assert not (tmp_path / previous_manifest["checkpoint"]["path"]).parent.exists()
    assert len(list((tmp_path / ".event-exports").iterdir())) == 1


def test_export_crash_preserves_published_pair_and_sqlite_resume(tmp_path, monkeypatch):
    store, _ = store_with_step(tmp_path)
    store.export()
    store.commit_route(checkpoint(position=2), commit_id="second", math_steps=[fragment(ordinal=2)])
    original = event_module.atomic_write

    def interrupted(path, text):
        if path == tmp_path / "events.jsonl":
            raise RuntimeError("export interrupted")
        return original(path, text)

    with monkeypatch.context() as patch:
        patch.setattr(event_module, "atomic_write", interrupted)
        with pytest.raises(RuntimeError, match="export interrupted"):
            store.export()
    assert _read_group(tmp_path)["checkpoint"]["last_seq"] == 3
    reopened = EventStore(tmp_path, IDENTITY)
    assert reopened.checkpoint(TARGET, "discriminant")["driver_state"]["position"] == 2
    assert reopened.export()["last_seq"] == 3
    assert json.loads((tmp_path / "checkpoint.json").read_text()) == _read_group(tmp_path)["checkpoint"]
    assert [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()] == reopened.events()


def test_concurrent_exports_take_their_snapshots_under_export_lock(tmp_path, monkeypatch):
    first, _ = store_with_step(tmp_path)
    second = EventStore(tmp_path, IDENTITY)
    first_read = Event()
    release = Event()
    original = first.snapshot_with_events

    def pause():
        value = original()
        first_read.set()
        assert release.wait(timeout=10)
        return value

    monkeypatch.setattr(first, "snapshot_with_events", pause)
    with ThreadPoolExecutor(max_workers=2) as pool:
        older = pool.submit(first.export)
        assert first_read.wait(timeout=10)
        second.commit_route(checkpoint(position=2), commit_id="second", math_steps=[fragment(ordinal=2)])
        newer = pool.submit(second.export)
        release.set()
        assert older.result(timeout=10)["last_seq"] == 2
        assert newer.result(timeout=10)["last_seq"] == 3
    assert _read_group(tmp_path)["checkpoint"]["last_seq"] == 3
    assert json.loads((tmp_path / "checkpoint.json").read_text())["last_seq"] == 3
    assert len(list((tmp_path / ".event-exports").iterdir())) == 1
