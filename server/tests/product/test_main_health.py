"""Public liveness reports admission booleans without exposing or clearing state."""

import runpy
from types import SimpleNamespace

import dotenv
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def health_app(tmp_path, monkeypatch):
    monkeypatch.setenv('REVIEW_BACKEND', 'product')
    monkeypatch.setenv('PRODUCT_MODE', 'server')
    monkeypatch.setenv('AUTH_SMS_MODE', 'disabled')
    monkeypatch.setenv('PRODUCT_EXECUTION_STORAGE_CONTEXT_REQUIRED', '1')
    monkeypatch.setattr(dotenv, 'load_dotenv', lambda *_args, **_kwargs: False)
    app = runpy.run_module('shuxueshuo_server.main')['app']
    app.state.product = SimpleNamespace(settings=SimpleNamespace(root=tmp_path))
    marker = tmp_path / 'locks/services-draining'
    marker.parent.mkdir()
    app.state.search_drain_path = marker
    app.state.search_accepting = True
    client = TestClient(app)
    try:
        yield app, marker, client
    finally:
        client.close()


@pytest.mark.parametrize('memory_accepting', [False, True])
@pytest.mark.parametrize('marker_exists', [False, True])
@pytest.mark.parametrize('path_source', ['search', 'product'])
def test_liveness_reports_current_admission_without_exposing_private_paths(
    health_app, memory_accepting, marker_exists, path_source,
):
    app, marker, client = health_app
    if path_source == 'product':
        del app.state.search_drain_path
    app.state.search_accepting = memory_accepting
    if marker_exists:
        marker.write_text('operator requested drain')
    draining = marker_exists or not memory_accepting
    response = client.get('/api/health')
    assert response.status_code == 200
    assert response.json() == {'status': 'ok', 'accepting': not draining, 'draining': draining}
    assert response.headers['cache-control'] == 'no-store'
    assert str(marker.parent.parent) not in response.text
    assert marker.exists() is marker_exists
    assert app.state.search_accepting is memory_accepting
    if marker_exists:
        assert marker.read_text() == 'operator requested drain'


def test_liveness_observes_marker_changes_without_restart(health_app):
    _app, marker, client = health_app
    assert client.get('/api/health').json()['accepting'] is True
    marker.touch()
    assert client.get('/api/health').json() == {'status': 'ok', 'accepting': False, 'draining': True}
    marker.unlink()
    assert client.get('/api/health').json() == {'status': 'ok', 'accepting': True, 'draining': False}


def test_liveness_does_not_claim_admission_when_marker_is_unreadable(health_app):
    app, _marker, client = health_app

    def unreadable():
        raise PermissionError('/private/operator/path')

    app.state.search_drain_path = SimpleNamespace(exists=unreadable)
    response = client.get('/api/health')
    assert response.status_code == 200
    assert response.json() == {'status': 'ok', 'accepting': False, 'draining': True}
    assert '/private/operator/path' not in response.text
