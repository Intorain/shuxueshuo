"""Page concurrency and explicit private execution scopes over isolated PostgreSQL."""

import multiprocessing
import os
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from contextvars import copy_context
from datetime import timedelta
from threading import Event
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from shuxueshuo_server.auth.api import cookie_name
from shuxueshuo_server.auth.config import AuthConfig
from shuxueshuo_server.graph_lesson.stage_three import storage
from shuxueshuo_server.problem_understanding.workflow_ledger import save
from shuxueshuo_server.search import dev_api
from tests.search.test_execution_storage import status_event
from tests.search.test_postgres_execution import execution
from tests.search.test_repository import repository as repository_fixture
from tests.search.test_repository import student, submission
from tests.search.test_websocket_polling import stream as stream_fixture
from tools.run_site import create_local_app

GUARD = "PRODUCT_EXECUTION_STORAGE_CONTEXT_REQUIRED"


@pytest.fixture
def repository(tmp_path):
    yield from repository_fixture.__wrapped__(tmp_path)


@pytest.fixture
def stream(repository, monkeypatch):
    yield from stream_fixture.__wrapped__(repository, monkeypatch)


@pytest.mark.parametrize("operation", ["delete", "cleanup"])
def test_same_page_writes_overlap_but_block_page_lifecycle(repository, operation):
    user = student(repository)
    removable, _ = submission(repository, user)
    repository.test_time[0] += timedelta(minutes=1)
    first, _ = submission(repository, user, removable["page_id"])
    second, _ = submission(repository, user, removable["page_id"])
    stores = [execution(repository, row) for row in (first, second)]
    if operation == "cleanup":
        repository.test_time[0] = removable["expires_at"]
    entered = [Event(), Event()]
    release = Event()
    deleting = Event()

    def hold(index):
        entered[index].set()
        assert release.wait(10)

    def remove():
        deleting.set()
        if operation == "delete":
            return repository.delete(user, removable["id"])
        return repository.cleanup()

    with ThreadPoolExecutor(max_workers=3) as pool:
        first_write = pool.submit(stores[0].commit_events, [status_event()], commit_id="first",
                                  before_commit=lambda: hold(0))
        try:
            assert entered[0].wait(5)
            second_write = pool.submit(stores[1].commit_events, [status_event()], commit_id="second",
                                       before_commit=lambda: hold(1))
            assert entered[1].wait(3), "different submissions on the same page must write concurrently"
            removed = pool.submit(remove)
            assert deleting.wait(5)
            with pytest.raises(TimeoutError):
                removed.result(timeout=0.2)
        finally:
            release.set()
        assert first_write.result(timeout=5)["last_seq"] == 1
        assert second_write.result(timeout=5)["last_seq"] == 1
        removed.result(timeout=5)
    assert all(len(store.events()) == 1 for store in stores)
    with pytest.raises(dev_api.SearchError, match="search.not_found"):
        repository.submission(user, removable["id"])


def test_context_requirement_is_scoped_and_cli_default_is_unchanged(monkeypatch):
    monkeypatch.delenv(GUARD, raising=False)
    database = object()
    fallbacks = []

    def default_engine(*arguments):
        fallbacks.append(arguments)
        return database

    monkeypatch.setattr(storage, "_default_engine", default_engine)
    assert storage.current_storage().db is database
    with storage.require_storage_context():
        with pytest.raises(storage.StorageContextRequired):
            storage.current_storage()
        with storage.storage_context(database), pytest.raises(storage.StorageContextRequired):
            storage.current_storage()
        with storage.storage_context(database, "submission"):
            assert storage.current_storage().submission_id == "submission"
        with pytest.raises(storage.StorageContextRequired):
            storage.current_storage()
    assert len(fallbacks) == 1
    assert storage.current_storage().db is database
    assert len(fallbacks) == 2


def test_context_requirement_follows_background_work_without_leaking(monkeypatch):
    monkeypatch.delenv(GUARD, raising=False)
    database = object()
    monkeypatch.setattr(storage, "_default_engine", lambda *_args: database)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with storage.require_storage_context(), pytest.raises(storage.StorageContextRequired):
            pool.submit(copy_context().run, storage.current_storage).result(timeout=5)
        assert pool.submit(storage.current_storage).result(timeout=5).db is database


def spawn_context_probe(sender):
    def forbidden(*_args):
        raise AssertionError("spawn must not open the default database")

    storage._default_engine = forbidden
    try:
        storage.current_storage()
    except storage.StorageContextRequired as exc:
        sender.send(exc.code)
    finally:
        sender.close()


def test_web_process_guard_survives_spawn_without_parent_context(monkeypatch):
    monkeypatch.setenv(GUARD, "1")
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=spawn_context_probe, args=(sender,))
    with storage.storage_context(object(), "parent-submission"):
        process.start()
    sender.close()
    try:
        assert receiver.poll(15)
        assert receiver.recv() == "events.storage_context_required"
        process.join(timeout=15)
        assert process.exitcode == 0
    finally:
        receiver.close()
        if process.is_alive():
            process.kill()
            process.join()
        process.close()


@pytest.mark.parametrize("endpoint", ["snapshot", "events", "ws"])
@pytest.mark.parametrize("local_app", [False, True])
def test_web_requests_fail_closed_when_storage_binding_is_missing(stream, repository, monkeypatch, endpoint, local_app):
    monkeypatch.delenv(GUARD, raising=False)
    fallbacks = []

    def forbidden(*_args):
        fallbacks.append(True)
        raise AssertionError("web requests must never open the default database")

    monkeypatch.setattr(storage, "_default_engine", forbidden)
    monkeypatch.setattr(dev_api, "storage_context", lambda *_args, **_kwargs: nullcontext())
    app = stream.app
    if local_app:
        app = create_local_app(SimpleNamespace(mode="local", root=repository.root), AuthConfig(environment="development"))
        app.state.student_auth = stream.auth
        app.state.search_repository = repository
    client = TestClient(app, base_url=stream.auth.config.origin)
    client.cookies.set(cookie_name(stream.auth.config), stream.token)
    client.headers["Origin"] = stream.auth.config.origin
    url = f"/api/search/problems/{stream.row['id']}/lesson/{stream.store.identity['run_id']}/{endpoint}"
    if endpoint == "ws":
        with pytest.raises(WebSocketDisconnect) as closed, client.websocket_connect(url) as socket:
            socket.receive_json()
        assert closed.value.code == 1011
    else:
        response = client.get(url)
        assert response.status_code == 503
        assert response.json() == {"detail": "search.storage_unavailable"}
    assert fallbacks == []
    assert os.getenv(GUARD) is None


def test_missing_run_is_a_domain_error_not_a_missing_file(repository):
    row, _ = submission(repository, student(repository))
    store = execution(repository, row)
    with storage.storage_context(repository.db, row["id"], clock=repository.clock), pytest.raises(storage.RunNotFound) as missing:
        storage.read_run("f" * 32)
    assert missing.value.code == "events.run_not_found"
    assert not isinstance(missing.value, (FileNotFoundError, OSError, ValueError))
    assert store.events() == []


def test_queued_web_worker_cannot_fall_back_when_its_binding_is_omitted(stream, repository, monkeypatch):
    monkeypatch.delenv(GUARD, raising=False)
    user = stream.auth.current_user(stream.token)
    row, _ = submission(repository, user)
    save(row["path"] / "stage-two-1/stage-two-result.json", {"status": "resolved", "goals": []})
    fallbacks = []

    def forbidden(*_args):
        fallbacks.append(True)
        raise AssertionError("queued web work must never open the default database")

    def start(*_args, **_kwargs):
        return storage.current_storage()

    monkeypatch.setattr(storage, "_default_engine", forbidden)
    monkeypatch.setattr(dev_api, "storage_context", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(dev_api.stage_three, "run_stage_three", start)
    client = TestClient(stream.app, base_url=stream.auth.config.origin)
    client.cookies.set(cookie_name(stream.auth.config), stream.token)
    client.headers["Origin"] = stream.auth.config.origin
    response = client.post(f"/api/search/problems/{row['id']}/lesson/start")
    assert response.status_code == 200, response.text
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        current = repository.submission(user, row["id"])
        if current["lesson_status"] == "failed":
            break
        time.sleep(0.01)
    assert current["lesson_status"] == "failed"
    assert current["error_code"] == "search.lesson_failed"
    assert fallbacks == []
