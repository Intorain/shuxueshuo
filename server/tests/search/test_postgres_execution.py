"""Private execution state shares PostgreSQL ownership and lifecycle boundaries."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from uuid import uuid4

import pytest
import sqlalchemy as sa

from shuxueshuo_server.graph_lesson.stage_three.events import EventStore
from shuxueshuo_server.graph_lesson.stage_three.storage import (
    RunNotFound,
    RunUnavailable,
    storage_context,
)
from shuxueshuo_server.product.models import metadata
from tests.search.test_repository import identity, student, submission
from tests.search.test_repository import repository as repository_fixture

repository = repository_fixture


def execution(repo, row):
    value = {'run_id': uuid4().hex, 'lesson_version': 'offline-fixture', 'input_sha256': 'a' * 64,
             'revisions': {'fixture': 'b' * 64}}
    with storage_context(repo.db, row['id'], clock=repo.clock):
        return EventStore(row['path'] / 'stage-two-1/stage-three', value, create=True)


def remaining(repo, run_id):
    with repo.db.connect() as connection:
        return {name: connection.scalar(sa.select(sa.func.count()).select_from(table).where(table.c.run_id == run_id))
                for name, table in metadata.tables.items() if name.startswith('lesson_') and 'run_id' in table.c}


def test_same_database_runs_are_scoped_to_the_exact_submission(repository):
    first, _ = submission(repository, student(repository))
    second, _ = submission(repository, student(repository))
    durable = execution(repository, first)
    durable.commit_events([], commit_id='first')
    with storage_context(repository.db, first['id'], clock=repository.clock):
        assert EventStore(durable.directory, durable.identity).snapshot()['run_id'] == durable.identity['run_id']
    for owner in (second['id'], None):
        with storage_context(repository.db, owner, clock=repository.clock), pytest.raises(RunNotFound):
            EventStore(durable.directory, durable.identity)
    assert not list(repository.storage.root.rglob('*.sqlite*'))


def test_deleted_submission_cascades_and_late_worker_cannot_recreate(repository):
    user = student(repository)
    row, _ = submission(repository, user)
    durable = execution(repository, row)
    durable.commit_events([], commit_id='committed')
    repository.delete(user, row['id'])
    assert not any(remaining(repository, durable.identity['run_id']).values())
    with pytest.raises(RunNotFound):
        durable.commit_events([], commit_id='late')
    with storage_context(repository.db, row['id'], clock=repository.clock), pytest.raises(RunNotFound):
        EventStore(durable.directory, durable.identity, create=True)
    assert not any(remaining(repository, durable.identity['run_id']).values())


def test_delete_serializes_with_inflight_atomic_commit(repository):
    user = student(repository)
    row, _ = submission(repository, user)
    durable = execution(repository, row)
    reached, release, deleting = Event(), Event(), Event()

    def hold():
        reached.set()
        assert release.wait(10)

    def delete():
        deleting.set()
        return repository.delete(user, row['id'])

    with ThreadPoolExecutor(2) as pool:
        writing = pool.submit(durable.commit_events, [], commit_id='racing', before_commit=hold)
        assert reached.wait(5)
        removed = pool.submit(delete)
        try:
            assert deleting.wait(5)
            assert not removed.done()
        finally:
            release.set()
        writing.result(timeout=10)
        assert removed.result(timeout=10)['deleted_search_ids'] == [row['id']]
    assert not any(remaining(repository, durable.identity['run_id']).values())


@pytest.mark.parametrize('linked', [False, True])
def test_expiry_blocks_execution_before_cleanup_and_purges_every_table(repository, linked):
    user = student(repository)
    row, _ = submission(repository, user)
    if linked:
        repository.link_identity(row['id'], identity())
    durable = execution(repository, row)
    durable.commit_events([], commit_id='before-expiry')
    repository.test_time[0] = row['expires_at']
    with pytest.raises(RunUnavailable):
        durable.commit_events([], commit_id='expired')
    with pytest.raises(RunUnavailable):
        durable.snapshot()
    repository.cleanup()
    assert not any(remaining(repository, durable.identity['run_id']).values())
    assert repository.cleanup()['removed'] == 0
    if linked:
        assert repository.submission(user, row['id'])['artifact_state'] == 'expired'


def test_page_expiry_does_not_expire_the_private_execution(repository):
    row, _ = submission(repository, student(repository))
    durable = execution(repository, row)
    repository.test_time[0] += timedelta(days=1)
    repository.cleanup()
    durable.commit_events([], commit_id='after-page-expiry')
    assert durable.snapshot()['run_id'] == durable.identity['run_id']


def test_atomic_commit_fault_and_retry_keep_one_durable_receipt(repository):
    row, _ = submission(repository, student(repository))
    durable = execution(repository, row)

    def crash():
        raise RuntimeError('offline fault')

    with pytest.raises(RuntimeError, match='offline fault'):
        durable.commit_events([], commit_id='atomic', before_commit=crash)
    assert remaining(repository, durable.identity['run_id'])['lesson_commits'] == 0
    with pytest.raises(RuntimeError, match='offline fault'):
        durable.commit_events([], commit_id='atomic', after_commit=crash)
    result = durable.commit_events([], commit_id='atomic')
    assert result['commit_id'] == 'atomic'
    assert remaining(repository, durable.identity['run_id'])['lesson_commits'] == 1
