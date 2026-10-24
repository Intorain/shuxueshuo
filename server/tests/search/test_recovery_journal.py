from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import errno
import json
import os
from time import monotonic
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from shuxueshuo_server.graph_lesson.stage_three.storage import RunNotFound, StorageContextRequired
from shuxueshuo_server.search.recovery import RecoveryJournal, STATE, entry_key
from shuxueshuo_server.search import recovery
from shuxueshuo_server.search.repository import PAGES, SUBMISSIONS, SearchError, SearchRepository
from tests.search.test_postgres_execution import execution, remaining
from tests.search.test_repository import identity, student, submission
from tests.search.test_repository import repository as repository_fixture

repository = repository_fixture


def test_journal_initializes_one_authority_and_validates_backup_cursor(repository):
    before = repository.recovery.snapshot()
    assert before.cursor['sequence'] == 0
    user = student(repository)
    row, _ = submission(repository, user)
    repository.delete(user, row['id'])
    after = repository.recovery.snapshot()
    assert after.validate_cursor(before.cursor) is after
    assert after.cursor['sequence'] == 1
    assert after.deleted_keys == {entry_key(row)}
    assert SearchRepository(repository.db, repository.root).recovery.snapshot().cursor == after.cursor
    for cursor in ({**before.cursor, 'authority_id': str(uuid4())},
                   {**after.cursor, 'sequence': 2}, {**after.cursor, 'digest': '0' * 64}):
        with pytest.raises(SearchError):
            after.validate_cursor(cursor)


def test_durable_intent_survives_database_rollback_and_blocks_all_access(repository, monkeypatch):
    user = student(repository)
    row, _ = submission(repository, user)
    problem = identity()
    repository.link_identity(row['id'], problem)
    durable = execution(repository, row)
    original = repository._delete_rows

    def fail_after_journal(*_args):
        raise RuntimeError('injected database failure')

    monkeypatch.setattr(repository, '_delete_rows', fail_after_journal)
    with pytest.raises(RuntimeError, match='database failure'):
        repository.delete(user, row['id'])
    with repository.db.connect() as connection:
        assert connection.scalar(sa.select(SUBMISSIONS.c.id).where(SUBMISSIONS.c.id == row['id'])) == row['id']
        assert connection.scalar(sa.select(STATE.c.sequence)) == 0
    assert repository.recovery.snapshot().cursor['sequence'] == 1
    with pytest.raises(SearchError, match='search.not_found'):
        repository.submission(user, row['id'])
    assert repository.history(user)['items'] == []
    assert not repository.set_state(row['id'], lesson_status='ready')
    assert repository.link_identity(row['id'], problem) is None
    with pytest.raises(RunNotFound):
        durable.commit_events([], commit_id='late-after-failed-delete')
    monkeypatch.setattr(repository, '_delete_rows', original)
    reopened = SearchRepository(repository.db, repository.root, clock=repository.clock)
    reopened.recover()
    assert reopened.replay_deletions() == {'deleted_search_ids': []}
    assert not any(remaining(repository, durable.identity['run_id']).values())
    reopened.cleanup()
    assert not row['path'].exists()
    assert repository.page(user, row['page_id'])['path'].exists()


def test_journal_write_failure_cannot_commit_database_deletion(repository, monkeypatch):
    user = student(repository)
    row, _ = submission(repository, user)

    def fail_write(*_args, **_kwargs):
        raise OSError('injected durable write failure')

    monkeypatch.setattr(repository.recovery, '_write', fail_write)
    with pytest.raises(OSError, match='durable write failure'):
        repository.delete(user, row['id'])
    assert repository.submission(user, row['id'])['id'] == row['id']
    assert repository.recovery.snapshot().cursor['sequence'] == 0
    with repository.db.connect() as connection:
        assert connection.scalar(sa.select(PAGES.c.pending_cleanup_keys).where(PAGES.c.id == row['page_id'])) == []


@pytest.mark.parametrize('failure', ['partial_write', 'fsync'])
def test_failed_append_rolls_back_partial_or_unsynced_bytes(repository, monkeypatch, failure):
    user = student(repository)
    acknowledged, _ = submission(repository, user)
    pending, _ = submission(repository, user)
    repository.delete(user, acknowledged['id'])
    journal = repository.recovery
    original_bytes = journal.path.read_bytes()
    journal_inode = journal.path.stat().st_ino
    original_write, original_fsync = os.write, os.fsync
    failures = []

    def interrupted_write(descriptor, payload):
        if os.fstat(descriptor).st_ino == journal_inode:
            failures.append('write')
            if len(failures) == 1:
                return original_write(descriptor, payload[:len(payload) // 2])
            raise OSError(errno.ENOSPC, 'injected disk full')
        return original_write(descriptor, payload)

    def interrupted_fsync(descriptor):
        if os.fstat(descriptor).st_ino == journal_inode and not failures:
            failures.append('fsync')
            raise OSError(errno.ENOSPC, 'injected disk full')
        return original_fsync(descriptor)

    with monkeypatch.context() as scoped:
        scoped.setattr(recovery.os, 'write' if failure == 'partial_write' else 'fsync',
                       interrupted_write if failure == 'partial_write' else interrupted_fsync)
        with pytest.raises(OSError, match='injected disk full'):
            repository.delete(user, pending['id'])
    assert failures
    assert journal.path.read_bytes() == original_bytes
    reopened = SearchRepository(repository.db, repository.root)
    assert reopened.recovery.snapshot().deleted_keys == {entry_key(acknowledged)}
    assert reopened.submission(user, pending['id'])['id'] == pending['id']
    with repository.db.connect() as connection:
        assert connection.scalar(sa.select(STATE.c.sequence)) == 1
        assert connection.scalar(sa.select(PAGES.c.pending_cleanup_keys).where(PAGES.c.id == pending['page_id'])) == []
    assert reopened.delete(user, pending['id'])['deleted_search_ids'] == [pending['id']]


@pytest.mark.parametrize('failure', ['write', 'fsync', 'directory_fsync'])
def test_failed_initial_header_creation_removes_only_new_file(repository, monkeypatch, failure):
    journal = RecoveryJournal(repository.root / 'new-authority')
    with repository.db.begin() as connection:
        connection.execute(STATE.update().values(initialized=False, sequence=0, replayed_sequence=0, digest=''))
    original_write, original_fsync = os.write, os.fsync
    failures = []

    def interrupted_write(descriptor, payload):
        original_write(descriptor, payload[:len(payload) // 2])
        raise OSError(errno.ENOSPC, 'injected initial write failure')

    def interrupted_fsync(descriptor):
        target = journal.root if failure == 'directory_fsync' else journal.path
        if target.exists() and os.fstat(descriptor).st_ino == target.stat().st_ino and not failures:
            failures.append('fsync')
            raise OSError(errno.ENOSPC, 'injected initial write failure')
        return original_fsync(descriptor)

    with monkeypatch.context() as scoped:
        scoped.setattr(recovery.os, 'write' if failure == 'write' else 'fsync',
                       interrupted_write if failure == 'write' else interrupted_fsync)
        with pytest.raises(OSError, match='injected initial write failure'):
            journal.initialize(repository.db)
    assert not journal.path.exists()
    with repository.db.connect() as connection:
        assert not connection.scalar(sa.select(STATE.c.initialized))
    journal.initialize(repository.db)
    assert journal.snapshot().cursor['sequence'] == 0


@pytest.mark.parametrize('fragment', [b'', b'{"authority_id":', b'complete_without_newline'])
def test_first_start_recreates_unbound_fragment_without_changing_authority(repository, caplog, fragment):
    journal = repository.recovery
    header = journal.path.read_bytes()
    authority = journal.snapshot().authority_id
    with repository.db.begin() as connection:
        connection.execute(STATE.update().values(initialized=False, sequence=0, replayed_sequence=0, digest=''))
    journal.path.write_bytes(header[:-1] if fragment == b'complete_without_newline' else fragment)
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(SearchRepository, repository.db, repository.root) for _index in range(2)]
        reopened = [future.result(timeout=5) for future in futures]
    assert journal.path.read_bytes() == header
    for current in reopened:
        assert current.recovery.snapshot().authority_id == authority
        assert current.recovery.snapshot().cursor['sequence'] == 0
    with repository.db.connect() as connection:
        state = connection.execute(sa.select(STATE)).mappings().one()
        assert state['initialized'] and str(state['authority_id']) == authority
        assert state['digest'] == reopened[0].recovery.snapshot().cursor['digest']
    assert caplog.text.count('Discarded uninitialized search deletion journal fragment') == 1


@pytest.mark.parametrize('contents', ['valid_header', 'bad_complete_header', 'complete_header_and_fragment'])
def test_first_start_does_not_discard_any_complete_record(repository, contents, caplog):
    journal = repository.recovery
    header = journal.path.read_bytes()
    with repository.db.begin() as connection:
        connection.execute(STATE.update().values(initialized=False, sequence=0, replayed_sequence=0, digest=''))
    raw = (header if contents == 'valid_header' else b'not-json\n' if contents == 'bad_complete_header'
           else header + b'{"sequence":')
    journal.path.write_bytes(raw)
    if contents == 'valid_header':
        SearchRepository(repository.db, repository.root)
    else:
        with pytest.raises(SearchError, match='recovery.'):
            SearchRepository(repository.db, repository.root)
    assert journal.path.read_bytes() == raw
    assert 'Discarded uninitialized search deletion journal fragment' not in caplog.text


@pytest.mark.parametrize('state_values', [
    {'initialized': True},
    {'initialized': False},
    {'initialized': False, 'sequence': 1, 'replayed_sequence': 0, 'digest': ''},
])
@pytest.mark.parametrize('fragment', [b'', b'{"authority_id":'])
def test_existing_checkpoint_never_recreates_missing_header(repository, state_values, fragment):
    with repository.db.begin() as connection:
        connection.execute(STATE.update().values(**state_values))
    repository.recovery.path.write_bytes(fragment)
    with pytest.raises(SearchError, match='recovery.'):
        SearchRepository(repository.db, repository.root)
    assert repository.recovery.path.read_bytes() == fragment


def test_unbound_fragment_directory_sync_failure_stays_uninitialized_and_retryable(repository, monkeypatch):
    journal = repository.recovery
    with repository.db.begin() as connection:
        connection.execute(STATE.update().values(initialized=False, sequence=0, replayed_sequence=0, digest=''))
    journal.path.write_bytes(b'{"authority_id":')

    def fail_sync(_self):
        raise OSError(errno.EIO, 'injected fragment directory sync failure')

    with monkeypatch.context() as scoped:
        scoped.setattr(RecoveryJournal, '_sync_directory', fail_sync)
        with pytest.raises(OSError, match='fragment directory sync failure'):
            SearchRepository(repository.db, repository.root)
    with repository.db.connect() as connection:
        assert not connection.scalar(sa.select(STATE.c.initialized))
    assert not journal.path.exists()
    reopened = SearchRepository(repository.db, repository.root)
    assert reopened.recovery.snapshot().cursor['sequence'] == 0


def test_failed_append_and_failed_rollback_can_repair_unconfirmed_tail_on_restart(repository, monkeypatch, caplog):
    user = student(repository)
    pending, _ = submission(repository, user)
    journal = repository.recovery
    original_bytes = journal.path.read_bytes()
    original_write = os.write

    def interrupted_write(descriptor, payload):
        original_write(descriptor, payload[:len(payload) // 2])
        raise OSError(errno.ENOSPC, 'injected disk full')

    def interrupted_truncate(*_args):
        raise OSError(errno.ENOSPC, 'injected rollback failure')

    with monkeypatch.context() as scoped:
        scoped.setattr(recovery.os, 'write', interrupted_write)
        scoped.setattr(recovery.os, 'ftruncate', interrupted_truncate)
        with pytest.raises(OSError, match='injected disk full'):
            repository.delete(user, pending['id'])
    assert journal.path.read_bytes() != original_bytes
    with pytest.raises(SearchError, match='recovery.truncated'):
        repository.submission(user, pending['id'])
    reopened = SearchRepository(repository.db, repository.root)
    assert journal.path.read_bytes() == original_bytes
    assert reopened.submission(user, pending['id'])['id'] == pending['id']
    assert 'Could not roll back failed search deletion journal write' in caplog.text
    assert 'Repaired incomplete search deletion journal tail' in caplog.text


def test_restart_repairs_only_torn_tail_and_preserves_durable_intent_ahead_of_database(repository, monkeypatch, caplog):
    user = student(repository)
    confirmed, _ = submission(repository, user)
    durable, _ = submission(repository, user)
    retained, _ = submission(repository, user)
    repository.delete(user, confirmed['id'])

    def fail_database(*_args):
        raise RuntimeError('injected database rollback')

    with monkeypatch.context() as scoped:
        scoped.setattr(repository, '_delete_rows', fail_database)
        with pytest.raises(RuntimeError):
            repository.delete(user, durable['id'])
    complete_bytes = repository.recovery.path.read_bytes()
    with repository.recovery.path.open('ab') as stream:
        stream.write(b'{"sequence":3,"entries":[')
    reopened = SearchRepository(repository.db, repository.root)
    assert repository.recovery.path.read_bytes() == complete_bytes
    assert reopened.recovery.snapshot().deleted_keys == {entry_key(confirmed), entry_key(durable)}
    assert reopened.submission(user, retained['id'])['id'] == retained['id']
    with pytest.raises(SearchError, match='search.not_found'):
        reopened.submission(user, durable['id'])
    assert reopened.replay_deletions()['deleted_search_ids'] == [durable['id']]
    assert 'Repaired incomplete search deletion journal tail' in caplog.text


@pytest.mark.parametrize('damage', ['complete_json_without_newline', 'partial_record', 'bad_complete_row',
                                  'bad_prefix_and_tail', 'wrong_authority_and_tail', 'uninitialized'])
def test_restart_never_repairs_confirmed_or_unverifiable_damage(repository, damage):
    user = student(repository)
    row, _ = submission(repository, user)
    repository.delete(user, row['id'])
    path = repository.recovery.path
    original_bytes = path.read_bytes()
    if damage == 'complete_json_without_newline':
        damaged = original_bytes[:-1]
    elif damage == 'partial_record':
        damaged = original_bytes[:-20]
    elif damage == 'bad_complete_row':
        damaged = original_bytes + b'not-json\n'
    elif damage == 'bad_prefix_and_tail':
        damaged = original_bytes.replace(b'"previous_digest":"', b'"previous_digest":"wrong-') + b'{"sequence":'
    elif damage == 'wrong_authority_and_tail':
        other = RecoveryJournal(repository.root / 'other-authority')
        with other._lock(write=True, create=True):
            header = {'schema_version': recovery.SCHEMA, 'authority_id': str(uuid4()), 'sequence': 0}
            other._write({**header, 'digest': recovery._digest(header)}, create=True)
        damaged = other.path.read_bytes() + b'{"sequence":'
    else:
        with repository.db.begin() as connection:
            connection.execute(STATE.update().values(initialized=False))
        damaged = original_bytes + b'{"sequence":'
    path.write_bytes(damaged)
    with pytest.raises(SearchError, match='recovery.'):
        SearchRepository(repository.db, repository.root)
    assert path.read_bytes() == damaged


def test_restore_shared_lock_rejects_delete_quickly_without_database_changes(repository):
    user = student(repository)
    row, _ = submission(repository, user)
    with ThreadPoolExecutor(1) as pool:
        with repository.recovery.locked_snapshot():
            started = monotonic()
            deletion = pool.submit(repository.delete, user, row['id'])
            with pytest.raises(SearchError, match='recovery.busy') as raised:
                deletion.result(timeout=2)
            assert raised.value.status == 503
            assert monotonic() - started < 2
            with repository.db.connect() as connection:
                assert connection.scalar(sa.select(SUBMISSIONS.c.id).where(SUBMISSIONS.c.id == row['id'])) == row['id']
                assert connection.scalar(sa.select(STATE.c.sequence)) == 0
                assert connection.scalar(sa.select(PAGES.c.pending_cleanup_keys).where(PAGES.c.id == row['page_id'])) == []
    assert repository.delete(user, row['id'])['deleted_search_ids'] == [row['id']]


@pytest.mark.parametrize('damage', ['missing', 'truncated', 'rolled_back', 'bad_hash', 'symlink', 'fifo', 'lock_fifo', 'lock_missing'])
def test_missing_or_rolled_back_authority_fails_closed(repository, damage):
    user = student(repository)
    removed, _ = submission(repository, user)
    retained, _ = submission(repository, user)
    repository.delete(user, removed['id'])
    path = repository.recovery.path
    if damage == 'missing':
        path.unlink()
    elif damage == 'lock_missing':
        repository.recovery.lock_path.unlink()
    elif damage == 'truncated':
        path.write_bytes(path.read_bytes()[:-2])
    elif damage == 'rolled_back':
        path.write_bytes(path.read_bytes().splitlines(keepends=True)[0])
    elif damage == 'bad_hash':
        records = [json.loads(line) for line in path.read_text().splitlines()]
        records[-1]['digest'] = '0' * 64
        path.write_text(''.join(json.dumps(record) + '\n' for record in records))
    elif damage == 'symlink':
        original = path.with_suffix('.original')
        path.rename(original)
        path.symlink_to(original)
    else:
        fifo = repository.recovery.lock_path if damage == 'lock_fifo' else path
        fifo.unlink()
        os.mkfifo(fifo)
    with pytest.raises(SearchError, match='recovery.'):
        repository.submission(user, retained['id'])
    with pytest.raises(SearchError, match='recovery.'):
        repository.history(user)
    with pytest.raises(SearchError, match='recovery.'):
        SearchRepository(repository.db, repository.root)


def test_journal_records_exact_submission_incarnation_not_public_problem(repository):
    user, other = student(repository), student(repository)
    problem = identity()
    earlier, _ = submission(repository, user)
    pending, _ = submission(repository, user)
    other_row, _ = submission(repository, other)
    for row in (earlier, other_row):
        repository.link_identity(row['id'], problem)
    repository.delete(user, earlier['id'])
    repository.link_identity(pending['id'], problem)
    repository.test_time[0] += timedelta(seconds=1)
    repeated, _ = submission(repository, user)
    repository.link_identity(repeated['id'], problem)
    assert repository.recovery.snapshot().deleted_keys == {entry_key(earlier)}
    assert repository.replay_deletions()['deleted_search_ids'] == []
    for owner, row in ((user, pending), (user, repeated), (other, other_row)):
        assert repository.submission(owner, row['id'])['id'] == row['id']


def test_replay_matches_owner_and_creation_time_not_only_search_id(repository):
    user = student(repository)
    row, _ = submission(repository, user)
    with repository.db.begin() as connection:
        repository.recovery.append(connection, [{**row, 'created_at': row['created_at'] - timedelta(seconds=1)}])
    assert repository.replay_deletions()['deleted_search_ids'] == []
    assert repository.submission(user, row['id'])['id'] == row['id']


def test_concurrent_deletions_form_one_complete_hash_chain(repository):
    user = student(repository)
    rows = [submission(repository, user)[0] for _ in range(8)]
    before = repository.recovery.snapshot().cursor
    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(lambda row: repository.delete(user, row['id']), rows))
    assert {identifier for result in results for identifier in result['deleted_search_ids']} == {row['id'] for row in rows}
    snapshot = RecoveryJournal(repository.root).snapshot().validate_cursor(before)
    assert snapshot.cursor['sequence'] == 8
    assert snapshot.deleted_keys == {entry_key(row) for row in rows}


def test_cleanup_replays_old_failed_intent_even_after_later_successful_delete(repository, monkeypatch):
    user = student(repository)
    failed, _ = submission(repository, user)
    later, _ = submission(repository, user)
    original = repository._delete_rows
    monkeypatch.setattr(repository, '_delete_rows', lambda *_args: (_ for _ in ()).throw(RuntimeError('offline failure')))
    with pytest.raises(RuntimeError):
        repository.delete(user, failed['id'])
    monkeypatch.setattr(repository, '_delete_rows', original)
    repository.delete(user, later['id'])
    repository.cleanup()
    with repository.db.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(SUBMISSIONS)) == 0
    assert not failed['path'].exists() and not later['path'].exists()


@pytest.mark.parametrize('operation', ['delete', 'authority', 'singleton'])
def test_application_cannot_replace_database_authority(repository, operation):
    with pytest.raises(DBAPIError):
        with repository.db.begin() as connection:
            statement = (STATE.delete() if operation == 'delete' else STATE.update().values(
                **({'authority_id': uuid4()} if operation == 'authority' else {'singleton': False})))
            connection.execute(statement)


def test_snapshot_opens_existing_authority_lock_read_only(repository, monkeypatch):
    import os
    from shuxueshuo_server.search import recovery

    original = os.open
    flags_seen = []

    def record_flags(path, flags, *args, **kwargs):
        if path == repository.recovery.lock_path:
            flags_seen.append(flags)
        return original(path, flags, *args, **kwargs)

    monkeypatch.setattr(recovery.os, 'open', record_flags)
    with repository.recovery.locked_snapshot() as snapshot:
        assert snapshot.cursor['sequence'] == 0
    assert flags_seen and all(not flags & (os.O_RDWR | os.O_WRONLY | os.O_CREAT) for flags in flags_seen)


def test_private_executor_without_journal_guard_fails_closed(repository, monkeypatch):
    row, _ = submission(repository, student(repository))
    durable = execution(repository, row)
    monkeypatch.delattr(repository.db, '_search_recovery')
    with pytest.raises(StorageContextRequired):
        durable.commit_events([], commit_id='missing-authority')
    with pytest.raises(StorageContextRequired):
        durable.snapshot()


def test_cleanup_does_not_requery_deleted_history_after_replay_checkpoint(repository):
    user = student(repository)
    row, _ = submission(repository, user)
    repository.delete(user, row['id'])
    statements = []

    def record_statement(_connection, _cursor, statement, *_args):
        statements.append(statement)

    sa.event.listen(repository.db, 'before_cursor_execute', record_statement)
    try:
        assert repository.replay_deletions() == {'deleted_search_ids': []}
    finally:
        sa.event.remove(repository.db, 'before_cursor_execute', record_statement)
    assert not any('search_submissions' in statement for statement in statements)
