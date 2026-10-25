"""Real PostgreSQL HTTP admission with explicit offline extraction/course fixtures."""

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier, Event, Lock

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from shuxueshuo_server.auth.api import cookie_name
from shuxueshuo_server.problem_understanding.workflow_ledger import save
from shuxueshuo_server.search import dev_api
from shuxueshuo_server.search.admission import TICKETS
from shuxueshuo_server.search.repository import SUBMISSIONS
from tests.search.test_private_api import login, recorded_pipeline, upload, wait_ready
from tests.search.test_private_api import private_app as private_app_fixture
from tests.search.test_private_api import repository as repository_fixture


@pytest.fixture
def repository(tmp_path):
    yield from repository_fixture.__wrapped__(tmp_path)


@pytest.fixture
def private_app(repository, monkeypatch):
    return private_app_fixture.__wrapped__(repository, monkeypatch)


def eventually(predicate):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    pytest.fail("Offline admission operation did not reach its expected state")


def actor(client, auth):
    user, token = login(client, auth)
    page = upload(client)
    return {"user": user, "page": page["page_id"], "headers": {
        "Origin": auth.config.origin, "X-Search-User": user["id"],
        "Cookie": f"{cookie_name(auth.config)}={token}",
    }}


def generate(client, owner, request_id="generation"):
    return client.post("/api/search/problems", headers=owner["headers"], json={
        "page_id": owner["page"], "box": [0, 0, 1, 1], "client_request_id": request_id,
    })


def accept_generation(client, owner, request_id="generation"):
    response = generate(client, owner, request_id)
    assert response.status_code == 200, response.text
    return response.json()["search_id"]


def tickets(repo, *, search_id=None):
    query = sa.select(TICKETS).order_by(TICKETS.c.accepted_at, TICKETS.c.id)
    if search_id is not None:
        query = query.where(TICKETS.c.search_id == search_id)
    with repo.db.connect() as connection:
        return list(connection.execute(query).mappings())


def settle(repo):
    eventually(lambda: all(row["state"] not in {"running", "reserved"} for row in tickets(repo)))


def submission_count(repo):
    with repo.db.connect() as connection:
        return connection.scalar(sa.select(sa.func.count()).select_from(SUBMISSIONS))


def offline_pipeline(monkeypatch):
    calls = recorded_pipeline(monkeypatch)
    classifications = []

    def classify(directory, *_args, **_kwargs):
        classifications.append(directory.name)
        next_attempt = len(list(directory.glob("stage-two-*/stage-two-result.json"))) + 1
        save(directory / f"stage-two-{next_attempt}/stage-two-result.json", {
            "status": "resolved", "goals": [{"status": "resolved"}],
        })

    monkeypatch.setattr(dev_api, "run_stage_two", classify)
    return calls, classifications


def block_recognition(monkeypatch):
    original = dev_api.run_question_image
    entered, release, lock = [], Event(), Lock()

    def blocked(*args, **kwargs):
        with lock:
            entered.append(kwargs["problem_id"])
        assert release.wait(30), "Offline recognition fixture was not released"
        return original(*args, **kwargs)

    monkeypatch.setattr(dev_api, "run_question_image", blocked)
    return entered, release


def complete_generation(client, repo, owner, request_id="generation"):
    search_id = accept_generation(client, owner, request_id)
    row = wait_ready(repo, owner["user"], search_id)
    settle(repo)
    return search_id, row


def test_two_running_four_waiting_rejects_seventh_without_submission(private_app, repository, monkeypatch):
    calls, _ = offline_pipeline(monkeypatch)
    entered, release = block_recognition(monkeypatch)
    app, auth = private_app
    with TestClient(app, base_url=auth.config.origin) as client:
        owners = [actor(client, auth) for _ in range(7)]
        try:
            identifiers = [accept_generation(client, owner) for owner in owners[:6]]
            eventually(lambda: len(entered) == 2)
            rows = tickets(repository)
            assert sum(row["state"] == "running" for row in rows) == 2
            assert sum(row["state"] == "reserved" for row in rows) == 4
            assert sum(row["consumed"] for row in rows) == 2
            refused = generate(client, owners[6])
            assert refused.status_code == 429, refused.text
            assert refused.json()["detail"] == "search.queue_full"
            assert refused.headers["cache-control"] == "no-store"
            assert submission_count(repository) == 6
            assert len(tickets(repository)) == 6
        finally:
            release.set()
        settle(repository)
        assert sorted(calls) == sorted(identifiers)


@pytest.mark.parametrize("operation", ["generation", "rerun", "continuation"])
def test_account_concurrency_is_shared_across_generation_and_lesson_operations(
    private_app, repository, monkeypatch, operation,
):
    offline_pipeline(monkeypatch)
    app, auth = private_app
    with TestClient(app, base_url=auth.config.origin) as client:
        owner = actor(client, auth)
        ready_id, row = complete_generation(client, repository, owner, "ready")
        entered, release = block_recognition(monkeypatch)
        try:
            active_id = accept_generation(client, owner, "active")
            eventually(lambda: entered == [active_id])
            if operation == "generation":
                response = generate(client, owner, "conflicting")
            elif operation == "rerun":
                response = client.post(f"/api/search/problems/{ready_id}/lesson", headers=owner["headers"],
                                       json={"client_request_id": "rerun"})
            else:
                output = row["path"] / "stage-two-1/stage-three"
                run_id = dev_api.stage_three.read(output / "run.json")["run_id"]
                monkeypatch.setattr(dev_api.stage_three, "fingerprint", lambda: {"fixture": "b" * 64})
                monkeypatch.setattr(dev_api.stage_three, "has_pending_interactions", lambda _output: True)
                response = client.post(f"/api/search/problems/{ready_id}/lesson/{run_id}/resume",
                                       headers=owner["headers"])
            assert response.status_code == 429, response.text
            assert response.json()["detail"] == "search.account_busy"
            assert len(tickets(repository)) == 2
            assert submission_count(repository) == 2
            with repository.storage.lifecycle_lock(ready_id):
                pass
        finally:
            release.set()


def test_simultaneous_idempotent_requests_start_and_charge_once(private_app, repository, monkeypatch):
    calls, _ = offline_pipeline(monkeypatch)
    entered, release = block_recognition(monkeypatch)
    app, auth = private_app
    with TestClient(app, base_url=auth.config.origin) as client:
        owner = actor(client, auth)
        barrier = Barrier(2)

        def submit():
            barrier.wait(timeout=10)
            return generate(client, owner, "same-request")

        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = [future.result(timeout=10) for future in [pool.submit(submit), pool.submit(submit)]]
            assert [response.status_code for response in responses] == [200, 200]
            identifiers = {response.json()["search_id"] for response in responses}
            assert len(identifiers) == 1
            eventually(lambda: len(entered) == 1)
            assert submission_count(repository) == 1
            rows = tickets(repository)
            assert len(rows) == 1 and rows[0]["consumed"]
        finally:
            release.set()
        settle(repository)
        assert len(calls) == 1


def test_finished_rerun_request_remains_idempotent(private_app, repository, monkeypatch):
    calls, classifications = offline_pipeline(monkeypatch)
    app, auth = private_app
    with TestClient(app, base_url=auth.config.origin) as client:
        owner = actor(client, auth)
        search_id, _ = complete_generation(client, repository, owner)
        url = f"/api/search/problems/{search_id}/lesson"
        response = client.post(url, headers=owner["headers"], json={"client_request_id": "same-rerun"})
        assert response.status_code == 200, response.text
        settle(repository)
        repeated = client.post(url, headers=owner["headers"], json={"client_request_id": "same-rerun"})
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["duplicate"] is True
        assert len(calls) == 1 and len(classifications) == 2
        rows = tickets(repository)
        assert [row["kind"] for row in rows].count("rerun") == 1
        assert all(row["consumed"] and row["state"] == "finished" for row in rows)


@pytest.mark.parametrize("generation_enabled", [True, False])
def test_deleted_generation_request_is_retired_without_new_charge_or_submission(
    private_app, repository, monkeypatch, generation_enabled,
):
    calls, _ = offline_pipeline(monkeypatch)
    app, auth = private_app
    with TestClient(app, base_url=auth.config.origin) as client:
        owner = actor(client, auth)
        search_id, _ = complete_generation(client, repository, owner, "retired-request")
        deleted = client.delete(f"/api/search/problems/{search_id}", headers=owner["headers"])
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["deleted_search_ids"] == [search_id]
        assert submission_count(repository) == 0
        repository.admission.set_generation_enabled(generation_enabled)
        barrier = Barrier(2)

        def retry_deleted():
            barrier.wait(timeout=10)
            return generate(client, owner, "retired-request")

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = [future.result(timeout=10) for future in [pool.submit(retry_deleted), pool.submit(retry_deleted)]]
        for response in responses:
            assert response.status_code == 409, response.text
            assert response.json()["detail"] == "search.request_retired"
            assert response.headers["cache-control"] == "no-store"
        assert submission_count(repository) == 0
        assert len(tickets(repository)) == 1
        assert tickets(repository)[0]["consumed"]
        assert calls == [search_id]
        repository.admission.set_generation_enabled(True)
        replacement_id, _ = complete_generation(client, repository, owner, "fresh-request")
        assert replacement_id != search_id
        other_owner = actor(client, auth)
        other_id, _ = complete_generation(client, repository, other_owner, "retired-request")
        assert other_id not in {search_id, replacement_id}
        assert len(tickets(repository)) == 3
        assert sum(row["consumed"] for row in tickets(repository)) == 3


def test_stop_cancels_waiting_without_charge_and_keeps_reads_and_delete(private_app, repository, monkeypatch):
    calls, _ = offline_pipeline(monkeypatch)
    entered, release = block_recognition(monkeypatch)
    app, auth = private_app
    with TestClient(app, base_url=auth.config.origin) as client:
        owners = [actor(client, auth) for _ in range(4)]
        try:
            identifiers = [accept_generation(client, owner) for owner in owners[:3]]
            eventually(lambda: len(entered) == 2)
            cancelled = repository.admission.set_generation_enabled(False)
            assert len(cancelled) == 1
            app.state.search_task_runner.reap()
            queued = tickets(repository, search_id=identifiers[2])[0]
            assert queued["state"] == "cancelled" and not queued["consumed"]
            paused = generate(client, owners[3])
            assert paused.status_code == 503, paused.text
            assert paused.json()["detail"] == "search.generation_paused"
            detail = client.get(f"/api/search/problems/{identifiers[2]}", headers=owners[2]["headers"])
            assert detail.status_code == 200, detail.text
            assert client.get("/api/search/problems", headers=owners[2]["headers"]).status_code == 200
            deleted = client.delete(f"/api/search/problems/{identifiers[2]}", headers=owners[2]["headers"])
            assert deleted.status_code == 200, deleted.text
            with repository.storage.cleanup_lock(identifiers[2]):
                pass
            repository.admission.set_generation_enabled(True)
            app.state.search_task_runner.reap()
            assert tickets(repository, search_id=identifiers[2])[0]["state"] == "cancelled"
        finally:
            release.set()
        settle(repository)
        assert identifiers[2] not in calls
        assert sum(row["consumed"] for row in tickets(repository)) == 2


def test_stop_cancels_waiting_rerun_and_releases_both_leases(private_app, repository, monkeypatch):
    _, classifications = offline_pipeline(monkeypatch)
    app, auth = private_app
    with TestClient(app, base_url=auth.config.origin) as client:
        owner = actor(client, auth)
        search_id, row = complete_generation(client, repository, owner)
        blockers = [actor(client, auth) for _ in range(2)]
        entered, release = block_recognition(monkeypatch)
        try:
            for blocker in blockers:
                accept_generation(client, blocker)
            eventually(lambda: len(entered) == 2)
            response = client.post(f"/api/search/problems/{search_id}/lesson", headers=owner["headers"],
                                   json={"client_request_id": "queued-rerun"})
            assert response.status_code == 200, response.text
            assert (row["path"] / dev_api.stage_three.RETRY_INTENT).is_file()
            repository.admission.set_generation_enabled(False)
            app.state.search_task_runner.reap()
            rerun = next(ticket for ticket in tickets(repository, search_id=search_id) if ticket["kind"] == "rerun")
            assert rerun["state"] == "cancelled" and not rerun["consumed"]
            assert not (row["path"] / dev_api.stage_three.RETRY_INTENT).exists()
            with repository.storage.lifecycle_lock(search_id):
                lease = dev_api.stage_three.acquire_problem(row["path"])
                dev_api.stage_three.release_problem(lease)
            assert classifications.count(search_id) == 1
        finally:
            release.set()


def test_stop_switch_allows_local_continuation_without_paid_daily_charge(private_app, repository, monkeypatch):
    calls, classifications = offline_pipeline(monkeypatch)
    app, auth = private_app
    with TestClient(app, base_url=auth.config.origin) as client:
        owner = actor(client, auth)
        search_id, row = complete_generation(client, repository, owner)
        output = row["path"] / "stage-two-1/stage-three"
        run_id = dev_api.stage_three.read(output / "run.json")["run_id"]
        pending = [True]
        resumed = []
        monkeypatch.setattr(dev_api.stage_three, "fingerprint", lambda: {"fixture": "b" * 64})
        monkeypatch.setattr(dev_api.stage_three, "has_pending_interactions", lambda _output: pending[0])

        def resume(directory, selected_run, **_kwargs):
            resumed.append((directory.name, selected_run))
            pending[0] = False

        monkeypatch.setattr(dev_api.stage_three, "resume_stage_three", resume)
        repository.admission.set_generation_enabled(False)
        response = client.post(f"/api/search/problems/{search_id}/lesson/{run_id}/resume", headers=owner["headers"])
        assert response.status_code == 200, response.text
        settle(repository)
        assert resumed == [(search_id, run_id)]
        continuation = next(ticket for ticket in tickets(repository) if ticket["kind"] == "continuation")
        assert continuation["state"] == "finished" and not continuation["consumed"]
        assert len(calls) == 1 and len(classifications) == 1


@pytest.mark.parametrize("operation", ["delete", "expire"])
def test_waiting_deleted_or_expired_job_releases_lifecycle_before_cleanup(
    private_app, repository, monkeypatch, operation,
):
    calls, _ = offline_pipeline(monkeypatch)
    entered, release = block_recognition(monkeypatch)
    app, auth = private_app
    with TestClient(app, base_url=auth.config.origin) as client:
        owners = [actor(client, auth) for _ in range(3)]
        try:
            identifiers = [accept_generation(client, owner) for owner in owners]
            eventually(lambda: len(entered) == 2)
            queued_id = identifiers[2]
            row = repository.submission(owners[2]["user"], queued_id)
            if operation == "delete":
                response = client.delete(f"/api/search/problems/{queued_id}", headers=owners[2]["headers"])
                assert response.status_code == 200, response.text
            else:
                repository.test_time[0] = row["expires_at"]
            app.state.search_task_runner.reap()
            with repository.storage.cleanup_lock(queued_id):
                pass
            repository.cleanup()
            assert not row["path"].exists()
            queued = tickets(repository, search_id=queued_id)[0]
            assert queued["state"] == "cancelled" and not queued["consumed"]
            assert len(entered) == 2
        finally:
            release.set()
        settle(repository)
        assert queued_id not in calls
        assert not row["path"].exists()


@pytest.mark.parametrize("scope", ["account", "global"])
@pytest.mark.parametrize("kind", ["generation", "rerun"])
def test_daily_limit_rejects_without_creating_submission_or_ticket(private_app, repository, monkeypatch, scope, kind):
    offline_pipeline(monkeypatch)
    repository.admission.config = replace(repository.admission.config, **{f"{kind}_{scope}_daily": 1})
    app, auth = private_app
    with TestClient(app, base_url=auth.config.origin) as client:
        owner = actor(client, auth)
        search_id, _ = complete_generation(client, repository, owner)
        url = f"/api/search/problems/{search_id}/lesson"
        if kind == "rerun":
            response = client.post(url, headers=owner["headers"], json={"client_request_id": "first-rerun"})
            assert response.status_code == 200, response.text
            settle(repository)
        before = tickets(repository)
        if kind == "generation":
            response = generate(client, owner, "over-limit")
        else:
            response = client.post(url, headers=owner["headers"], json={"client_request_id": "over-limit"})
        assert response.status_code == 429, response.text
        prefix = "daily" if scope == "account" else "global"
        assert response.json()["detail"] == f"search.{prefix}_{kind}_limit"
        assert submission_count(repository) == 1
        assert tickets(repository) == before


def test_polling_and_history_never_reserve_or_consume_quota(private_app, repository, monkeypatch):
    calls, classifications = offline_pipeline(monkeypatch)
    app, auth = private_app
    with TestClient(app, base_url=auth.config.origin) as client:
        owner = actor(client, auth)
        search_id, _ = complete_generation(client, repository, owner)
        before = tickets(repository)
        for _ in range(4):
            assert client.get("/api/search/problems", headers=owner["headers"]).status_code == 200
            assert client.get(f"/api/search/problems/{search_id}", headers=owner["headers"]).status_code == 200
        assert tickets(repository) == before
        assert len(calls) == 1 and len(classifications) == 1
