"""Real HTTP/PG recovery when unstarted enqueue cancellation temporarily fails."""

import pytest
from fastapi.testclient import TestClient

from shuxueshuo_server.search import stage_three
from shuxueshuo_server.search.storage import SearchError
from tests.search.test_generation_admission_api import (
    actor,
    complete_generation,
    generate,
    offline_pipeline,
    tickets,
)
from tests.search.test_private_api import private_app as private_app_fixture
from tests.search.test_repository import repository as repository_fixture


@pytest.fixture
def repository(tmp_path):
    yield from repository_fixture.__wrapped__(tmp_path)


@pytest.fixture
def private_app(repository, monkeypatch):
    return private_app_fixture.__wrapped__(repository, monkeypatch)


@pytest.mark.parametrize(('operation', 'failure'), [
    ('generation', 'enqueue'),
    ('rerun', 'enqueue'),
    ('continuation', 'enqueue'),
    ('rerun', 'retry-intent'),
])
def test_unstarted_http_job_retries_cancellation_without_work_or_held_leases(
    private_app, repository, monkeypatch, operation, failure,
):
    recognition, classifications = offline_pipeline(monkeypatch)
    app, auth = private_app
    with TestClient(app, base_url=auth.config.origin) as client:
        owner = actor(client, auth)
        search_id, directory = None, None
        if operation != 'generation':
            search_id, row = complete_generation(client, repository, owner, 'seed-ready-course')
            directory = row['path']
        before_recognition, before_classifications = list(recognition), list(classifications)
        initial_consumed = sum(row['consumed'] for row in tickets(repository))
        runner = app.state.search_task_runner
        reap = runner.reap
        monkeypatch.setattr(runner, 'reap', lambda: None)
        cancelled, dispatched, resumed = [], [], []
        original_cancel = repository.admission.cancel

        def transient_cancel(identifier, **kwargs):
            cancelled.append(identifier)
            if len(cancelled) == 1:
                raise OSError('offline fixture: cancellation database temporarily unavailable')
            return original_cancel(identifier, **kwargs)

        def reject_enqueue(*_args, **_kwargs):
            dispatched.append(True)
            raise OSError('offline fixture: executor rejected enqueue')

        def must_not_resume(*_args, **_kwargs):
            resumed.append(True)
            pytest.fail('Unstarted continuation must not run')

        monkeypatch.setattr(repository.admission, 'cancel', transient_cancel)
        monkeypatch.setattr(runner.executor, 'submit', reject_enqueue)
        monkeypatch.setattr(stage_three, 'resume_stage_three', must_not_resume)
        if failure == 'retry-intent':
            original_reserve = stage_three.reserve_retry

            def fail_after_intent(current):
                original_reserve(current)
                raise OSError('offline fixture: retry intent publication failed')

            monkeypatch.setattr(stage_three, 'reserve_retry', fail_after_intent)
        if operation == 'generation':
            response = generate(client, owner, 'failed-enqueue')
        elif operation == 'rerun':
            response = client.post(f'/api/search/problems/{search_id}/lesson', headers=owner['headers'],
                                   json={'client_request_id': 'failed-rerun'})
        else:
            output = directory / 'stage-two-1/stage-three'
            run_id = stage_three.read(output / 'run.json')['run_id']
            monkeypatch.setattr(stage_three, 'fingerprint', lambda: {'fixture': 'b' * 64})
            monkeypatch.setattr(stage_three, 'has_pending_interactions', lambda _output: True)
            response = client.post(f'/api/search/problems/{search_id}/lesson/{run_id}/resume', headers=owner['headers'])
        assert response.status_code == 503, response.text
        assert response.json()['detail'] == 'search.storage_unavailable'
        assert response.headers['cache-control'] == 'no-store'
        pending = [row for row in tickets(repository) if row['state'] == 'reserved']
        assert len(pending) == 1
        ticket = pending[0]
        search_id = ticket['search_id']
        assert ticket['kind'] == operation
        assert ticket['consumed'] is False
        assert cancelled == [str(ticket['id'])]
        assert not runner.pending and not runner.running
        assert str(ticket['id']) in runner.finalizations
        assert dispatched == ([] if failure == 'retry-intent' else [True])
        with pytest.raises(SearchError, match='search.account_busy'):
            repository.admission.reserve(owner['user'], 'continuation', search_id)
        row = repository.submission(owner['user'], search_id)
        assert row['recognition_status' if operation == 'generation' else 'lesson_status'] == 'interrupted'
        with repository.storage.lifecycle_lock(search_id):
            pass
        if operation != 'generation':
            assert not (directory / stage_three.RETRY_INTENT).exists()
            lease = stage_three.acquire_problem(directory)
            stage_three.release_problem(lease)
        reap()
        assert cancelled == [str(ticket['id']), str(ticket['id'])]
        assert not runner.finalizations
        restored = next(row for row in tickets(repository) if row['id'] == ticket['id'])
        assert restored['state'] == 'cancelled'
        assert restored['consumed'] is False
        assert sum(row['consumed'] for row in tickets(repository)) == initial_consumed
        assert recognition == before_recognition
        assert classifications == before_classifications
        assert resumed == []
        next_ticket = repository.admission.reserve(owner['user'], 'continuation', search_id)
        assert next_ticket.created
        assert original_cancel(next_ticket.id)
