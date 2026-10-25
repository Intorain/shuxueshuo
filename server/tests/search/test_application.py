"""Single-process production search wiring and shutdown over isolated PostgreSQL."""

import importlib
import runpy
import secrets
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from shuxueshuo_server.auth import api as auth_api
from shuxueshuo_server.auth.config import AuthConfig
from shuxueshuo_server.auth.service import AuthService
from shuxueshuo_server.auth.sms import MockSms
from shuxueshuo_server.product import api as product_api
from shuxueshuo_server.search import application, dev_api, maintenance
from tests.search.test_lesson_admission_concurrency import admission_url
from tests.search.test_private_api import login, recorded_pipeline, upload
from tests.search.test_repository import (
    PAGES,
    SUBMISSIONS,
    identity,
    student,
    submission,
)
from tests.search.test_repository import repository as repository_fixture
from tests.search.test_stage_three_api import client_for, forbidden, seed


@pytest.fixture
def repository(tmp_path):
    yield from repository_fixture.__wrapped__(tmp_path)


@pytest.fixture
def production_app(repository, monkeypatch):
    repository.admission.set_generation_enabled(True)
    importlib.import_module("shuxueshuo_server.tutor_demo.api")
    settings = SimpleNamespace(mode="server", root=repository.root.parent / "instance")
    (settings.root / "locks").mkdir(parents=True)
    config = AuthConfig(mode="mock", environment="test", origin="https://testserver",
                        secret=secrets.token_urlsafe(48), session_seconds=90 * 86400)
    auth = AuthService(repository.db, config, MockSms(), clock=repository.clock)
    closed = Event()
    product = SimpleNamespace(db=repository.db, settings=settings, close=closed.set)
    install_auth = auth_api.install_auth
    roots = []

    def create_repository(database, root):
        assert database is repository.db
        roots.append(root)
        return repository

    monkeypatch.setenv("REVIEW_BACKEND", "product")
    monkeypatch.setenv("PRODUCT_MODE", "server")
    monkeypatch.setenv("PRODUCT_EXECUTION_STORAGE_CONTEXT_REQUIRED", "0")
    monkeypatch.setenv("RUN_LLM_INTEGRATION", "0")
    monkeypatch.setattr(product_api, "load_application", lambda: product)
    monkeypatch.setattr(application, "SearchRepository", create_repository)
    monkeypatch.setattr(auth_api, "install_auth", lambda app: install_auth(app, auth=auth))
    monkeypatch.setattr(dev_api.OcrClient, "observe", lambda *_args, **_kwargs: {
        "width": 100, "height": 100, "lines": [], "layout": [], "latency_ms": {"detect": 0},
    })
    monkeypatch.setattr(dev_api, "run_question_image", forbidden)
    monkeypatch.setattr(dev_api, "run_stage_two", forbidden)
    monkeypatch.setattr(dev_api.stage_three, "run_stage_three", forbidden)
    monkeypatch.setattr(dev_api.stage_three, "resume_stage_three", forbidden)
    app = runpy.run_module("shuxueshuo_server.main")["app"]
    return SimpleNamespace(app=app, auth=auth, closed=closed, roots=roots, settings=settings,
                           drain=settings.root / "locks/services-draining")


def test_production_startup_recovers_and_cleans_before_serving(production_app, repository):
    user = student(repository)
    row, _ = submission(repository, user)
    repository.test_time[0] += timedelta(days=2)
    with TestClient(production_app.app, base_url=production_app.auth.config.origin) as client:
        assert client.get("/api/search/problems").status_code == 401
        assert production_app.roots == [production_app.settings.root / "work/search/private-v1"]
        assert repository.submission(user, row["id"])["recognition_status"] == "interrupted"
        with repository.db.connect() as connection:
            assert connection.scalar(sa.select(PAGES.c.image_state).where(PAGES.c.id == row["page_id"])) == "expired"
        assert not repository.storage.path(repository.storage.page_key(row["page_id"])).exists()
        assert not production_app.closed.is_set()
    assert production_app.closed.is_set()


@pytest.mark.parametrize("path,body", [
    ("/pages", None),
    ("/pages/012345abcdef/rotate", {"degrees": 90}),
    ("/problems", {"page_id": "012345abcdef", "box": [0, 0, 1, 1]}),
    ("/problems/012345abcdef/lesson", None),
    ("/problems/012345abcdef/lesson/start", None),
    ("/problems/012345abcdef/lesson/run/resume", None),
])
def test_draining_refuses_new_work_but_keeps_reads_and_deletes(production_app, repository, path, body):
    with TestClient(production_app.app, base_url=production_app.auth.config.origin) as client:
        user, _token = login(client, production_app.auth)
        row, _ = submission(repository, user)
        (row["path"] / "crop.json").write_text("{}")
        production_app.drain.touch()
        response = client.post("/api/search" + path, json=body)
        assert response.status_code == 503, response.text
        assert response.json() == {"detail": "service.draining"}
        assert client.get("/api/search/problems").status_code == 200
        assert client.get("/api/search/problems/" + row["id"]).status_code == 200
        assert client.delete("/api/search/problems/" + row["id"]).status_code == 200


def test_recognition_rechecks_drain_after_lifecycle_lock(production_app, repository, monkeypatch):
    monkeypatch.setenv("RUN_LLM_INTEGRATION", "1")
    original = repository.storage.lifecycle_lock
    locked = []

    def acquire(search_id, **kwargs):
        lease = original(search_id, **kwargs)
        locked.append(search_id)
        production_app.drain.touch()
        return lease

    with TestClient(production_app.app, base_url=production_app.auth.config.origin) as client:
        login(client, production_app.auth)
        page = upload(client)
        monkeypatch.setattr(repository.storage, "lifecycle_lock", acquire)
        response = client.post("/api/search/problems", json={"page_id": page["page_id"], "box": [0, 0, 1, 1]})
        assert response.status_code == 503
        assert len(locked) == 1
        with original(locked[0]):
            assert not repository.storage.path(repository.storage.submission_key(locked[0])).exists()
        with repository.db.connect() as connection:
            assert connection.scalar(sa.select(sa.func.count()).select_from(SUBMISSIONS)) == 0


@pytest.mark.parametrize("operation", ["retry", "start", "resume"])
def test_lesson_admission_rechecks_drain_after_lifecycle_lock(tmp_path, monkeypatch, operation):
    root, directory = seed(tmp_path)
    monkeypatch.setattr(dev_api, "run_question_image", forbidden)
    monkeypatch.setattr(dev_api, "run_stage_two", forbidden)
    monkeypatch.setattr(dev_api.stage_three, "run_stage_three", forbidden)
    monkeypatch.setattr(dev_api.stage_three, "resume_stage_three", forbidden)
    with client_for(root) as client:
        url = admission_url(client, directory, operation)
        repository = client.app.state.search_repository
        drain = tmp_path / "services-draining"
        client.app.state.search_drain_path = drain
        original = repository.storage.lifecycle_lock

        def acquire(search_id, **kwargs):
            lease = original(search_id, **kwargs)
            drain.touch()
            return lease

        monkeypatch.setattr(repository.storage, "lifecycle_lock", acquire)
        response = client.post(url)
        assert response.status_code == 503, response.text
        with original(directory.name):
            dev_api.stage_three.release_problem(dev_api.stage_three.acquire_problem(directory))
        with repository.db.connect() as connection:
            assert connection.scalar(sa.select(SUBMISSIONS.c.lesson_status).where(SUBMISSIONS.c.id == directory.name)) != "running"


def test_shutdown_finishes_worker_and_closes_ocr_before_database(production_app, repository, monkeypatch):
    entered, release, closing = Event(), Event(), Event()
    recorded_pipeline(monkeypatch, entered=entered, release=release)
    threadpool = dev_api.run_in_threadpool
    closed_ocr = []

    async def observe_shutdown(function, *args, **kwargs):
        if getattr(function, "__name__", None) == "shutdown":
            closing.set()
        return await threadpool(function, *args, **kwargs)

    def close_ocr(_client):
        assert not production_app.closed.is_set()
        closed_ocr.append(True)

    monkeypatch.setattr(dev_api, "run_in_threadpool", observe_shutdown)
    monkeypatch.setattr(dev_api.OcrClient, "close", close_ocr)
    client = TestClient(production_app.app, base_url=production_app.auth.config.origin)
    client.__enter__()
    user, _token = login(client, production_app.auth)
    page = upload(client)
    response = client.post("/api/search/problems", json={"page_id": page["page_id"], "box": [0, 0, 1, 1]})
    assert response.status_code == 200, response.text
    with ThreadPoolExecutor(max_workers=1) as pool:
        try:
            assert entered.wait(5)
            shutdown = pool.submit(client.__exit__, None, None, None)
            assert closing.wait(5)
            assert production_app.app.state.search_accepting is False
            assert not production_app.closed.is_set()
            assert closed_ocr == []
            with pytest.raises(TimeoutError):
                shutdown.result(timeout=0.1)
        finally:
            release.set()
        shutdown.result(timeout=15)
    assert closed_ocr == [True]
    assert production_app.closed.is_set()
    assert repository.submission(user, response.json()["search_id"])["lesson_status"] == "ready"


def test_periodic_cleanup_retries_and_shutdown_waits_for_current_scan(production_app, repository, monkeypatch):
    entered, release, closing = Event(), Event(), Event()
    original = repository.cleanup
    calls = []

    def cleanup():
        calls.append(True)
        if len(calls) == 2:
            raise OSError("injected cleanup failure")
        if len(calls) == 3:
            entered.set()
            assert release.wait(10)
            assert not production_app.closed.is_set()
        return original()

    monkeypatch.setattr(application, "CLEANUP_INTERVAL", 0.01)
    monkeypatch.setattr(repository, "cleanup", cleanup)
    monkeypatch.setattr(dev_api.OcrClient, "close", lambda _client: closing.set())
    client = TestClient(production_app.app, base_url=production_app.auth.config.origin)
    client.__enter__()
    with ThreadPoolExecutor(max_workers=1) as pool:
        try:
            assert entered.wait(5)
            shutdown = pool.submit(client.__exit__, None, None, None)
            assert closing.wait(5)
            assert not production_app.closed.is_set()
            with pytest.raises(TimeoutError):
                shutdown.result(timeout=0.1)
        finally:
            release.set()
        shutdown.result(timeout=5)
    assert len(calls) == 3
    assert production_app.closed.is_set()


@pytest.mark.parametrize("command", ["cleanup", "disable"])
def test_maintenance_supports_server_settings(repository, monkeypatch, capsys, command):
    row, _ = submission(repository, student(repository))
    problem_id = repository.associate(row["id"], identity())["id"]
    selected = []

    def load(*args):
        selected.append(args)
        return repository.test_settings

    monkeypatch.setattr(maintenance.Settings, "load", load)
    monkeypatch.setattr(maintenance, "engine", lambda _url: repository.db)
    monkeypatch.setattr(maintenance, "SearchRepository", lambda _db, _root: repository)
    arguments = ["maintenance", "--mode", "server", "--data-dir", "/srv/test-only", "--instance", "isolated", command]
    if command == "disable":
        arguments.append(str(problem_id))
    monkeypatch.setattr(sys, "argv", arguments)
    maintenance.main()
    assert selected == [("server", "/srv/test-only", "isolated")]
    output = capsys.readouterr().out
    if command == "disable":
        assert "disabled" in output
