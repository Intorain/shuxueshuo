"""Retry intent must supersede the previous run before its new directory exists."""

import threading
import time
from contextlib import nullcontext
from contextvars import Context
from uuid import uuid4

import pytest

from shuxueshuo_server.graph_lesson.stage_three.checkpoint import identity_from_seed
from shuxueshuo_server.graph_lesson.stage_three.events import EventStore
from shuxueshuo_server.graph_lesson.stage_three.storage import storage_context
from shuxueshuo_server.graph_lesson.stage_two.runner import replay_run
from shuxueshuo_server.problem_understanding.workflow_ledger import save
from shuxueshuo_server.search import dev_api, stage_three
from tests.search.test_stage_three_api import (
    client_for,
    forbidden,
    seed,
    start,
    status,
    wait_done,
)
from tests.solver.test_graph_stage_three_recorded import Q01_SELECTION


def submitted_work(function, arguments):
    task = arguments[0] if isinstance(getattr(function, '__self__', None), Context) else function
    if task.__qualname__ == 'SearchTaskRunner._run':
        return arguments[1].work
    return task


def completed_run(client, directory):
    repo = client.app.state.search_repository
    output = directory / "stage-two-1/stage-three"
    seed = {"run_id": uuid4().hex, "lesson_version": "retry-fixture",
            "stage_one": {"sha256": "a" * 64}, "stage_two": {"sha256": "b" * 64}}
    identity = {**identity_from_seed(seed), "revisions": {"fixture": "c" * 64}}
    save(output / "run.json", seed)
    save(output / "frozen.json", {"implementation": identity["revisions"]})
    with storage_context(repo.db, directory.name, clock=repo.clock):
        EventStore(output, identity, create=True)
    save(output / "stage-three-result.json", {"status": "completed"})


@pytest.mark.parametrize("paused_phase", ["queued", "stage_two"])
def test_accepted_retry_does_not_publish_previous_terminal_run(tmp_path, monkeypatch, paused_phase):
    root, directory = seed(tmp_path)
    reached, release, finished = threading.Event(), threading.Event(), threading.Event()
    executor = dev_api.ThreadPoolExecutor

    def pause():
        reached.set()
        assert release.wait(15), "test did not release accepted retry"

    class PausedExecutor(executor):
        def submit(self, function, *args, **kwargs):
            task = submitted_work(function, args)
            if task.__qualname__.endswith("retry_lesson.<locals>.work"):
                def queued():
                    try:
                        if paused_phase == "queued":
                            pause()
                        return function(*args, **kwargs)
                    finally:
                        finished.set()

                return super().submit(queued)
            return super().submit(function, *args, **kwargs)

    def recorded_stage_two(output, _result, **_kwargs):
        if paused_phase == "stage_two":
            pause()
        return replay_run(Q01_SELECTION, output / "stage-two-2")

    monkeypatch.setattr(dev_api, "ThreadPoolExecutor", PausedExecutor)
    monkeypatch.setattr(dev_api, "run_stage_two", recorded_stage_two)
    monkeypatch.setattr(dev_api, "run_question_image", forbidden)
    monkeypatch.setattr("shuxueshuo_server.graph_lesson.stage_two.selection.live_provider_factory", lambda: forbidden)
    with client_for(root) as client:
        first = start(client)["stream"]
        old_snapshot = client.get(first["snapshot_url"]).json()
        try:
            assert client.post(f"/api/search/problems/{directory.name}/lesson").json() == {"status": "running"}
            assert reached.wait(5)
            assert not (directory / "stage-two-2").exists()
            for observer in (client, client_for(root)):
                with observer if observer is not client else nullcontext(observer):
                    current = status(observer)
                    assert current["status"] == "running", current
                    assert current["execution_status"] == "starting", current
                    assert current["stream"] is None
                    assert not current.get("goals")
                    assert observer.get(first["snapshot_url"]).json() == old_snapshot
        finally:
            release.set()
            assert finished.wait(30), "retry worker did not finish before test cleanup"
        second = wait_done(client)["stream"]
        assert second["run_id"] != first["run_id"]
        assert second["lesson_version"] != first["lesson_version"]
        assert sorted(path.name for path in directory.glob("stage-two-*")) == ["stage-two-1", "stage-two-2"]
        assert client.get(first["snapshot_url"]).json() == old_snapshot


@pytest.mark.parametrize("failure_phase", ["queue", "stage_two"])
def test_retry_failure_releases_intent_and_keeps_history_readable(tmp_path, monkeypatch, failure_phase):
    root, directory = seed(tmp_path)
    executor = dev_api.ThreadPoolExecutor

    class FailingExecutor(executor):
        def submit(self, function, *args, **kwargs):
            task = submitted_work(function, args)
            if failure_phase == "queue" and task.__qualname__.endswith("retry_lesson.<locals>.work"):
                raise RuntimeError("injected queue failure")
            return super().submit(function, *args, **kwargs)

    def failed_stage_two(*args, **kwargs):
        raise RuntimeError(f"injected stage two failure reading {directory / 'question.png'}")

    monkeypatch.setattr(dev_api, "ThreadPoolExecutor", FailingExecutor)
    monkeypatch.setattr(dev_api, "run_stage_two", failed_stage_two)
    monkeypatch.setattr("shuxueshuo_server.graph_lesson.stage_two.selection.live_provider_factory", lambda: forbidden)
    with client_for(root) as client:
        completed_run(client, directory)
        if failure_phase == "queue":
            with pytest.raises(RuntimeError, match="injected queue failure"):
                client.post(f"/api/search/problems/{directory.name}/lesson")
        else:
            assert client.post(f"/api/search/problems/{directory.name}/lesson").json() == {"status": "running"}
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            current = status(client)
            if current["execution_status"] == "completed":
                break
            time.sleep(0.01)
        assert current["execution_status"] == "completed", current
        assert current["goals"] and not (directory / "stage-two-2").exists()
        assert not (directory / stage_three.RETRY_INTENT).exists()
        if failure_phase == "stage_two":
            assert current["execution_error"] == "search.lesson_failed"
            assert str(directory) not in str(current)
        # The next operation can reserve the problem immediately, and a fresh
        # router also sees readable history rather than a permanent spinner.
        stage_three.release_problem(stage_three.acquire_problem(directory))
        with client_for(root) as observer:
            assert status(observer)["execution_status"] == "completed"


def test_crashed_retry_intent_is_inactive_without_its_lease_and_not_inherited(tmp_path):
    root, directory = seed(tmp_path)
    lease = stage_three.acquire_problem(directory)
    stage_three.reserve_retry(directory)
    assert stage_three.pending_retry(directory) == directory / "stage-two-2"
    # Closing without adapter cleanup models the kernel releasing flock when
    # a process dies. The durable intent itself deliberately remains on disk.
    lease.close()
    assert (directory / stage_three.RETRY_INTENT).is_file()
    assert stage_three.pending_retry(directory) is None
    with client_for(root) as observer:
        completed_run(observer, directory)
        assert status(observer)["execution_status"] == "completed"
    lease = stage_three.acquire_problem(directory)
    try:
        assert stage_three.pending_retry(directory) is None
        assert not (directory / stage_three.RETRY_INTENT).exists()
    finally:
        stage_three.release_problem(lease)


def test_terminal_result_remains_running_until_current_worker_finishes(tmp_path, monkeypatch):
    root, directory = seed(tmp_path)
    completed, release = threading.Event(), threading.Event()
    original = stage_three.run_stage_three

    def delay_worker_cleanup(*args, **kwargs):
        result = original(*args, **kwargs)
        completed.set()
        assert release.wait(15), "test did not release completed worker"
        return result

    monkeypatch.setattr(stage_three, "run_stage_three", delay_worker_cleanup)
    with client_for(root) as client:
        assert client.post(f"/api/search/problems/{directory.name}/lesson/start").status_code == 200
        try:
            assert completed.wait(15)
            assert (directory / "stage-two-1/stage-three/stage-three-result.json").is_file()
            current = status(client)
            assert current["execution_status"] == "running", current
            stream = current["stream"]
            assert stream and client.get(stream["snapshot_url"]).status_code == 200
            with client_for(root) as observer:
                observed = status(observer)
                assert observed["execution_status"] == "running", observed
                assert observed["stream"] == stream
        finally:
            release.set()
        assert wait_done(client)["stream"] == stream
