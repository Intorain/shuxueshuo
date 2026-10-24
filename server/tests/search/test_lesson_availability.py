"""Lost lesson files and archived SQLite runs never become resumable UI state."""

import json

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from shuxueshuo_server.product.models import metadata
from shuxueshuo_server.search import dev_api
from tests.search.test_private_api import login
from tests.search.test_private_api import private_app as private_app_fixture
from tests.search.test_repository import (
    SUBMISSIONS,
    identity,
    lesson_artifacts,
    submission,
)
from tests.search.test_repository import repository as repository_fixture

private_app = private_app_fixture
repository = repository_fixture


@pytest.mark.parametrize('missing', [
    'postgres_run', 'legacy_sqlite', 'result.json', 'crop.json', 'question.png',
    'stage-two-1/stage-two-result.json', 'stage-two-1/stage-three/run.json',
    'stage-two-1/stage-three/frozen.json', 'stage-two-1/stage-three/stage-three-result.json',
])
def test_unavailable_ready_lesson_is_safe_to_read_and_refuses_execution(private_app, repository, monkeypatch, missing):
    calls = []

    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError('unavailable lesson must not start work or call a provider')

    monkeypatch.setattr(dev_api, 'run_question_image', forbidden)
    monkeypatch.setattr(dev_api, 'run_stage_two', forbidden)
    monkeypatch.setattr(dev_api.stage_three, 'run_stage_three', forbidden)
    monkeypatch.setattr(dev_api.stage_three, 'resume_stage_three', forbidden)
    monkeypatch.setattr(dev_api.stage_three, 'reserve_retry', forbidden)
    monkeypatch.setattr('shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory', forbidden)
    monkeypatch.setattr('shuxueshuo_server.graph_lesson.stage_two.selection.live_provider_factory', forbidden)
    app, auth = private_app
    with TestClient(app, base_url=auth.config.origin) as client:
        user, _token = login(client, auth)
        row, _created = submission(repository, user)
        repository.link_identity(row['id'], identity())
        lesson_artifacts(repository, row)
        repository.set_state(row['id'], recognition_state='reviewed', lesson_state='ready')
        output = row['path'] / 'stage-two-1/stage-three'
        run_id = json.loads((output / 'run.json').read_text())['run_id']
        if missing in {'postgres_run', 'legacy_sqlite'}:
            runs = metadata.tables['lesson_runs']
            with repository.db.begin() as connection:
                connection.execute(runs.delete().where(runs.c.run_id == run_id))
            if missing == 'legacy_sqlite':
                (output / 'events.sqlite3').write_bytes(b'archived SQLite is not runtime authority')
        else:
            (row['path'] / missing).unlink()
        before = {str(path.relative_to(row['path'])) for path in row['path'].rglob('*')}
        history = client.get('/api/search/problems').json()['items'][0]
        assert history['latest_status'] == history['lesson_status'] == 'unavailable'
        assert history['lesson_available'] is False
        response = client.get('/api/search/problems/' + row['id'])
        assert response.status_code == 200, response.text
        detail = response.json()
        assert detail['status'] == detail['lesson_status'] == 'unavailable'
        assert detail['lesson'] is None and detail['statement']
        for action in ('', '/start', '/' + run_id + '/resume'):
            response = client.post(f"/api/search/problems/{row['id']}/lesson{action}")
            assert response.status_code == 409, response.text
            assert response.json() == {'detail': 'lesson.execution_unavailable'}
        assert calls == []
        assert {str(path.relative_to(row['path'])) for path in row['path'].rglob('*')} == before
        with repository.db.connect() as connection:
            assert connection.scalar(sa.select(SUBMISSIONS.c.lesson_status).where(SUBMISSIONS.c.id == row['id'])) == 'ready'


@pytest.mark.parametrize('missing', ['postgres_run', 'result.json', 'stage-three-result.json'])
def test_retry_rechecks_availability_after_acquiring_lifecycle_lock(private_app, repository, monkeypatch, missing):
    calls = []

    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError('lost lesson must not reserve a retry or start work')

    monkeypatch.setattr(dev_api, 'run_stage_two', forbidden)
    monkeypatch.setattr(dev_api.stage_three, 'reserve_retry', forbidden)
    monkeypatch.setattr('shuxueshuo_server.graph_lesson.stage_two.selection.live_provider_factory', forbidden)
    app, auth = private_app
    with TestClient(app, base_url=auth.config.origin) as client:
        user, _token = login(client, auth)
        row, _created = submission(repository, user)
        lesson_artifacts(repository, row)
        (row['path'] / 'result.json').write_text('{"status":"reviewed_candidate"}')
        repository.set_state(row['id'], recognition_state='reviewed', lesson_state='ready')
        assert repository.submission(user, row['id'])['lesson_status'] == 'ready'
        output = row['path'] / 'stage-two-1/stage-three'
        run_id = json.loads((output / 'run.json').read_text())['run_id']
        original_lock = repository.storage.lifecycle_lock
        leases = []

        def lose_artifact(search_id, **kwargs):
            lease = original_lock(search_id, **kwargs)
            leases.append(lease)
            try:
                if missing == 'postgres_run':
                    runs = metadata.tables['lesson_runs']
                    with repository.db.begin() as connection:
                        connection.execute(runs.delete().where(runs.c.run_id == run_id))
                elif missing == 'result.json':
                    (row['path'] / missing).unlink()
                else:
                    (output / missing).unlink()
            except BaseException:
                lease.close()
                raise
            return lease

        monkeypatch.setattr(repository.storage, 'lifecycle_lock', lose_artifact)
        response = client.post(f"/api/search/problems/{row['id']}/lesson")
        assert response.status_code == 409, response.text
        assert response.json() == {'detail': 'lesson.execution_unavailable'}
        assert response.headers['cache-control'] == 'no-store'
        assert calls == []
        assert len(leases) == 1 and leases[0].stream.closed
        with original_lock(row['id']):
            pass
        assert not (row['path'] / dev_api.stage_three.RETRY_INTENT).exists()
        assert not (row['path'] / 'stage-two-2').exists()
        with repository.db.connect() as connection:
            assert connection.scalar(sa.select(SUBMISSIONS.c.lesson_status).where(SUBMISSIONS.c.id == row['id'])) == 'ready'
