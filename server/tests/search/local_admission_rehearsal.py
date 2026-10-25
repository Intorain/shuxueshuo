"""Run real loopback HTTP admission acceptance with isolated PostgreSQL and offline fixtures."""

import argparse
import json
import secrets
import socket
import threading
import time
from dataclasses import asdict
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from PIL import Image

from shuxueshuo_server.auth import api as auth_api
from shuxueshuo_server.auth.config import AuthConfig
from shuxueshuo_server.auth.service import AuthService
from shuxueshuo_server.auth.sms import MockSms
from shuxueshuo_server.search import dev_api
from shuxueshuo_server.search.admission import SearchLimits
from shuxueshuo_server.solver.extraction import multimodal_provider
from tests.search.test_generation_admission_api import (
    block_recognition,
    offline_pipeline,
    settle,
    tickets,
)
from tests.search.test_repository import repository as repository_fixture


def checked(response, status=200):
    assert response.status_code == status, (response.status_code, response.text[:500])
    assert response.headers.get("cache-control") == "no-store"
    return response.json()


def await_ready(browser, repo, search_id):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        current = checked(browser.get(f"/api/search/problems/{search_id}"))
        if current["lesson_status"] == "ready":
            settle(repo)
            return current
        assert current["lesson_status"] not in {"failed", "unsupported", "unavailable"}, current
        time.sleep(0.02)
    raise TimeoutError("Offline course fixture did not finish")


def login(browser, auth):
    phone = "139" + "".join(str(secrets.randbelow(10)) for _ in range(8))
    sent = checked(browser.post("/api/auth/sms/send", json={"phone": phone}))
    code = auth.sms.messages[sent["challenge_id"]][1]
    verified = checked(browser.post("/api/auth/sms/verify", json={
        "phone": phone, "challenge_id": sent["challenge_id"], "code": code,
    }))
    browser.headers["X-Search-User"] = verified["user"]["id"]
    return verified["user"]


def exercise(browser, other, repo, auth, app, monkeypatch):
    checked(browser.get("/api/search/problems"), 401)
    owner = login(browser, auth)
    with Image.new("RGB", (100, 100), "white") as source, BytesIO() as encoded:
        source.save(encoded, format="PNG")
        page = checked(browser.post("/api/search/pages", content=encoded.getvalue()))
    rotated = checked(browser.post(f"/api/search/pages/{page['page_id']}/rotate", json={"degrees": 90}))
    assert rotated["page_id"] != page["page_id"]
    request = {"page_id": page["page_id"], "box": [0, 0, 1, 1], "client_request_id": "first"}
    assert not repo.admission.generation_enabled()
    assert checked(browser.post("/api/search/problems", json=request), 503)["detail"] == "search.generation_paused"
    repo.admission.set_generation_enabled(True)
    entered, release = block_recognition(monkeypatch)
    try:
        search_id = checked(browser.post("/api/search/problems", json=request))["search_id"]
        assert checked(browser.post("/api/search/problems", json=request))["search_id"] == search_id
        denied = checked(browser.post("/api/search/problems", json={**request, "client_request_id": "busy"}), 429)
        assert denied["detail"] == "search.account_busy"
    finally:
        release.set()
    ready = await_ready(browser, repo, search_id)
    assert entered == [search_id]
    for index in range(1, 10):
        current = checked(browser.post("/api/search/problems", json={**request, "client_request_id": f"daily-{index}"}))
        await_ready(browser, repo, current["search_id"])
    denied = checked(browser.post("/api/search/problems", json={**request, "client_request_id": "daily-over-limit"}), 429)
    assert denied["detail"] == "search.daily_generation_limit"
    for index in range(3):
        body = {"client_request_id": f"rerun-{index}"}
        checked(browser.post(f"/api/search/problems/{search_id}/lesson", json=body))
        await_ready(browser, repo, search_id)
        assert checked(browser.post(f"/api/search/problems/{search_id}/lesson", json=body))["duplicate"] is True
    denied = checked(browser.post(f"/api/search/problems/{search_id}/lesson", json={"client_request_id": "rerun-over-limit"}), 429)
    assert denied["detail"] == "search.daily_rerun_limit"
    history = checked(browser.get("/api/search/problems", params={"limit": 1, "offset": 0}))
    assert history["user_id"] == owner["id"] and len(history["items"]) == 1
    assert history["items"][0]["problem_id"] == ready["problem_id"]
    assert checked(browser.get("/api/search/problems", params={"limit": 1, "offset": 1}))["items"] == []
    login(other, auth)
    checked(other.get(f"/api/search/problems/{search_id}"), 404)
    assert checked(other.get("/api/search/problems"))["items"] == []
    repo.admission.set_generation_enabled(False)
    denied = checked(browser.post("/api/search/problems", json={**request, "client_request_id": "stopped"}), 503)
    assert denied["detail"] == "search.generation_paused"
    checked(browser.get(f"/api/search/problems/{search_id}"))
    before_delete = tickets(repo)
    deleted = checked(browser.delete(f"/api/search/problems/{search_id}"))["deleted_search_ids"]
    assert len(deleted) == 10
    checked(browser.get(f"/api/search/problems/{search_id}"), 404)
    assert browser.get(page["image_url"]).status_code == 200
    assert checked(browser.get("/api/search/problems"))["items"] == []
    app.state.search_task_runner.reap()
    assert tickets(repo) == before_delete
    assert sum(ticket["consumed"] for ticket in before_delete) == 13
    return [
        "loopback mock-SMS login, authenticated upload and rotation",
        "generation default closed and explicit offline enable",
        "one-account concurrency rejects immediately; identical request is idempotent",
        "ten daily generations succeed; eleventh is rejected without a ticket",
        "three daily reruns succeed; fourth is rejected; finished rerun retry is idempotent",
        "history grouping and limit/offset; second account cannot read first account",
        "expense stop permits reads and deletion; deletion preserves consumed quotas",
        "all ten linked submissions deleted while source page remains available",
    ]


def run_rehearsal(*, port=0):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", port))
        address = f"http://127.0.0.1:{listener.getsockname()[1]}"
        with TemporaryDirectory(prefix="search-admission-http-") as temporary, pytest.MonkeyPatch.context() as monkeypatch:
            config = SearchLimits()
            for key, value in asdict(config).items():
                monkeypatch.setenv("SEARCH_" + key.upper(), str(value))
            fixture = repository_fixture.__wrapped__(Path(temporary))
            repo = next(fixture)
            server, thread = None, None
            forbidden_calls = []

            def forbidden(*_args, **_kwargs):
                forbidden_calls.append(True)
                raise AssertionError("Offline rehearsal forbids real model clients and SMS")

            try:
                calls, classifications = offline_pipeline(monkeypatch)
                monkeypatch.setattr(multimodal_provider, "_default_client_factory", forbidden)
                monkeypatch.setattr(auth_api, "AliyunSms", forbidden)
                monkeypatch.setattr(dev_api.OcrClient, "observe", lambda *_args, **_kwargs: {
                    "width": 100, "height": 100, "lines": [], "layout": [], "latency_ms": {"detect": 0},
                })
                auth = AuthService(repo.db, AuthConfig(mode="mock", environment="test", origin=address,
                    secure=False, secret=secrets.token_urlsafe(48)), MockSms(), clock=repo.clock)
                app = FastAPI()
                app.state.search_repository = repo
                auth_api.install_auth(app, auth=auth)
                app.include_router(dev_api.create_search_router(repo.root))
                server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
                thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
                thread.start()
                deadline = time.monotonic() + 10
                while not server.started:
                    if not thread.is_alive() or time.monotonic() > deadline:
                        raise RuntimeError("Offline loopback HTTP server failed to start")
                    time.sleep(0.02)
                with (
                    httpx.Client(base_url=address, headers={"Origin": address}, trust_env=False, timeout=20) as browser,
                    httpx.Client(base_url=address, headers={"Origin": address}, trust_env=False, timeout=20) as other,
                ):
                    checks = exercise(browser, other, repo, auth, app, monkeypatch)
                assert len(calls) == 10 and len(classifications) == 13
                assert not forbidden_calls
                return {"kind": "offline-search-admission-http/v1", "passed": True, "base_url": address,
                        "port": listener.getsockname()[1], "limits": asdict(config), "checks": checks,
                        "synthetic_recognition_calls": len(calls), "synthetic_course_calls": len(classifications),
                        "paid_calls": 0, "real_sms_calls": 0, "production_deployment": False,
                        "limitations": ["Loopback HTTP, not browser or TLS acceptance.",
                            "Synthetic reviewed extraction, OCR and course fixtures; not real model evidence.",
                            "Temporary isolated PostgreSQL schema; existing 8779 service is not replaced."]}
            finally:
                if server is not None:
                    server.should_exit = True
                if thread is not None:
                    thread.join(timeout=15)
                    if thread.is_alive():
                        raise RuntimeError("Offline HTTP server did not stop")
                try:
                    next(fixture)
                except StopIteration:
                    pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=0, help="Unused loopback port; default chooses an available port")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run_rehearsal(port=args.port)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
