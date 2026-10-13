"""A failed practice restore cannot consume or evict registered tutor sessions."""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from shuxueshuo_server.tutor_demo import api
from shuxueshuo_server.tutor_demo.session import Sessions

from .auth_helpers import TeachingOnlyBudget

USER = '00000000-0000-0000-0000-000000000001'


@pytest.fixture
def session_api(monkeypatch):
    sessions = Sessions()
    monkeypatch.setattr(api, 'Sessions', lambda: sessions)
    monkeypatch.setattr(api, 'service', lambda request: SimpleNamespace(db=object()))
    app = FastAPI()
    app.include_router(api.create_router(object(), TeachingOnlyBudget()))
    app.dependency_overrides[api.require_tutor_user] = lambda: {'id': USER}
    return app, sessions


@pytest.mark.parametrize('status', [404, 409, 503])
@pytest.mark.parametrize('existing', [8, 199])
def test_failed_restore_preserves_all_slots(monkeypatch, session_api, status, existing):
    app, sessions = session_api
    for index in range(existing):
        owner = USER if existing == 8 else f'other-{index}'
        sessions.create('q01', owner_user_id=owner)
    before = dict(sessions.items)

    def restore(db, user, attempt, session, content_version):
        assert session.id not in sessions.items
        assert content_version == 'test-content-version'
        raise HTTPException(status, '练习不能恢复')

    monkeypatch.setattr(api.practice, 'restore_session', restore)
    body = {'lesson_id': 'q01', 'practice_attempt_id': str(uuid4()),
            'content_version': 'test-content-version'}
    with TestClient(app) as client:
        for _ in range(12):
            response = client.post('/api/tutor-demo/sessions', json=body)
            assert response.status_code == status, response.text
            assert sessions.items == before
        # A normal start still has its slot. Successful starts retain the existing caps.
        response = client.post('/api/tutor-demo/sessions', json={'lesson_id': 'q01'})
        assert response.status_code == 201
        assert len(sessions.items) == (8 if existing == 8 else 200)


def test_successful_restore_registers_restored_session(monkeypatch, session_api):
    app, sessions = session_api

    def restore(db, user, attempt, session, content_version):
        assert not sessions.items
        assert content_version == 'test-content-version'
        session.revision = 3
        session.learning_content_version = content_version
        session.learning_practice_attempt_id = attempt
        session.learning_confirmed_choices = {'technique': 'square'}

    monkeypatch.setattr(api.practice, 'restore_session', restore)
    with TestClient(app) as client:
        response = client.post('/api/tutor-demo/sessions', json={
            'lesson_id': 'q01', 'practice_attempt_id': str(uuid4()),
            'content_version': 'test-content-version',
        })
        assert response.status_code == 201
        view = response.json()
        assert view['revision'] == 3
        assert view['content_version'] == 'test-content-version'
        assert view['confirmed_choices'] == {'technique': 'square'}
        assert list(sessions.items) == [view['session_id']]
        assert client.get(f"/api/tutor-demo/sessions/{view['session_id']}").json() == {
            key: value for key, value in view.items()
            if key not in ('content_version', 'confirmed_choices')}


def test_cancelled_restore_does_not_register(monkeypatch, session_api):
    app, sessions = session_api
    existing = sessions.create('q01', owner_user_id=USER)

    async def cancelled(*args):
        raise asyncio.CancelledError

    monkeypatch.setattr(api, 'run_in_threadpool', cancelled)
    start = next(route.endpoint for route in app.routes
                 if route.path == '/api/tutor-demo/sessions')
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(start(api.Start(practice_attempt_id=uuid4(),
                                  content_version='test-content-version'), {'id': USER}, None))
    assert sessions.items == {existing.id: existing}


def test_bound_session_requires_version_before_preparing_a_session(session_api):
    app, sessions = session_api
    with TestClient(app) as client:
        response = client.post('/api/tutor-demo/sessions', json={
            'lesson_id': 'q01', 'practice_attempt_id': str(uuid4()),
        })
    assert response.status_code == 422
    assert not sessions.items
