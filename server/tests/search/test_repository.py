import json
import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from threading import Barrier, Event, current_thread
from uuid import uuid4

import pytest
import sqlalchemy as sa
from PIL import Image
from sqlalchemy.exc import DBAPIError, IntegrityError

from shuxueshuo_server.graph_lesson.stage_three.events import EventStore
from shuxueshuo_server.graph_lesson.stage_three.storage import storage_context
from shuxueshuo_server.product.admin.database import DELETABLE, MUTABLE, doctor
from shuxueshuo_server.product.config import Settings
from shuxueshuo_server.product.db import canonical, engine
from shuxueshuo_server.product.models import metadata
from shuxueshuo_server.search.repository import (
    PAGES,
    PROBLEMS,
    RELATIONS,
    SUBMISSIONS,
    SearchError,
    SearchRepository,
)


@pytest.fixture
def repository(tmp_path):
    root = os.environ.get('PRODUCT_TEST_DATA_DIR')
    if not root:
        pytest.fail('Search persistence tests require independently migrated PRODUCT_TEST_DATA_DIR')
    settings = Settings.load('local', root, os.environ.get('PRODUCT_TEST_INSTANCE', 'search-stage1'))
    schema = 'search_test_' + secrets.token_hex(8)
    migration_db = engine(settings.url('migration'))
    with migration_db.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}", public')
        connection.exec_driver_sql(f'GRANT USAGE ON SCHEMA "{schema}" TO product_app')
        script = Path(__file__).parents[2] / 'alembic/versions/0013_student_search.sql'
        connection.execute(sa.text(script.read_text()))
        connection.execute(sa.text(script.with_name('0014_lesson_execution.sql').read_text()))
        connection.execute(sa.text(script.with_name('0015_search_recovery.sql').read_text()))
        for table in (PROBLEMS, PAGES, SUBMISSIONS, RELATIONS, metadata.tables['search_recovery_state'],
                      *[table for name, table in metadata.tables.items() if name.startswith('lesson_')]):
            connection.exec_driver_sql(f'GRANT SELECT, INSERT ON "{table.name}" TO product_app')
            if table.name in MUTABLE:
                columns = ','.join('"' + name + '"' for name in MUTABLE[table.name].split())
                connection.exec_driver_sql(f'GRANT UPDATE ({columns}) ON "{table.name}" TO product_app')
            if table.name in DELETABLE:
                connection.exec_driver_sql(f'GRANT DELETE ON "{table.name}" TO product_app')
    database = engine(settings.url())

    @sa.event.listens_for(database, 'connect')
    def search_path(dbapi_connection, _record):
        previous = dbapi_connection.autocommit
        dbapi_connection.autocommit = True
        try:
            with dbapi_connection.cursor() as cursor:
                cursor.execute(f'SET SESSION search_path TO "{schema}", public')
        finally:
            dbapi_connection.autocommit = previous

    now = [datetime.now(UTC)]
    repo = SearchRepository(database, tmp_path / 'private-v1', clock=lambda: now[0])
    repo.test_time = now
    repo.test_settings = settings
    repo.test_schema = schema
    try:
        yield repo
    finally:
        database.dispose()
        with migration_db.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        migration_db.dispose()


def student(repo):
    phone = '139' + ''.join(str(secrets.randbelow(10)) for _ in range(8))
    with repo.db.begin() as connection:
        return connection.scalar(sa.text('SELECT register_student_phone(:phone,:id)'), {'phone': phone, 'id': uuid4()})


def page(repo, user, parent=None):
    page_id = secrets.token_hex(6)
    directory = repo.storage.path(repo.storage.page_key(page_id))
    directory.mkdir()
    Image.new('RGB', (120, 120), 'white').save(directory / 'page.png')
    (directory / 'ocr.json').write_text('{"private":"name"}')
    repo.register_page(user, page_id, {'width': 120, 'height': 120, 'regions': ['private']}, parent_page_id=parent)
    return page_id


def submission(repo, user, page_id=None, request_id=None):
    page_id = page_id or page(repo, user)
    search_id = secrets.token_hex(6)
    directory = repo.storage.path(repo.storage.submission_key(search_id))
    directory.mkdir()
    for name in ('question.png', 'original.png'):
        Image.new('RGB', (80, 50), 'white').save(directory / name)
    return repo.create_submission(user, search_id, page_id, [0, 0, 1, 1], client_request_id=request_id)


def identity():
    value = {'identity_version': 1, 'stem': 'x > ' + str(uuid4())}
    return {'identity_version': 1, 'fingerprint': sha256(canonical(value).encode()).hexdigest(),
            'identity': value, 'statement': '已知 x > 0，求解。', 'structured_problem': {'condition': 'x > 0'}}


def lesson_artifacts(repo, row):
    for name in ('result.json', 'crop.json', 'stage-two-1/stage-two-result.json', 'stage-two-1/stage-three/run.json',
                 'stage-two-1/stage-three/frozen.json',
                 'stage-two-1/stage-three/stage-three-result.json'):
        target = row['path'] / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('{}')
    run_id = uuid4().hex
    output = row['path'] / 'stage-two-1/stage-three'
    (output / 'run.json').write_text('{"run_id":"' + run_id + '"}')
    with storage_context(repo.db, row['id'], clock=repo.clock):
        EventStore(output, {'run_id': run_id, 'lesson_version': 'fixture', 'input_sha256': 'a' * 64,
                            'revisions': {'fixture': 'b' * 64}}, create=True)


def count(repo, table, condition):
    with repo.db.connect() as connection:
        return connection.scalar(sa.select(sa.func.count()).select_from(table).where(condition))


def test_parallel_identity_merges_and_retry_is_idempotent(repository):
    first, second = student(repository), student(repository)
    first_row, _ = submission(repository, first, request_id='one')
    second_row, _ = submission(repository, second, request_id='one')
    common = identity()
    barrier = Barrier(2)

    def link(row):
        barrier.wait()
        return repository.link_identity(row['id'], common)['id']

    with ThreadPoolExecutor(2) as pool:
        problem_ids = list(pool.map(link, (first_row, second_row)))
    assert problem_ids[0] == problem_ids[1]
    assert count(repository, PROBLEMS, PROBLEMS.c.id == problem_ids[0]) == 1
    assert count(repository, RELATIONS, RELATIONS.c.problem_id == problem_ids[0]) == 2
    repeated, created = submission(repository, first, first_row['page_id'], request_id='one')
    assert not created and repeated['id'] == first_row['id']
    assert repository.find_request(first, 'one')['id'] == first_row['id']


def test_request_race_has_one_submission_and_one_winner(repository):
    user = student(repository)
    page_id = page(repository, user)
    barrier = Barrier(2)

    def create(_index):
        barrier.wait()
        return submission(repository, user, page_id, request_id='concurrent')

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(create, range(2)))
    assert sum(created for _, created in results) == 1
    assert results[0][0]['id'] == results[1][0]['id']
    assert count(repository, SUBMISSIONS, SUBMISSIONS.c.user_id == user) == 1


def test_foreign_page_access_and_composite_fk(repository):
    first, second = student(repository), student(repository)
    row, _ = submission(repository, first)
    with pytest.raises(SearchError, match='page.not_found'):
        repository.page(second, row['page_id'])
    with pytest.raises(SearchError, match='search.not_found'):
        repository.submission(second, row['id'])
    settings = repository.test_settings
    owner = engine(settings.url('migration'))
    try:
        with pytest.raises(IntegrityError), owner.begin() as connection:
            connection.exec_driver_sql(f'SET LOCAL search_path TO "{repository.test_schema}", public')
            connection.execute(SUBMISSIONS.update().where(SUBMISSIONS.c.id == row['id']).values(user_id=second))
    finally:
        owner.dispose()


def test_identity_immutable_collision_and_disable(repository):
    user = student(repository)
    first, _ = submission(repository, user)
    second, _ = submission(repository, user)
    common = identity()
    problem = repository.link_identity(first['id'], common)
    with pytest.raises(SearchError, match='fingerprint_conflict'):
        repository.link_identity(second['id'], {**common, 'identity': {'different': True}})
    with pytest.raises(DBAPIError), repository.db.begin() as connection:
        connection.execute(PROBLEMS.update().where(PROBLEMS.c.id == problem['id']).values(statement='changed'))
    repository.disable(problem['id'])
    with pytest.raises(SearchError, match='problem.disabled'):
        repository.link_identity(second['id'], common)
    assert repository.set_state(first['id'], lesson_state='ready') is False
    item = next(item for item in repository.history(user)['items'] if item['search_id'] == first['id'])
    assert item['latest_status'] == 'disabled'
    assert not item['lesson_available']


def test_history_prefers_ready_and_retains_latest_status(repository):
    user = student(repository)
    early, _ = submission(repository, user)
    common = identity()
    repository.link_identity(early['id'], common)
    lesson_artifacts(repository, early)
    repository.set_state(early['id'], lesson_state='ready')
    repository.test_time[0] += timedelta(seconds=2)
    latest, _ = submission(repository, user)
    repository.link_identity(latest['id'], common)
    repository.set_state(latest['id'], lesson_state='failed')
    item = repository.history(user)['items'][0]
    assert item['search_id'] == early['id']
    assert item['lesson_available'] and item['latest_status'] == 'failed'
    assert item['last_searched_at'] == latest['created_at'].isoformat()


def test_history_uses_relation_membership_recency_and_owner_for_mixed_pagination(repository):
    user, other_user = student(repository), student(repository)
    expired, _ = submission(repository, user)
    repository.test_time[0] = expired['expires_at']
    first, _ = submission(repository, user)
    common = identity()
    first_problem = repository.link_identity(first['id'], common)
    repository.test_time[0] += timedelta(seconds=1)
    second, _ = submission(repository, user)
    repository.link_identity(second['id'], identity())
    repository.test_time[0] += timedelta(seconds=1)
    unlinked, _ = submission(repository, user)
    repository.test_time[0] += timedelta(seconds=1)
    foreign, _ = submission(repository, other_user)
    repository.link_identity(foreign['id'], common)
    foreign_unlinked, _ = submission(repository, other_user)
    recent_at = repository.clock() + timedelta(seconds=1)
    with repository.db.begin() as connection:
        connection.execute(RELATIONS.update().where(
            RELATIONS.c.user_id == user, RELATIONS.c.problem_id == first_problem['id']).values(last_searched_at=recent_at))

    first_page = repository.history(user, limit=2)
    second_page = repository.history(user, limit=2, offset=2)
    assert [item['search_id'] for item in first_page['items']] == [first['id'], unlinked['id']]
    assert [item['search_id'] for item in second_page['items']] == [second['id']]
    assert first_page['items'][0]['last_searched_at'] == recent_at.isoformat()
    assert first_page['has_more'] and not second_page['has_more']
    assert {item['search_id'] for item in repository.history(other_user)['items']} == {foreign['id'], foreign_unlinked['id']}

    with repository.db.begin() as connection:
        connection.execute(RELATIONS.delete().where(
            RELATIONS.c.user_id == user, RELATIONS.c.problem_id == first_problem['id']))
    assert [item['search_id'] for item in repository.history(user)['items']] == [unlinked['id'], second['id']]
    assert count(repository, SUBMISSIONS, SUBMISSIONS.c.id == first['id']) == 1


@pytest.mark.parametrize(('status', 'summary'), [
    ('queued', '等待识别的题目'),
    ('running', '识别中的题目'),
    ('reviewed', '已识别的题目'),
    ('needs_confirmation', '待确认的题目'),
    ('failed', '识别失败的题目'),
    ('interrupted', '识别已中断的题目'),
])
def test_unlinked_history_title_reflects_recognition_state_without_reading_private_statement(repository, status, summary):
    user = student(repository)
    row, _ = submission(repository, user)
    (row['path'] / 'result.json').write_text('{"statement":"PRIVATE TITLE MUST NOT APPEAR"}')
    repository.set_state(row['id'], recognition_state=status)
    item = repository.history(user)['items'][0]
    assert item['problem_id'] is None
    assert item['latest_status'] == status and item['summary'] == summary


def test_delete_removes_all_linked_private_records_but_keeps_page_and_other_question(repository):
    first, second = student(repository), student(repository)
    page_id = page(repository, first)
    chosen, _ = submission(repository, first, page_id)
    repeated, _ = submission(repository, first, page_id)
    other, _ = submission(repository, first, page_id)
    foreign, _ = submission(repository, second)
    common = identity()
    for row in (chosen, repeated, foreign):
        repository.link_identity(row['id'], common)
    result = repository.delete(first, chosen['id'])
    assert set(result['deleted_search_ids']) == {chosen['id'], repeated['id']}
    assert repository.link_identity(chosen['id'], common) is None
    assert repository.set_state(chosen['id'], lesson_state='ready') is False
    repository.cleanup()
    assert not chosen['path'].exists() and not repeated['path'].exists()
    assert other['path'].exists() and foreign['path'].exists()
    assert repository.page(first, page_id)['path'].exists()
    assert repository.history(first)['items'][0]['search_id'] == other['id']
    repository.link_identity(other['id'], common)
    assert count(repository, RELATIONS, RELATIONS.c.user_id == first) == 1


def test_cleanup_waits_for_active_writer_and_late_completion_cannot_restore(repository):
    user = student(repository)
    row, _ = submission(repository, user)
    with repository.lifecycle_lock(row['id']):
        repository.delete(user, row['id'])
        repository.cleanup()
        assert row['path'].exists()
        (row['path'] / 'late.json').write_text('private')
        assert repository.set_state(row['id'], lesson_state='ready') is False
    repository.cleanup()
    assert not row['path'].exists()


def test_image_and_lesson_expiry_and_rotation_deadline(repository):
    user = student(repository)
    original = page(repository, user)
    linked, _ = submission(repository, user, original)
    unlinked, _ = submission(repository, user, original)
    repository.link_identity(linked['id'], identity())
    repository.set_state(linked['id'], lesson_state='ready')
    repository.test_time[0] += timedelta(hours=12)
    rotated = page(repository, user, original)
    assert repository.page(user, original)['expires_at'] == repository.page(user, rotated)['expires_at']
    repository.test_time[0] += timedelta(hours=12)
    with pytest.raises(SearchError, match='page.expired'):
        repository.page(user, rotated)
    repository.cleanup()
    assert not repository.page(user, original, require_image=False)['path'].exists()
    assert linked['path'].exists()
    repository.test_time[0] += timedelta(days=29)
    assert repository.submission(user, linked['id'])['lesson_status'] == 'expired'
    with pytest.raises(SearchError, match='search.not_found'):
        repository.submission(user, unlinked['id'])
    repository.cleanup()
    assert not linked['path'].exists() and not unlinked['path'].exists()
    assert repository.submission(user, linked['id'])['statement']
    assert count(repository, SUBMISSIONS, SUBMISSIONS.c.id == unlinked['id']) == 0


def test_recover_marks_abandoned_work_without_interrupting_locked_work(repository):
    user = student(repository)
    abandoned, _ = submission(repository, user)
    active, _ = submission(repository, user)
    repository.set_state(abandoned['id'], recognition_state='reviewed', lesson_state='running')
    with repository.lifecycle_lock(active['id']):
        repository.recover()
        assert repository.submission(user, active['id'])['recognition_status'] == 'queued'
    assert repository.submission(user, abandoned['id'])['lesson_status'] == 'interrupted'


def test_cleanup_retry_and_orphan_scope(repository, monkeypatch):
    user = student(repository)
    row, _ = submission(repository, user)
    repository.delete(user, row['id'])
    original_remove = repository.storage.remove

    def unavailable(key):
        if key == row['storage_key']:
            raise OSError('unavailable')
        return original_remove(key)

    monkeypatch.setattr(repository.storage, 'remove', unavailable)
    repository.cleanup()
    assert row['path'].exists()
    pending = repository.page(user, row['page_id'])['pending_cleanup_keys']
    assert pending[0]['attempts'] == 1
    monkeypatch.setattr(repository.storage, 'remove', original_remove)
    orphan = repository.storage.path(repository.storage.submission_key(secrets.token_hex(6)))
    orphan.mkdir()
    old = (repository.clock() - timedelta(hours=2)).timestamp()
    os.utime(orphan, (old, old))
    fresh = repository.storage.path(repository.storage.submission_key(secrets.token_hex(6)))
    fresh.mkdir()
    legacy = repository.root.parent / 'anonymous'
    legacy.mkdir()
    repository.cleanup()
    assert not row['path'].exists() and not orphan.exists() and fresh.exists() and legacy.exists()


def test_application_permissions_and_doctor(repository):
    assert doctor(repository.test_settings, probe=False)['ok']
    with pytest.raises(DBAPIError), repository.db.begin() as connection:
        connection.execute(PAGES.delete())


def test_history_paginates_groups_without_duplicate_problem(repository):
    user = student(repository)
    common = identity()
    for index in range(5):
        repository.test_time[0] += timedelta(seconds=1)
        row, _ = submission(repository, user)
        if index < 2:
            repository.link_identity(row['id'], common)
    first = repository.history(user, limit=2)
    second = repository.history(user, limit=2, offset=2)
    assert len(first['items']) == len(second['items']) == 2
    assert first['has_more'] and not second['has_more']
    assert len({item['search_id'] for item in first['items'] + second['items']}) == 4


def test_delete_and_same_submission_completion_race_never_restores_relation(repository):
    user = student(repository)
    row, _ = submission(repository, user)
    common = identity()
    barrier = Barrier(2)

    def complete():
        barrier.wait()
        return repository.link_identity(row['id'], common)

    def remove():
        barrier.wait()
        return repository.delete(user, row['id'])

    with ThreadPoolExecutor(2) as pool:
        completion = pool.submit(complete)
        deletion = pool.submit(remove)
        completion.result()
        deletion.result()
    assert count(repository, SUBMISSIONS, SUBMISSIONS.c.id == row['id']) == 0
    assert count(repository, RELATIONS, RELATIONS.c.user_id == user) == 0


def test_publication_out_of_order_keeps_first_and_latest_submission_time(repository):
    user = student(repository)
    early, _ = submission(repository, user)
    repository.test_time[0] += timedelta(seconds=5)
    later, _ = submission(repository, user)
    common = identity()
    repository.link_identity(later['id'], common)
    repository.link_identity(early['id'], common)
    with repository.db.connect() as connection:
        relation = connection.execute(sa.select(RELATIONS).where(RELATIONS.c.user_id == user)).mappings().one()
    assert relation['first_searched_at'] == early['created_at']
    assert relation['last_searched_at'] == later['created_at']


def test_deletion_rechecks_association_after_waiting_for_page_lock(repository, monkeypatch):
    user = student(repository)
    row, _ = submission(repository, user)
    original_page = repository._page
    selected = Event()
    linked = Event()

    def held_page(*args, **kwargs):
        if current_thread().name.startswith('delete-before-link'):
            selected.set()
            assert linked.wait(5)
        return original_page(*args, **kwargs)

    monkeypatch.setattr(repository, '_page', held_page)
    with ThreadPoolExecutor(1, thread_name_prefix='delete-before-link') as pool:
        deleted = pool.submit(repository.delete, user, row['id'])
        try:
            assert selected.wait(5)
            repository.link_identity(row['id'], identity())
        finally:
            linked.set()
        deleted.result()
    assert count(repository, RELATIONS, RELATIONS.c.user_id == user) == 0


def test_history_skips_missing_private_lesson_artifacts(repository):
    user = student(repository)
    common = identity()
    earlier, _ = submission(repository, user)
    repository.test_time[0] += timedelta(seconds=1)
    later, _ = submission(repository, user)
    for row in (earlier, later):
        repository.link_identity(row['id'], common)
        repository.set_state(row['id'], lesson_state='ready')
        lesson_artifacts(repository, row)
    (later['path'] / 'result.json').unlink()
    item = repository.history(user)['items'][0]
    assert item['search_id'] == earlier['id'] and item['lesson_available']
    assert item['latest_status'] == item['lesson_status'] == 'unavailable'
    assert repository.submission(user, earlier['id'])['lesson_status'] == 'ready'
    assert repository.submission(user, later['id'])['lesson_status'] == 'unavailable'


@pytest.mark.parametrize('missing', [
    'postgres_run', 'legacy_sqlite', 'result.json', 'crop.json', 'question.png',
    'stage-two-1/stage-two-result.json', 'stage-two-1/stage-three/run.json',
    'stage-two-1/stage-three/frozen.json', 'stage-two-1/stage-three/stage-three-result.json',
])
def test_ready_submission_missing_runtime_authority_or_files_is_unavailable_without_rewriting_history(repository, missing):
    user = student(repository)
    row, _ = submission(repository, user)
    repository.link_identity(row['id'], identity())
    lesson_artifacts(repository, row)
    repository.set_state(row['id'], lesson_state='ready')
    assert repository.submission(user, row['id'])['lesson_status'] == 'ready'
    output = row['path'] / 'stage-two-1/stage-three'
    if missing in {'postgres_run', 'legacy_sqlite'}:
        run_id = json.loads((output / 'run.json').read_text())['run_id']
        runs = metadata.tables['lesson_runs']
        with repository.db.begin() as connection:
            connection.execute(runs.delete().where(runs.c.run_id == run_id))
        if missing == 'legacy_sqlite':
            (output / 'events.sqlite3').write_bytes(b'legacy archival evidence, never authoritative')
    else:
        (row['path'] / missing).unlink()
    detail = repository.submission(user, row['id'])
    assert detail['lesson_status'] == 'unavailable' and detail['artifact_state'] == 'active'
    assert detail['statement']
    history = repository.history(user)['items'][0]
    assert history['search_id'] == row['id'] and not history['lesson_available']
    assert history['latest_status'] == history['lesson_status'] == 'unavailable'
    with repository.db.connect() as connection:
        assert connection.scalar(sa.select(SUBMISSIONS.c.lesson_status).where(SUBMISSIONS.c.id == row['id'])) == 'ready'


def test_expired_linked_directory_recreated_by_late_reader_is_cleaned_again(repository):
    user = student(repository)
    row, _ = submission(repository, user)
    repository.link_identity(row['id'], identity())
    repository.test_time[0] += timedelta(days=30)
    repository.cleanup()
    assert not row['path'].exists()
    row['path'].mkdir()
    (row['path'] / 'private-result.json').write_text('late-reader')
    os.utime(row['path'], (repository.clock().timestamp(), repository.clock().timestamp()))
    repository.cleanup()
    assert not row['path'].exists()


def test_cleanup_does_not_lock_processed_history_without_new_expiry(repository):
    user = student(repository)
    row, _ = submission(repository, user)
    repository.link_identity(row['id'], identity())
    repository.test_time[0] += timedelta(days=30)
    repository.cleanup()
    statements = []

    def record_locks(_connection, _cursor, statement, _parameters, _context, _executemany):
        if 'FOR UPDATE' in statement:
            statements.append(statement)

    sa.event.listen(repository.db, 'before_cursor_execute', record_locks)
    try:
        assert repository.cleanup() == {'removed': 0, 'orphans_removed': 0}
    finally:
        sa.event.remove(repository.db, 'before_cursor_execute', record_locks)
    assert statements == []
    assert repository.submission(user, row['id'])['artifact_state'] == 'expired'


def test_cleanup_processes_new_expiry_on_already_expired_page_without_relocking_old_submission(repository):
    user = student(repository)
    page_id = page(repository, user)
    earlier, _ = submission(repository, user, page_id)
    repository.link_identity(earlier['id'], identity())
    repository.test_time[0] += timedelta(hours=1)
    later, _ = submission(repository, user, page_id)
    repository.link_identity(later['id'], identity())
    repository.test_time[0] = earlier['expires_at']
    repository.cleanup()
    assert not earlier['path'].exists() and later['path'].exists()
    assert repository.page(user, page_id, require_image=False)['image_state'] == 'expired'
    repository.test_time[0] = later['expires_at']

    def bound_lock_wait(connection):
        if current_thread().name.startswith('cleanup-new-expiry'):
            connection.exec_driver_sql("SET LOCAL statement_timeout = '1500ms'")

    sa.event.listen(repository.db, 'begin', bound_lock_wait)
    try:
        with ThreadPoolExecutor(1, thread_name_prefix='cleanup-new-expiry') as pool, repository.db.begin() as connection:
            connection.execute(sa.select(SUBMISSIONS).where(SUBMISSIONS.c.id == earlier['id']).with_for_update())
            result = pool.submit(repository.cleanup).result(timeout=5)
    finally:
        sa.event.remove(repository.db, 'begin', bound_lock_wait)
    assert result['removed'] == 1
    assert not later['path'].exists()
    assert repository.submission(user, later['id'])['artifact_state'] == 'expired'


def test_cleanup_deletes_expired_unlinked_submission_even_if_artifacts_already_expired(repository):
    user = student(repository)
    row, _ = submission(repository, user)
    with repository.db.begin() as connection:
        connection.execute(SUBMISSIONS.update().where(SUBMISSIONS.c.id == row['id']).values(artifact_state='expired'))
    repository.test_time[0] = row['expires_at']
    repository.cleanup()
    assert count(repository, SUBMISSIONS, SUBMISSIONS.c.id == row['id']) == 0
    assert not row['path'].exists()


@pytest.mark.parametrize('category', ['pages', 'submissions'])
def test_recreated_expired_directory_failure_is_queued_for_retry(repository, monkeypatch, category):
    user = student(repository)
    row, _ = submission(repository, user)
    repository.link_identity(row['id'], identity())
    repository.test_time[0] = row['expires_at']
    repository.cleanup()
    key = repository.storage.page_key(row['page_id']) if category == 'pages' else row['storage_key']
    directory = repository.storage.path(key)
    directory.mkdir()
    (directory / 'late.json').write_text('private')
    os.utime(directory, (repository.clock().timestamp(), repository.clock().timestamp()))
    original_remove = repository.storage.remove

    def unavailable(candidate):
        if candidate == key:
            raise OSError('unavailable')
        return original_remove(candidate)

    monkeypatch.setattr(repository.storage, 'remove', unavailable)
    repository.cleanup()
    pending = repository.page(user, row['page_id'], require_image=False)['pending_cleanup_keys']
    assert len(pending) == 1 and pending[0]['key'] == key
    repository.cleanup()
    pending = repository.page(user, row['page_id'], require_image=False)['pending_cleanup_keys']
    assert pending[0]['attempts'] == 1 and pending[0]['last_error_code'] == 'OSError'
    monkeypatch.setattr(repository.storage, 'remove', original_remove)
    repository.cleanup()
    assert not directory.exists()
    assert repository.page(user, row['page_id'], require_image=False)['pending_cleanup_keys'] == []


def test_cleanup_rechecks_page_candidate_after_another_cleaner_finishes(repository):
    user = student(repository)
    row, _ = submission(repository, user)
    repository.link_identity(row['id'], identity())
    repository.test_time[0] = row['expires_at']
    selected, processed = Event(), Event()

    def pause_candidates(_connection, _cursor, statement, _parameters, _context, _executemany):
        if (current_thread().name.startswith('stale-cleaner') and statement.startswith('SELECT search_pages.id \n')
                and not selected.is_set()):
            selected.set()
            assert processed.wait(5)

    def bound_lock_wait(connection):
        if current_thread().name.startswith('stale-cleaner'):
            connection.exec_driver_sql("SET LOCAL statement_timeout = '1500ms'")

    sa.event.listen(repository.db, 'after_cursor_execute', pause_candidates)
    sa.event.listen(repository.db, 'begin', bound_lock_wait)
    try:
        with ThreadPoolExecutor(1, thread_name_prefix='stale-cleaner') as pool:
            cleanup = pool.submit(repository.cleanup)
            try:
                assert selected.wait(5)
                repository.cleanup()
                with repository.db.begin() as connection:
                    connection.execute(sa.select(PAGES).where(PAGES.c.id == row['page_id']).with_for_update())
                    processed.set()
                    assert cleanup.result(timeout=5) == {'removed': 0, 'orphans_removed': 0}
            finally:
                processed.set()
    finally:
        sa.event.remove(repository.db, 'after_cursor_execute', pause_candidates)
        sa.event.remove(repository.db, 'begin', bound_lock_wait)


def test_cleanup_waits_for_shared_reader_without_blocking_generation(repository):
    user = student(repository)
    row, _ = submission(repository, user)
    with repository.storage.read_lock(row['id']):
        with repository.lifecycle_lock(row['id']):
            assert row['path'].exists()
        repository.delete(user, row['id'])
        repository.cleanup()
        assert row['path'].exists()
    repository.cleanup()
    assert not row['path'].exists()


@pytest.mark.parametrize('change', ['delete', 'associate', 'delete_linked'])
def test_history_uses_one_snapshot_when_group_changes_concurrently(repository, change):
    user = student(repository)
    row, _ = submission(repository, user)
    problem = repository.link_identity(row['id'], identity()) if change == 'delete_linked' else None
    selected, modified = Event(), Event()

    def after_selection(_connection, _cursor, statement, _parameters, _context, _executemany):
        if 'coalesce(' in statement and 'search_submissions' in statement and not selected.is_set():
            selected.set()
            assert modified.wait(5)

    def change_group():
        try:
            assert selected.wait(5)
            if change in {'delete', 'delete_linked'}:
                repository.delete(user, row['id'])
            else:
                repository.link_identity(row['id'], identity())
        finally:
            modified.set()

    sa.event.listen(repository.db, 'after_cursor_execute', after_selection)
    try:
        with ThreadPoolExecutor(1) as pool:
            changed = pool.submit(change_group)
            history = repository.history(user)
            changed.result()
    finally:
        sa.event.remove(repository.db, 'after_cursor_execute', after_selection)
    if change in {'delete', 'delete_linked'}:
        assert history['items'] == []
    else:
        assert [item['search_id'] for item in history['items']] == [row['id']]
        assert history['items'][0]['problem_id'] == (str(problem['id']) if problem else None)
    assert not history['has_more']
    latest = repository.history(user)['items']
    if change in {'delete', 'delete_linked'}:
        assert latest == []
    else:
        assert latest[0]['problem_id'] is not None


def test_history_reuses_validated_deletion_snapshots_for_full_page(repository, monkeypatch):
    user = student(repository)
    page_id = page(repository, user)
    rows = [submission(repository, user, page_id)[0] for _index in range(100)]
    submission(repository, student(repository))
    snapshots, statements = [], []
    original = repository.recovery.snapshot

    def snapshot():
        snapshots.append(True)
        return original()

    def record_statement(_connection, _cursor, statement, *_args):
        if 'search_recovery_state' in statement:
            statements.append(statement)

    monkeypatch.setattr(repository.recovery, 'snapshot', snapshot)
    sa.event.listen(repository.db, 'before_cursor_execute', record_statement)
    try:
        history = repository.history(user, limit=100)
    finally:
        sa.event.remove(repository.db, 'before_cursor_execute', record_statement)
    assert {item['search_id'] for item in history['items']} == {row['id'] for row in rows}
    assert not history['has_more']
    assert len(snapshots) == len(statements) == 3


@pytest.mark.parametrize('linked', [False, True])
def test_history_rechecks_deletions_after_item_decoration(repository, monkeypatch, linked):
    user = student(repository)
    rows = [submission(repository, user)[0] for _index in range(2)]
    if linked:
        common = identity()
        for row in rows:
            repository.link_identity(row['id'], common)
    original = repository._decorate
    deleted = []

    with ThreadPoolExecutor(1) as pool:
        def decorate(connection, row, **kwargs):
            value = original(connection, row, **kwargs)
            if not deleted:
                result = pool.submit(repository.delete, user, row['id']).result(timeout=5)
                deleted.extend(result['deleted_search_ids'])
            return value

        monkeypatch.setattr(repository, '_decorate', decorate)
        history = repository.history(user)
    assert {item['search_id'] for item in history['items']} == {row['id'] for row in rows} - set(deleted)
    assert not history['has_more']


def test_history_rejects_journal_damage_during_decoration(repository, monkeypatch):
    user = student(repository)
    submission(repository, user)
    original = repository._decorate

    def decorate(connection, row, **kwargs):
        value = original(connection, row, **kwargs)
        with repository.recovery.path.open('ab') as stream:
            stream.write(b'{"sequence":')
        return value

    monkeypatch.setattr(repository, '_decorate', decorate)
    with pytest.raises(SearchError, match='recovery.truncated'):
        repository.history(user)


def test_identity_link_rechecks_expiry_after_waiting_for_public_problem(repository):
    original_user, arriving_user = student(repository), student(repository)
    original, _ = submission(repository, original_user)
    arriving, _ = submission(repository, arriving_user)
    common = identity()
    problem = repository.link_identity(original['id'], common)
    attempted = Event()

    def before_lock(_connection, _cursor, statement, _parameters, _context, _executemany):
        if current_thread().name.startswith('late-associate') and 'search_problems' in statement and 'FOR UPDATE' in statement:
            attempted.set()

    sa.event.listen(repository.db, 'before_cursor_execute', before_lock)
    try:
        with ThreadPoolExecutor(1, thread_name_prefix='late-associate') as pool:
            with repository.db.begin() as connection:
                connection.execute(sa.select(PROBLEMS).where(PROBLEMS.c.id == problem['id']).with_for_update())
                linked = pool.submit(repository.link_identity, arriving['id'], common)
                assert attempted.wait(5)
                repository.test_time[0] += timedelta(days=30)
            assert linked.result() is None
    finally:
        sa.event.remove(repository.db, 'before_cursor_execute', before_lock)
    assert count(repository, RELATIONS, RELATIONS.c.user_id == arriving_user) == 0
    with repository.db.connect() as connection:
        assert connection.scalar(sa.select(SUBMISSIONS.c.problem_id).where(SUBMISSIONS.c.id == arriving['id'])) is None


def test_identity_link_rolls_back_new_public_problem_if_it_expires_before_commit(repository):
    user = student(repository)
    row, _ = submission(repository, user)
    common = identity()
    advanced = Event()

    def expire_before_commit(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.startswith('INSERT INTO student_search_problems') and not advanced.is_set():
            advanced.set()
            repository.test_time[0] += timedelta(days=30)

    sa.event.listen(repository.db, 'after_cursor_execute', expire_before_commit)
    try:
        assert repository.link_identity(row['id'], common) is None
    finally:
        sa.event.remove(repository.db, 'after_cursor_execute', expire_before_commit)
    assert advanced.is_set()
    assert count(repository, RELATIONS, RELATIONS.c.user_id == user) == 0
    assert count(repository, PROBLEMS, PROBLEMS.c.fingerprint == common['fingerprint']) == 0


def test_recovery_rechecks_terminal_state_after_worker_finishes(repository):
    user = student(repository)
    row, _ = submission(repository, user)
    lesson_artifacts(repository, row)
    selected, completed = Event(), Event()

    def finish():
        try:
            assert selected.wait(5)
            with repository.lifecycle_lock(row['id']):
                repository.set_state(row['id'], recognition_state='reviewed', lesson_state='ready')
        finally:
            completed.set()

    def after_selection(_connection, _cursor, statement, _parameters, _context, _executemany):
        if 'SELECT search_submissions.id' in statement and 'recognition_status IN' in statement and not selected.is_set():
            selected.set()
            assert completed.wait(5)

    sa.event.listen(repository.db, 'after_cursor_execute', after_selection)
    try:
        with ThreadPoolExecutor(1) as pool:
            finished = pool.submit(finish)
            assert repository.recover() == 0
            finished.result()
    finally:
        sa.event.remove(repository.db, 'after_cursor_execute', after_selection)
    saved = repository.submission(user, row['id'])
    assert saved['lesson_status'] == 'ready' and saved['error_code'] is None


def test_two_orphan_cleaners_tolerate_removal_between_directory_check_and_stat(repository, monkeypatch):
    orphan = repository.storage.path(repository.storage.submission_key(secrets.token_hex(6)))
    orphan.mkdir()
    old = (repository.clock() - timedelta(hours=2)).timestamp()
    os.utime(orphan, (old, old))
    original_is_dir = Path.is_dir
    inspected, removed = Event(), Event()

    def pause_candidate(path):
        result = original_is_dir(path)
        if path == orphan and current_thread().name.startswith('first-cleaner') and result:
            inspected.set()
            assert removed.wait(5)
        return result

    monkeypatch.setattr(Path, 'is_dir', pause_candidate)
    with ThreadPoolExecutor(1, thread_name_prefix='first-cleaner') as pool:
        first = pool.submit(repository.cleanup_orphans)
        try:
            assert inspected.wait(5)
            assert repository.cleanup_orphans() == 1
        finally:
            removed.set()
        assert first.result() == 0


@pytest.mark.parametrize('key', ['pages/', 'submissions/', 'pages/unknown'])
def test_cleanup_key_cannot_remove_a_category_or_unmanaged_directory(repository, key):
    with pytest.raises(SearchError, match='storage.invalid_cleanup_key'):
        repository.storage.remove(key)
    assert repository.storage.path('pages').is_dir()
    assert repository.storage.path('submissions').is_dir()


def test_rotation_registration_rechecks_parent_expiry_after_lock_wait(repository):
    user = student(repository)
    parent_id = page(repository, user)
    attempted = Event()

    def before_parent_lock(_connection, _cursor, statement, _parameters, _context, _executemany):
        if current_thread().name.startswith('late-rotation') and 'search_pages' in statement and 'FOR UPDATE' in statement:
            attempted.set()

    sa.event.listen(repository.db, 'before_cursor_execute', before_parent_lock)
    try:
        with ThreadPoolExecutor(1, thread_name_prefix='late-rotation') as pool:
            with repository.db.begin() as connection:
                connection.execute(sa.select(PAGES).where(PAGES.c.id == parent_id).with_for_update())
                rotated = pool.submit(page, repository, user, parent_id)
                assert attempted.wait(5)
                repository.test_time[0] += timedelta(hours=24)
            with pytest.raises(SearchError, match='page.expired'):
                rotated.result()
    finally:
        sa.event.remove(repository.db, 'before_cursor_execute', before_parent_lock)
    assert count(repository, PAGES, PAGES.c.user_id == user) == 1


def test_two_cleaners_preserve_cleanup_appended_during_file_removal(repository, monkeypatch):
    user = student(repository)
    page_id = page(repository, user)
    earlier, _ = submission(repository, user, page_id)
    later, _ = submission(repository, user, page_id)
    repository.delete(user, earlier['id'])
    original_remove = repository.storage.remove
    removed, acknowledged = Event(), Event()

    def pause_removal(key):
        original_remove(key)
        if key == earlier['storage_key'] and current_thread().name.startswith('first-cleaner'):
            removed.set()
            assert acknowledged.wait(5)

    monkeypatch.setattr(repository.storage, 'remove', pause_removal)
    with ThreadPoolExecutor(1, thread_name_prefix='first-cleaner') as pool:
        first = pool.submit(repository.cleanup)
        try:
            assert removed.wait(5)
            repository.delete(user, later['id'])
            assert repository.cleanup()['removed'] == 1
        finally:
            acknowledged.set()
        assert first.result()['removed'] == 1
    assert not earlier['path'].exists() and not later['path'].exists()
    assert repository.page(user, page_id)['pending_cleanup_keys'] == []


def test_deleting_linked_group_keeps_separately_finishing_submission(repository, monkeypatch):
    user = student(repository)
    earlier, _ = submission(repository, user)
    common = identity()
    repository.link_identity(earlier['id'], common)
    repository.test_time[0] += timedelta(seconds=1)
    pending, _ = submission(repository, user)
    original_page = repository._page
    selected, linked = Event(), Event()

    def pause_deletion(*args, **kwargs):
        if current_thread().name.startswith('delete-linked-group'):
            selected.set()
            assert linked.wait(5)
        return original_page(*args, **kwargs)

    monkeypatch.setattr(repository, '_page', pause_deletion)
    with ThreadPoolExecutor(1, thread_name_prefix='delete-linked-group') as pool:
        deleted = pool.submit(repository.delete, user, earlier['id'])
        try:
            assert selected.wait(5)
            repository.link_identity(pending['id'], common)
        finally:
            linked.set()
        assert deleted.result()['deleted_search_ids'] == [earlier['id']]
    assert repository.history(user)['items'][0]['search_id'] == pending['id']
    with repository.db.connect() as connection:
        relation = connection.execute(sa.select(RELATIONS).where(RELATIONS.c.user_id == user)).mappings().one()
    assert relation['first_searched_at'] == relation['last_searched_at'] == pending['created_at']


@pytest.mark.parametrize('operation', ['rewrite', 'delete'])
def test_public_problem_trigger_protects_content_even_for_table_owner(repository, operation):
    user = student(repository)
    row, _ = submission(repository, user)
    problem = repository.link_identity(row['id'], identity())
    owner = engine(repository.test_settings.url('migration'))
    try:
        with pytest.raises(DBAPIError), owner.begin() as connection:
            connection.exec_driver_sql(f'SET LOCAL search_path TO "{repository.test_schema}", public')
            statement = (PROBLEMS.update().values(statement='changed') if operation == 'rewrite' else PROBLEMS.delete())
            connection.execute(statement.where(PROBLEMS.c.id == problem['id']))
    finally:
        owner.dispose()
    assert repository.submission(user, row['id'])['statement'] == problem['statement']
