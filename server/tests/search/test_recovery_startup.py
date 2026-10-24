"""Real journal recovery through the production API lifespan, with mock SMS."""

import secrets

import pytest
from fastapi.testclient import TestClient

from shuxueshuo_server.search import application
from shuxueshuo_server.search.recovery import STATE
from shuxueshuo_server.search.repository import SearchError, SearchRepository
from tests.search.test_application import production_app as production_app_fixture
from tests.search.test_application import repository as repository_fixture
from tests.search.test_private_api import login
from tests.search.test_repository import student, submission

production_app = production_app_fixture
repository = repository_fixture


def use_real_recovery(repository, monkeypatch):
    def create(database, _root):
        return SearchRepository(database, repository.root, clock=repository.clock)

    monkeypatch.setattr(application, 'SearchRepository', create)


@pytest.mark.parametrize('fragment', [b'', b'{"authority_id":'])
def test_first_start_fragment_does_not_block_product_or_login(production_app, repository, monkeypatch, fragment):
    header = repository.recovery.path.read_bytes()
    with repository.db.begin() as connection:
        connection.execute(STATE.update().values(initialized=False, sequence=0, replayed_sequence=0, digest=''))
    repository.recovery.path.write_bytes(fragment)
    use_real_recovery(repository, monkeypatch)
    with TestClient(production_app.app, base_url=production_app.auth.config.origin) as client:
        assert repository.recovery.path.read_bytes() == header
        assert client.get('/api/health').json()['accepting'] is True
        assert client.get('/api/product/v1/health').status_code == 200
        user, _token = login(client, production_app.auth)
        assert client.get('/api/auth/me').json()['user']['id'] == user['id']
        assert client.get('/api/search/problems').status_code == 200


def test_torn_tail_recovers_product_health_login_and_search(production_app, repository, monkeypatch):
    owner = student(repository)
    removed, _ = submission(repository, owner)
    retained, _ = submission(repository, owner)
    repository.delete(owner, removed['id'])
    complete = repository.recovery.path.read_bytes()
    with repository.recovery.path.open('ab') as stream:
        stream.write(b'{"sequence":2,"previous_digest":')
    use_real_recovery(repository, monkeypatch)
    with TestClient(production_app.app, base_url=production_app.auth.config.origin) as client:
        assert repository.recovery.path.read_bytes() == complete
        assert client.get('/api/health').json()['accepting'] is True
        assert client.get('/api/product/v1/health').status_code == 200
        client.headers['Origin'] = production_app.auth.config.origin
        phone = '139' + ''.join(str(secrets.randbelow(10)) for _index in range(8))
        sent = client.post('/api/auth/sms/send', json={'phone': phone})
        assert sent.status_code == 200, sent.text
        challenge = sent.json()['challenge_id']
        verified = client.post('/api/auth/sms/verify', json={
            'phone': phone, 'challenge_id': challenge,
            'code': production_app.auth.sms.messages[challenge][1],
        })
        assert verified.status_code == 200, verified.text
        user = verified.json()['user']
        assert client.get('/api/auth/me').json()['user']['id'] == user['id']
        client.headers['X-Search-User'] = user['id']
        assert client.get('/api/search/problems').json()['items'] == []
        assert client.get('/api/search/problems/' + retained['id']).status_code == 404
        recovered = production_app.app.state.search_repository
        assert recovered.submission(owner, retained['id'])['recognition_status'] == 'interrupted'
        with pytest.raises(SearchError, match='search.not_found'):
            recovered.submission(owner, removed['id'])
    assert production_app.closed.is_set()


def test_confirmed_record_damage_still_blocks_production_startup(production_app, repository, monkeypatch):
    owner = student(repository)
    row, _ = submission(repository, owner)
    repository.delete(owner, row['id'])
    damaged = repository.recovery.path.read_bytes()[:-1]
    repository.recovery.path.write_bytes(damaged)
    use_real_recovery(repository, monkeypatch)
    with pytest.raises(SearchError, match='recovery.journal_behind'):
        with TestClient(production_app.app, base_url=production_app.auth.config.origin):
            pytest.fail('A confirmed damaged deletion must not start serving')
    assert repository.recovery.path.read_bytes() == damaged


def test_restore_lock_returns_http_503_without_confirming_deletion(production_app, repository, monkeypatch):
    use_real_recovery(repository, monkeypatch)
    with TestClient(production_app.app, base_url=production_app.auth.config.origin) as client:
        user, _token = login(client, production_app.auth)
        row, _ = submission(repository, user)
        with repository.recovery.locked_snapshot():
            response = client.delete('/api/search/problems/' + row['id'])
            assert response.status_code == 503
            assert response.json()['detail'] == 'recovery.busy'
            assert repository.submission(user, row['id'])['id'] == row['id']
        response = client.delete('/api/search/problems/' + row['id'])
        assert response.status_code == 200
        assert response.json()['deleted_search_ids'] == [row['id']]
