"""Offline upload admission boundaries, independent of OCR and SMS providers."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from threading import Barrier, Event

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from shuxueshuo_server.auth.api import AuthBoundary
from shuxueshuo_server.auth.config import AuthConfig
from shuxueshuo_server.search.upload_admission import (
    UploadAdmission,
    UploadAdmissionBusy,
)


class FixtureAuth:
    config = AuthConfig(secure=False, origin="https://testserver")

    def current_user(self, token):
        return {"id": token} if token in {"alice", "bob", "charlie"} else None


def fixture_app(*, account_limit=2, global_limit=10):
    app = FastAPI()
    app.state.student_auth = FixtureAuth()
    app.state.search_upload_admission = UploadAdmission(account_limit=account_limit, global_limit=global_limit)
    return app, AuthBoundary(app)


def fixture_request(app, *, path="/api/search/pages", token="alice", origin="https://testserver",
                    expected="alice", body=b"fixture", length=None, stream_error=None):
    headers = [(b"origin", origin.encode()), (b"x-search-user", expected.encode())]
    if token is not None:
        headers.append((b"cookie", f"sss_dev_session={token}".encode()))
    if length is not None:
        headers.append((b"content-length", length.encode("latin-1")))
    received = []

    async def receive():
        received.append(True)
        if stream_error:
            raise stream_error
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {"type": "http", "method": "POST", "path": path, "headers": headers,
             "scheme": "https", "server": ("testserver", 443), "client": ("127.0.0.1", 80),
             "query_string": b"", "app": app}
    return Request(scope, receive=receive), received


async def accepted(request):
    return JSONResponse({"body_size": len(await request.body())})


def assert_empty(admission):
    assert admission._total == 0
    assert admission._accounts == {}


def test_default_limits_preserve_other_accounts_and_configuration_is_explicit(monkeypatch):
    monkeypatch.delenv("SEARCH_UPLOAD_ACCOUNT_LIMIT", raising=False)
    monkeypatch.delenv("SEARCH_UPLOAD_GLOBAL_LIMIT", raising=False)
    limiter = UploadAdmission.from_env()
    assert (limiter.account_limit, limiter.global_limit) == (2, 10)
    with ExitStack() as stack:
        for _ in range(2):
            stack.enter_context(limiter.admit("alice"))
        with pytest.raises(UploadAdmissionBusy), limiter.admit("alice"):
            pytest.fail("Third account request was accepted")
        for owner in ("bob", "charlie", "dana", "erin"):
            for _ in range(2):
                stack.enter_context(limiter.admit(owner))
        assert limiter._total == 10
        with pytest.raises(UploadAdmissionBusy), limiter.admit("frank"):
            pytest.fail("Eleventh global request was accepted")
    assert_empty(limiter)
    monkeypatch.setenv("SEARCH_UPLOAD_ACCOUNT_LIMIT", "3")
    monkeypatch.setenv("SEARCH_UPLOAD_GLOBAL_LIMIT", "4")
    limiter = UploadAdmission.from_env()
    assert (limiter.account_limit, limiter.global_limit) == (3, 4)


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "10"])
@pytest.mark.parametrize("field", ["account_limit", "global_limit"])
def test_invalid_limits_fail_closed(value, field):
    with pytest.raises(ValueError, match="positive integers"):
        UploadAdmission(**{field: value})


def test_atomic_concurrent_admission_never_exceeds_global_limit():
    admission = UploadAdmission()
    start = Barrier(20)
    result_ready = Barrier(21)
    release = Event()

    def enter(index):
        start.wait(timeout=10)
        try:
            with admission.admit(str(index % 5)):
                result_ready.wait(timeout=10)
                assert release.wait(10)
                return True
        except UploadAdmissionBusy:
            result_ready.wait(timeout=10)
            return False

    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(enter, index) for index in range(20)]
        try:
            result_ready.wait(timeout=10)
            assert admission._total == 10
            assert admission._accounts == {str(index): 2 for index in range(5)}
        finally:
            release.set()
        assert sum(future.result(timeout=10) for future in futures) == 10
    assert_empty(admission)


def test_default_upload_and_rotation_share_account_slots_without_blocking_other_accounts():
    async def scenario():
        app, boundary = fixture_app()
        entered, release = asyncio.Event(), asyncio.Event()
        active = []

        async def waiting_ocr(request):
            active.append(request.url.path)
            if len(active) == 2:
                entered.set()
            await release.wait()
            return await accepted(request)

        tasks = []
        for path in ("/api/search/pages", "/api/search/pages/123456abcdef/rotate"):
            request, _reads = fixture_request(app, path=path)
            tasks.append(asyncio.create_task(boundary.dispatch(request, waiting_ocr)))
        try:
            await asyncio.wait_for(entered.wait(), 3)
            rejected, rejected_reads = fixture_request(app)
            response = await boundary.dispatch(rejected, accepted)
            assert response.status_code == 429
            assert response.headers["cache-control"] == "no-store"
            assert not rejected_reads
            other, other_reads = fixture_request(app, token="bob", expected="bob")
            assert (await boundary.dispatch(other, accepted)).status_code == 200
            assert other_reads
            assert app.state.search_upload_admission._accounts == {"alice": 2}
        finally:
            release.set()
            assert all(response.status_code == 200 for response in await asyncio.gather(*tasks))
        assert_empty(app.state.search_upload_admission)

    asyncio.run(scenario())


@pytest.mark.parametrize("path", ["/api/search/pages", "/api/search/pages/123456abcdef/rotate"])
def test_in_flight_limit_covers_body_and_ocr_until_response(path):
    async def scenario():
        app, boundary = fixture_app(account_limit=1, global_limit=2)
        entered, release = asyncio.Event(), asyncio.Event()

        async def waiting_ocr(request):
            entered.set()
            await release.wait()
            return await accepted(request)

        first, first_reads = fixture_request(app, path=path)
        task = asyncio.create_task(boundary.dispatch(first, waiting_ocr))
        await asyncio.wait_for(entered.wait(), 3)
        try:
            second, second_reads = fixture_request(app)
            denied = await boundary.dispatch(second, accepted)
            assert denied.status_code == 429
            assert denied.body == b'{"detail":"search.upload_busy"}'
            assert denied.headers["cache-control"] == "no-store"
            assert first_reads and not second_reads
            other, other_reads = fixture_request(app, token="bob", expected="bob")
            response = await boundary.dispatch(other, accepted)
            assert response.status_code == 200
            assert other_reads
        finally:
            release.set()
            assert (await task).status_code == 200
        assert_empty(app.state.search_upload_admission)
        retried, _ = fixture_request(app)
        assert (await boundary.dispatch(retried, accepted)).status_code == 200

    asyncio.run(scenario())


def test_global_slot_is_already_held_while_request_body_is_streaming():
    async def scenario():
        app, boundary = fixture_app(account_limit=10, global_limit=1)
        entered, release = asyncio.Event(), asyncio.Event()
        first, _ = fixture_request(app)

        async def slow_receive():
            entered.set()
            await release.wait()
            return {"type": "http.request", "body": b"fixture", "more_body": False}

        first = Request(first.scope, receive=slow_receive)
        task = asyncio.create_task(boundary.dispatch(first, accepted))
        await asyncio.wait_for(entered.wait(), 3)
        try:
            other, other_reads = fixture_request(app, token="bob", expected="bob")
            denied = await boundary.dispatch(other, accepted)
            assert denied.status_code == 429
            assert not other_reads
        finally:
            release.set()
            assert (await task).status_code == 200
        assert_empty(app.state.search_upload_admission)

    asyncio.run(scenario())


@pytest.mark.parametrize("change,status", [
    ({"token": None}, 401), ({"token": "invalid"}, 401), ({"origin": "https://elsewhere"}, 403),
    ({"expected": "bob"}, 409),
])
def test_identity_checks_precede_admission_and_body_read(change, status):
    app, boundary = fixture_app(account_limit=1, global_limit=1)
    with app.state.search_upload_admission.admit("alice"):
        request, received = fixture_request(app, **change)
        response = asyncio.run(boundary.dispatch(request, accepted))
        assert response.status_code == status
        assert response.headers["cache-control"] == "no-store"
        assert not received
        assert app.state.search_upload_admission._total == 1
    assert_empty(app.state.search_upload_admission)


@pytest.mark.parametrize("marker", [False, True])
def test_draining_rejected_before_body_and_admission(tmp_path, marker):
    app, boundary = fixture_app()
    if marker:
        app.state.search_drain_path = tmp_path / "services-draining"
        app.state.search_drain_path.touch()
    else:
        app.state.search_accepting = False
    request, received = fixture_request(app)
    response = asyncio.run(boundary.dispatch(request, accepted))
    assert response.status_code == 503
    assert response.body == b'{"detail":"service.draining"}'
    assert not received
    assert_empty(app.state.search_upload_admission)


@pytest.mark.parametrize("length", ["-1", "bogus", "²", "9" * 5000, str(20 * 1024 * 1024 + 1)])
def test_bad_lengths_release_without_buffering(length):
    app, boundary = fixture_app()
    request, received = fixture_request(app, length=length)
    response = asyncio.run(boundary.dispatch(request, accepted))
    assert response.status_code == 413
    assert not received
    assert_empty(app.state.search_upload_admission)


@pytest.mark.parametrize("length", [None, str(20 * 1024 * 1024)])
def test_twenty_mib_boundary_retained(length):
    app, boundary = fixture_app()
    request, _ = fixture_request(app, body=b"x" * (20 * 1024 * 1024), length=length)
    response = asyncio.run(boundary.dispatch(request, accepted))
    assert response.status_code == 200
    assert_empty(app.state.search_upload_admission)


def test_chunked_body_over_limit_releases_slot():
    app, boundary = fixture_app()
    request, _ = fixture_request(app, body=b"x" * (20 * 1024 * 1024 + 1))
    response = asyncio.run(boundary.dispatch(request, accepted))
    assert response.status_code == 413
    assert_empty(app.state.search_upload_admission)


@pytest.mark.parametrize("failure", [OSError("fixture storage error"), HTTPException(400, "page.not_an_image")])
def test_handler_failure_releases_slot(failure):
    app, boundary = fixture_app()
    request, _ = fixture_request(app)

    async def fails(_request):
        raise failure

    response = asyncio.run(boundary.dispatch(request, fails))
    assert response.status_code == (400 if isinstance(failure, HTTPException) else 503)
    assert_empty(app.state.search_upload_admission)


@pytest.mark.parametrize("during_body", [False, True])
def test_cancellation_releases_slot(during_body):
    app, boundary = fixture_app()
    request, _ = fixture_request(app, stream_error=asyncio.CancelledError() if during_body else None)

    async def cancelled(_request):
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(boundary.dispatch(request, cancelled))
    assert_empty(app.state.search_upload_admission)


def test_non_upload_routes_do_not_take_upload_slots():
    app, boundary = fixture_app(account_limit=1, global_limit=1)
    with app.state.search_upload_admission.admit("alice"):
        for path in ("/api/search/problems", "/api/auth/logout", "/api/learning/progress"):
            request, received = fixture_request(app, path=path)
            response = asyncio.run(boundary.dispatch(request, accepted))
            assert response.status_code == 200
            assert received
            assert app.state.search_upload_admission._total == 1
    assert_empty(app.state.search_upload_admission)


def test_asgi_rotation_validation_failure_releases_admission():
    app, _boundary = fixture_app()
    app.add_middleware(AuthBoundary)

    @app.post("/api/search/pages/{page_id}/rotate")
    def rotate(page_id: str, body: dict):
        return {"page_id": page_id, "body": body}

    with TestClient(app, base_url="https://testserver") as client:
        client.cookies.set("sss_dev_session", "alice")
        client.headers.update({"Origin": "https://testserver", "X-Search-User": "alice"})
        assert client.post("/api/search/pages/123456abcdef/rotate", content=b"{").status_code == 422
        assert_empty(app.state.search_upload_admission)
        assert client.post("/api/search/pages/123456abcdef/rotate", json={"degrees": 90}).status_code == 200
        assert_empty(app.state.search_upload_admission)
