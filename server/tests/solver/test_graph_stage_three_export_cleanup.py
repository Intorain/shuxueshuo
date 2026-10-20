"""Debug generations are bounded without weakening durable publication/recovery."""

import fcntl
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from shuxueshuo_server.graph_lesson.stage_three import events as event_module
from shuxueshuo_server.graph_lesson.stage_three.events import EventStore
from tests.solver.test_graph_stage_three_event_storage_scaling import _read_group
from tests.solver.test_graph_stage_three_events import (
    IDENTITY,
    TARGET,
    checkpoint,
    fragment,
    store_with_step,
)


def generation(directory):
    manifest = json.loads((directory / "export-manifest.json").read_text())
    return (directory / manifest["checkpoint"]["path"]).parent


def next_step(store, ordinal):
    store.commit_route(checkpoint(position=ordinal), commit_id=f"step-{ordinal}",
                       math_steps=[fragment(ordinal=ordinal)])


def test_repeated_exports_keep_one_valid_pair_and_same_generation_is_not_deleted(tmp_path):
    store, _ = store_with_step(tmp_path)
    for ordinal in range(1, 7):
        if ordinal > 1:
            next_step(store, ordinal)
        store.export()
        current = generation(tmp_path)
        assert list(current.parent.iterdir()) == [current]
        before = _read_group(tmp_path)
        store.export()
        assert generation(tmp_path) == current
        assert list(current.parent.iterdir()) == [current]
        assert _read_group(tmp_path) == before
    assert store.checkpoint(TARGET, "discriminant")["driver_state"]["position"] == 6


@pytest.mark.parametrize("failure", ["manifest_write", "manifest_directory_sync"])
def test_old_pair_is_kept_until_manifest_publication_is_durable(tmp_path, monkeypatch, failure):
    store, _ = store_with_step(tmp_path)
    store.export()
    previous = generation(tmp_path)
    next_step(store, 2)
    sync = event_module._sync_directory
    write = event_module.export_json

    def fail_sync(path):
        if path == tmp_path:
            assert generation(tmp_path) != previous
            assert previous.is_dir()
            raise OSError("manifest directory sync interrupted")
        sync(path)

    def fail_write(path, value):
        if path == tmp_path / "export-manifest.json":
            assert generation(tmp_path) == previous
            raise OSError("manifest write interrupted")
        write(path, value)

    with monkeypatch.context() as patch:
        patch.setattr(event_module, "_sync_directory", fail_sync)
        if failure == "manifest_write":
            patch.setattr(event_module, "export_json", fail_write)
        with pytest.raises(OSError, match="manifest.*interrupted"):
            store.export()
    assert previous.is_dir()
    assert (previous / "checkpoint.json").is_file() and (previous / "events.jsonl").is_file()
    reopened = EventStore(tmp_path, IDENTITY)
    assert reopened.checkpoint(TARGET, "discriminant")["driver_state"]["position"] == 2
    leftovers = set(previous.parent.iterdir())
    next_step(reopened, 3)
    reopened.export()
    assert not previous.exists()
    assert list(previous.parent.iterdir()) == [generation(tmp_path)]
    assert not any(path.exists() for path in leftovers)
    assert _read_group(tmp_path)["checkpoint"]["last_seq"] == 4


def test_partial_cleanup_is_nonfatal_and_retried_on_next_export(tmp_path, monkeypatch, caplog):
    store, _ = store_with_step(tmp_path)
    store.export()
    previous = generation(tmp_path)
    next_step(store, 2)
    remove = event_module.shutil.rmtree

    def interrupted(path):
        assert path == previous and generation(tmp_path) != previous
        (path / "checkpoint.json").unlink()
        raise PermissionError("cleanup temporarily unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(event_module.shutil, "rmtree", interrupted)
        assert store.export()["last_seq"] == 3
    assert "will retry on the next export" in caplog.text
    assert previous.is_dir() and (previous / "events.jsonl").is_file()
    assert _read_group(tmp_path)["checkpoint"]["last_seq"] == 3
    assert event_module.shutil.rmtree is remove
    assert EventStore(tmp_path, IDENTITY).export()["last_seq"] == 3
    assert not previous.exists()
    assert list(previous.parent.iterdir()) == [generation(tmp_path)]


def test_cleanup_preserves_unmanaged_entries_and_does_not_follow_symlinks(tmp_path):
    store, _ = store_with_step(tmp_path)
    store.export()
    parent = generation(tmp_path).parent
    notes = parent / "notes"
    notes.mkdir()
    (notes / "keep.txt").write_text("keep")
    outside = tmp_path / "unrelated"
    outside.mkdir()
    sentinel = outside / "keep.txt"
    sentinel.write_text("outside")
    link = parent / ("1-1-" + "a" * 64 + "-" + "b" * 64)
    link.symlink_to(outside, target_is_directory=True)
    ordinary_file = parent / ("1-1-" + "c" * 64 + "-" + "d" * 64)
    ordinary_file.write_text("not a directory")
    next_step(store, 2)
    store.export()
    assert (notes / "keep.txt").read_text() == "keep"
    assert link.is_symlink() and sentinel.read_text() == "outside"
    assert ordinary_file.read_text() == "not a directory"
    assert set(parent.iterdir()) == {generation(tmp_path), notes, link, ordinary_file}


def test_shared_reader_pins_old_pair_until_it_finishes(tmp_path, monkeypatch):
    store, _ = store_with_step(tmp_path)
    store.export()
    previous = generation(tmp_path)
    next_step(store, 2)
    writer = EventStore(tmp_path, IDENTITY)
    started, acquired = Event(), Event()
    snapshot = writer.snapshot_with_events

    def took_lock():
        acquired.set()
        return snapshot()

    def export():
        started.set()
        return writer.export()

    monkeypatch.setattr(writer, "snapshot_with_events", took_lock)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with (tmp_path / ".export.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_SH)
            old_manifest = json.loads((tmp_path / "export-manifest.json").read_text())
            future = pool.submit(export)
            assert started.wait(timeout=5)
            assert not acquired.wait(timeout=0.05)
            assert (tmp_path / old_manifest["checkpoint"]["path"]).is_file()
            assert _read_group(tmp_path)["checkpoint"]["last_seq"] == 2
        assert future.result(timeout=5)["last_seq"] == 3
    assert acquired.is_set() and not previous.exists()
    assert _read_group(tmp_path)["checkpoint"]["last_seq"] == 3
