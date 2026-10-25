"""Search model entry points require the task runner's admission context."""

from contextlib import nullcontext

import pytest
from fastapi.testclient import TestClient

from shuxueshuo_server.search import task_runner
from shuxueshuo_server.solver.extraction.request_guard import (
    require_model_request_scope,
)
from tests.search.test_generation_admission_api import (
    accept_generation,
    actor,
    complete_generation,
    offline_pipeline,
    settle,
    tickets,
)
from tests.search.test_private_api import private_app as private_app_fixture
from tests.search.test_private_api import repository as repository_fixture


@pytest.fixture
def repository(tmp_path):
    yield from repository_fixture.__wrapped__(tmp_path)


@pytest.fixture
def private_app(repository, monkeypatch):
    return private_app_fixture.__wrapped__(repository, monkeypatch)


def count_factories(monkeypatch):
    calls = []

    def extraction(name):
        calls.append(('extraction', name))
        require_model_request_scope()
        return lambda: object()

    def selection():
        calls.append(('selection', 'deepseek'))
        require_model_request_scope()
        return object()

    monkeypatch.setattr('shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory', extraction)
    monkeypatch.setattr('shuxueshuo_server.graph_lesson.stage_two.selection.live_provider_factory', selection)
    return calls


@pytest.mark.parametrize('operation', ['generation', 'rerun'])
def test_unscoped_search_job_never_creates_a_live_provider(
    private_app, repository, monkeypatch, operation, caplog,
):
    recognized, classified = offline_pipeline(monkeypatch)
    app, auth = private_app
    with TestClient(app, base_url=auth.config.origin) as client:
        owner = actor(client, auth)
        if operation == 'rerun':
            search_id, _row = complete_generation(client, repository, owner, 'ready')
        recognized.clear()
        classified.clear()
        factory_calls = count_factories(monkeypatch)
        monkeypatch.setattr(task_runner, 'model_request_scope', lambda _guard: nullcontext())
        if operation == 'generation':
            search_id = accept_generation(client, owner, 'unscoped')
        else:
            response = client.post(f'/api/search/problems/{search_id}/lesson', headers=owner['headers'],
                                   json={'client_request_id': 'unscoped'})
            assert response.status_code == 200, response.text
        settle(repository)
        row = repository.submission(owner['user'], search_id)
        status = 'recognition_status' if operation == 'generation' else 'lesson_status'
        assert row[status] == 'failed'
        assert 'ModelRequestScopeRequired: model.request_scope_required' in caplog.text
        assert factory_calls == []
        assert recognized == []
        assert classified == []
        assert tickets(repository)[-1]['state'] == 'finished'


def test_admitted_search_jobs_supply_scope_to_both_provider_factories(private_app, repository, monkeypatch):
    recognized, classified = offline_pipeline(monkeypatch)
    factory_calls = count_factories(monkeypatch)
    app, auth = private_app
    with TestClient(app, base_url=auth.config.origin) as client:
        owner = actor(client, auth)
        search_id, _row = complete_generation(client, repository, owner)
        assert factory_calls == [('extraction', 'deepseek'), ('selection', 'deepseek')]
        assert recognized == [search_id]
        assert classified == [search_id]
        response = client.post(f'/api/search/problems/{search_id}/lesson', headers=owner['headers'],
                               json={'client_request_id': 'scoped-rerun'})
        assert response.status_code == 200, response.text
        settle(repository)
        assert repository.submission(owner['user'], search_id)['lesson_status'] == 'ready'
        assert factory_calls == [('extraction', 'deepseek'), ('selection', 'deepseek'), ('selection', 'deepseek')]
        assert recognized == [search_id]
        assert classified == [search_id, search_id]
