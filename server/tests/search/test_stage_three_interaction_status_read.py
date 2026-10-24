"""Status polling reads PostgreSQL without migrations or executor side effects."""

from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import OperationalError

from shuxueshuo_server.graph_lesson.stage_three.checkpoint import identity_from_seed
from shuxueshuo_server.graph_lesson.stage_three.events import EventStore
from shuxueshuo_server.graph_lesson.stage_three.storage import storage_context
from shuxueshuo_server.problem_understanding.workflow_ledger import save
from shuxueshuo_server.product.models import metadata
from shuxueshuo_server.search import stage_three
from tests.search.test_repository import repository as repository_fixture

repository = repository_fixture


@pytest.fixture(autouse=True)
def execution_database(repository):
    with storage_context(repository.db):
        yield


def make_store(directory):
    seed = {'run_id': uuid4().hex, 'lesson_version': 'offline-lesson',
            'stage_one': {'sha256': 'b' * 64}, 'stage_two': {'sha256': 'c' * 64}}
    store = EventStore(directory, {**identity_from_seed(seed), 'revisions': {'methods': 'd' * 64}}, create=True)
    save(directory / 'run.json', seed)
    return store


def pending(store, connection):
    connection.execute(metadata.tables['lesson_interaction_states'].insert().values(
        run_id=store.identity['run_id'], target='/root/goals/0', route='interval', step='step-1',
        ordinal=1, hash='e' * 64, status='pending'))


def file_state(directory):
    return {path.name: (path.read_bytes(), path.stat().st_mtime_ns)
            for path in directory.iterdir() if path.is_file()}


def test_status_poll_is_read_only_and_does_not_create_files(tmp_path, repository):
    store = make_store(tmp_path)
    with repository.db.begin() as connection:
        pending(store, connection)
    before = file_state(tmp_path)
    statements = []

    def record(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.strip().upper())

    sa.event.listen(repository.db, 'before_cursor_execute', record)
    try:
        assert stage_three.has_pending_interactions(tmp_path)
        assert stage_three.stream_descriptor('fixture', tmp_path)['run_id'] == store.identity['run_id']
    finally:
        sa.event.remove(repository.db, 'before_cursor_execute', record)
    assert file_state(tmp_path) == before
    assert statements and all(statement.startswith(('SELECT', 'SET')) for statement in statements)
    assert not list(tmp_path.rglob('*.sqlite*'))


def test_status_only_observes_committed_pending_changes(tmp_path, repository):
    store = make_store(tmp_path)
    table = metadata.tables['lesson_interaction_states']
    with repository.db.begin() as connection:
        pending(store, connection)
    with repository.db.begin() as writer:
        writer.execute(table.update().where(table.c.run_id == store.identity['run_id']).values(status='readonly'))
        assert stage_three.has_pending_interactions(tmp_path)
    assert not stage_three.has_pending_interactions(tmp_path)


@pytest.mark.parametrize('damage', ['database', 'run_id', 'lesson_version', 'input_sha256', 'run_json'])
def test_status_query_reports_unavailable_without_mutating_persisted_math_status(tmp_path, monkeypatch, caplog, damage):
    attempt = tmp_path / 'stage-two-1'
    output = attempt / 'stage-three'
    store = make_store(output)
    save(attempt / stage_three.RESULT, {'status': 'completed'})
    save(output / 'frozen.json', {'implementation': stage_three.fingerprint()})
    save(output / 'stage-three-result.json', {'status': 'completed'})
    if damage == 'run_json':
        (output / 'run.json').write_text('{')
    elif damage == 'database':
        def unavailable(_run_id):
            raise OperationalError('offline', {}, RuntimeError('unavailable'))
        monkeypatch.setattr(stage_three, 'read_run', unavailable)
    else:
        monkeypatch.setattr(stage_three, 'read_run', lambda _run_id: {
            'identity': {**store.identity, damage: 'different'}})
    result = stage_three.presentation(tmp_path, 'fixture', attempt=attempt)
    assert result['execution_status'] == 'unavailable'
    assert result['stream'] is None
    assert stage_three.read(output / 'stage-three-result.json')['status'] == 'completed'
    assert caplog.records and all(record.exc_info for record in caplog.records)


def test_missing_run_is_normal_and_never_created(tmp_path, caplog):
    missing = tmp_path / 'missing-run'
    assert stage_three.has_pending_interactions(missing) is False
    assert stage_three.stream_descriptor('fixture', missing) is None
    assert not missing.exists()
    assert not caplog.records


def test_pending_state_recovers_after_database_becomes_available(tmp_path, repository, monkeypatch):
    store = make_store(tmp_path)
    with repository.db.begin() as connection:
        pending(store, connection)
    original = stage_three.read_run
    def unavailable(_run_id):
        raise OperationalError('offline', {}, RuntimeError('unavailable'))
    monkeypatch.setattr(stage_three, 'read_run', unavailable)
    assert not stage_three.has_pending_interactions(tmp_path)
    monkeypatch.setattr(stage_three, 'read_run', original)
    assert stage_three.has_pending_interactions(tmp_path)


@pytest.mark.parametrize('missing', ['postgres_run', 'legacy_sqlite', 'run.json', 'frozen.json', 'stage_two'])
def test_stopped_run_missing_authority_or_resume_files_is_unavailable_and_cannot_resume(tmp_path, repository, missing):
    attempt = tmp_path / 'stage-two-1'
    output = attempt / 'stage-three'
    store = make_store(output)
    save(attempt / stage_three.RESULT, {'status': 'completed'})
    save(output / 'frozen.json', {'implementation': stage_three.fingerprint()})
    save(output / 'stage-three-result.json', {'status': 'completed'})
    if missing in {'postgres_run', 'legacy_sqlite'}:
        table = metadata.tables['lesson_runs']
        with repository.db.begin() as connection:
            connection.execute(table.delete().where(table.c.run_id == store.identity['run_id']))
        if missing == 'legacy_sqlite':
            (output / 'events.sqlite3').write_bytes(b'archived SQLite is not a runnable PostgreSQL store')
    elif missing == 'stage_two':
        (attempt / stage_three.RESULT).unlink()
    else:
        (output / missing).unlink()
    before = file_state(output)
    assert stage_three.presentation(tmp_path, 'fixture', attempt=attempt) == {
        'execution_status': 'unavailable', 'stream': None}
    with pytest.raises(stage_three.LessonConflict, match='lesson.execution_unavailable'):
        stage_three.assert_resumable(tmp_path, output)
    assert file_state(output) == before
