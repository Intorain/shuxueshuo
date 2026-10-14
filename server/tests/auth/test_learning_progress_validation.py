"""Reject invalid batch scopes before querying personal data, without a database."""

from contextlib import contextmanager
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from shuxueshuo_server.auth.api import require_user, service
from shuxueshuo_server.learning import graph_api

USER_ID = '00000000-0000-0000-0000-000000000001'
URL = '/api/learning/progress/batch'


@pytest.fixture
def scope_client(monkeypatch):
    app = FastAPI()
    app.include_router(graph_api.router)
    app.dependency_overrides[require_user] = lambda: {'id': USER_ID}
    app.dependency_overrides[service] = lambda: SimpleNamespace(db=object())
    calls = []

    @contextmanager
    def transaction(_db):
        calls.append('transaction')
        yield object()

    def statuses(_connection, user_id):
        assert user_id == UUID(USER_ID)
        return []

    def progress(_connection, scopes, node_statuses):
        assert node_statuses == []
        calls.append(list(scopes))
        return [{'scope': scope} for scope in scopes]

    monkeypatch.setattr(graph_api, 'transaction', transaction)
    monkeypatch.setattr(graph_api, 'lock', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(graph_api.drills, 'statuses', statuses)
    monkeypatch.setattr(graph_api.associations, 'content_metadata', lambda _c: {'content_version': 'test-version'})
    monkeypatch.setattr(graph_api.associations, 'directory_progress_batch', progress)
    with TestClient(app) as client:
        yield client, calls


@pytest.mark.parametrize(('scopes', 'error_location', 'error_type'), [
    ([], ['query', 'scope'], 'missing'),
    ([''], ['query', 'scope', 0], 'string_too_short'),
    (['s' * 101], ['query', 'scope', 0], 'string_too_long'),
    (['section-2-1', 's' * 101], ['query', 'scope', 1], 'string_too_long'),
    (['section-2-1', ''], ['query', 'scope', 1], 'string_too_short'),
    (['section-2-1'] * 101, ['query', 'scope'], 'too_long'),
])
def test_invalid_scope_is_rejected_before_querying(scope_client, scopes, error_location, error_type):
    client, calls = scope_client
    response = client.get(URL, params=[('scope', scope) for scope in scopes])

    assert response.status_code == 422
    assert any(error['loc'] == error_location and error['type'] == error_type
               for error in response.json()['detail'])
    assert calls == []


@pytest.mark.parametrize('scopes', [
    ['s'],
    ['s' * 100],
    [f'section-{i}' for i in range(100)],
])
def test_scope_length_and_count_boundaries_reach_service(scope_client, scopes):
    client, calls = scope_client
    response = client.get(URL, params=[('scope', scope) for scope in scopes])

    assert response.status_code == 200
    assert response.json() == {'content_version': 'test-version',
                               'progress': [{'scope': scope} for scope in scopes]}
    assert calls == ['transaction', scopes]


def test_batch_still_requires_login(scope_client):
    client, calls = scope_client

    def unauthenticated():
        raise HTTPException(401, '请先登录。')

    client.app.dependency_overrides[require_user] = unauthenticated
    response = client.get(URL, params={'scope': 'section-2-1'})

    assert response.status_code == 401
    assert calls == []


def test_batch_still_rejects_account_switch(scope_client):
    client, calls = scope_client
    response = client.get(URL, params={'scope': 'section-2-1'},
                          headers={'X-Learning-User': 'another-account'})

    assert response.status_code == 409
    assert calls == []
