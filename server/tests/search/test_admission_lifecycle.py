"""Real lifecycle races across PostgreSQL admission and request worker threads."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
from threading import Event, current_thread

import pytest
import sqlalchemy as sa
from fastapi import Request
from fastapi.testclient import TestClient
from PIL import Image
from starlette.concurrency import run_in_threadpool

from shuxueshuo_server.auth.api import AuthBoundary, cookie_name
from shuxueshuo_server.product.db import transaction
from shuxueshuo_server.search import dev_api
from shuxueshuo_server.search.admission import TICKETS
from shuxueshuo_server.search.repository import PAGES
from shuxueshuo_server.search.task_runner import SearchTaskRunner
from shuxueshuo_server.search.upload_admission import (
    UploadAdmission,
    UploadAdmissionBusy,
)
from tests.search.test_private_api import login, upload
from tests.search.test_private_api import private_app as private_app_fixture
from tests.search.test_repository import page, student, submission
from tests.search.test_repository import repository as repository_fixture
from tests.search.test_task_runner import HeldExecutor
from tests.search.test_upload_admission import fixture_app, fixture_request


@pytest.fixture
def repository(tmp_path):
    yield from repository_fixture.__wrapped__(tmp_path)


@pytest.fixture
def private_app(repository, monkeypatch):
    return private_app_fixture.__wrapped__(repository, monkeypatch)


@pytest.mark.parametrize('sync_endpoint', [False, True])
def test_cancelled_asgi_request_keeps_upload_slot_until_ocr_thread_finishes(sync_endpoint):
    async def scenario():
        app, _boundary = fixture_app(account_limit=1, global_limit=1)
        app.add_middleware(AuthBoundary)
        entered, release, finished = Event(), Event(), Event()

        def blocking_ocr(request):
            with request.state.search_upload_lease.hold():
                entered.set()
                try:
                    assert release.wait(10)
                    return {'ok': True}
                finally:
                    finished.set()

        if sync_endpoint:
            @app.post('/api/search/pages/123456abcdef/rotate')
            def rotate(request: Request):
                return blocking_ocr(request)

            path = '/api/search/pages/123456abcdef/rotate'
        else:
            @app.post('/api/search/pages')
            async def upload(request: Request):
                await request.body()
                return await run_in_threadpool(blocking_ocr, request)

            path = '/api/search/pages'
        original, _received = fixture_request(app, path=path)
        disconnected = asyncio.Event()
        sent = []
        supplied = False

        async def receive():
            nonlocal supplied
            if not supplied:
                supplied = True
                return {'type': 'http.request', 'body': b'fixture', 'more_body': False}
            await disconnected.wait()
            return {'type': 'http.disconnect'}

        async def send(message):
            sent.append(message)

        task = asyncio.create_task(app(original.scope, receive, send))
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            assert app.state.search_upload_admission._total == 1
            disconnected.set()
            task.cancel()
            for _index in range(20):
                await asyncio.sleep(0)
            assert not finished.is_set()
            assert app.state.search_upload_admission._total == 1
        finally:
            release.set()
            try:
                await asyncio.wait_for(task, 3)
            except asyncio.CancelledError:
                pass
        assert finished.is_set()
        assert app.state.search_upload_admission._total == 0

    asyncio.run(scenario())


def test_expiry_cleanup_does_not_hold_admission_control_before_locking_another_page(repository):
    first = student(repository)
    pages = sorted([page(repository, first), page(repository, first)])
    first_old, _created = submission(repository, first, pages[0])
    second_old, _created = submission(repository, first, pages[1])
    repository.test_time[0] += timedelta(hours=18)
    live, _created = submission(repository, first, pages[1])
    repository.test_time[0] += timedelta(days=29, hours=18)
    page_held, cleanup_waiting_for_page = Event(), Event()

    def inspect_statement(_connection, _cursor, statement, parameters, _context, _executemany):
        if (current_thread().name.startswith('expiry-cleanup') and 'FROM search_pages' in statement
                and 'FOR UPDATE' in statement and pages[1] in parameters.values()):
            cleanup_waiting_for_page.set()

    sa.event.listen(repository.db, 'before_cursor_execute', inspect_statement)

    def reserve_on_second_page():
        with transaction(repository.db) as connection:
            connection.execute(sa.select(PAGES.c.id).where(PAGES.c.id == pages[1]).with_for_update()).one()
            page_held.set()
            assert cleanup_waiting_for_page.wait(5)
            return repository.reserve_lesson(first, live['id'], 'continuation')

    def cleanup():
        assert page_held.wait(5)
        return repository.cleanup()

    try:
        with (ThreadPoolExecutor(1, thread_name_prefix='other-page') as requests,
              ThreadPoolExecutor(1, thread_name_prefix='expiry-cleanup') as maintenance):
            admitted = requests.submit(reserve_on_second_page)
            cleaned = maintenance.submit(cleanup)
            ticket = admitted.result(timeout=8)
            assert cleaned.result(timeout=8)['removed'] >= 2
        assert repository.admission.get_ticket(ticket.id).state == 'reserved'
        assert repository.submission(first, live['id'])['artifact_state'] == 'active'
        with repository.db.connect() as connection:
            assert connection.scalar(sa.text('SELECT count(*) FROM search_submissions WHERE id IN (:first,:second)'),
                {'first': first_old['id'], 'second': second_old['id']}) == 0
    finally:
        sa.event.remove(repository.db, 'before_cursor_execute', inspect_statement)


@pytest.mark.parametrize('rotating', [False, True])
def test_real_search_upload_and_rotation_keep_slots_until_cancelled_workers_finish(private_app, monkeypatch, rotating):
    app, auth = private_app
    admission = UploadAdmission(account_limit=1, global_limit=1)
    app.state.search_upload_admission = admission
    entered, release, finished = Event(), Event(), Event()

    def observe(_client, *_args, **_kwargs):
        entered.set()
        try:
            assert release.wait(10)
            return {'width': 100, 'height': 100, 'lines': [], 'layout': [], 'latency_ms': {'detect': 0}}
        finally:
            finished.set()

    with TestClient(app, base_url=auth.config.origin) as client:
        user, token = login(client, auth)
        if rotating:
            source = upload(client)
            path = '/api/search/pages/' + source['page_id'] + '/rotate'
            body = b'{"degrees":90}'
            content_type = b'application/json'
        else:
            path = '/api/search/pages'
            photo = BytesIO()
            Image.new('RGB', (100, 100), 'white').save(photo, 'PNG')
            body, content_type = photo.getvalue(), b'image/png'
        monkeypatch.setattr(dev_api.OcrClient, 'observe', observe)

        async def scenario():
            disconnected = asyncio.Event()
            supplied = False
            scope = {'type': 'http', 'method': 'POST', 'path': path, 'scheme': 'https',
                'server': ('testserver', 443), 'client': ('127.0.0.1', 80), 'query_string': b'', 'app': app,
                'headers': [(b'origin', auth.config.origin.encode()), (b'x-search-user', user['id'].encode()),
                            (b'cookie', f'{cookie_name(auth.config)}={token}'.encode()),
                            (b'content-type', content_type)]}

            async def receive():
                nonlocal supplied
                if not supplied:
                    supplied = True
                    return {'type': 'http.request', 'body': body, 'more_body': False}
                await disconnected.wait()
                return {'type': 'http.disconnect'}

            async def send(_message):
                pass

            task = asyncio.create_task(app(scope, receive, send))
            try:
                assert await asyncio.to_thread(entered.wait, 3)
                disconnected.set()
                task.cancel()
                for _index in range(20):
                    await asyncio.sleep(0)
                assert not finished.is_set()
                assert admission._total == 1
                with pytest.raises(UploadAdmissionBusy), admission.admit(user['id']):
                    pytest.fail('A cancelled request released an active OCR worker slot')
            finally:
                release.set()
                try:
                    await asyncio.wait_for(task, 3)
                except asyncio.CancelledError:
                    pass
            assert finished.is_set()
            assert admission._total == 0

        asyncio.run(scenario())


def test_cancelled_upload_lease_cannot_start_a_late_worker_or_release_twice():
    admission = UploadAdmission(account_limit=1, global_limit=1)
    with admission.admit('owner') as lease:
        worker = lease.hold()
        worker.__enter__()
    assert admission._total == 1
    lease.release_request()
    assert admission._total == 1
    with pytest.raises(UploadAdmissionBusy), lease.hold():
        pytest.fail('An already cancelled request started a second worker')
    worker.__exit__(None, None, None)
    assert admission._total == 0
    with pytest.raises(UploadAdmissionBusy), lease.hold():
        pytest.fail('An expired lease was resurrected')
    assert admission._total == 0


def test_database_finish_retry_unblocks_account_and_repairs_nonterminal_history(repository, monkeypatch):
    owner = student(repository)
    row, _created = submission(repository, owner)
    repository.admission.set_generation_enabled(True)
    ticket = repository.admission.reserve(owner, 'generation', row['id'])
    executor = HeldExecutor()
    runner = SearchTaskRunner(executor, workers=1, queue_size=0)
    original = repository.admission.finish
    attempts, executions = [], []

    def finish(identifier):
        attempts.append(identifier)
        if len(attempts) == 1:
            raise OSError('fixture lost database connection after work completed')
        return original(identifier)

    def work():
        executions.append(ticket.id)
        repository.set_state(row['id'], recognition_state='running')

    monkeypatch.setattr(repository.admission, 'finish', finish)
    runner.submit(ticket, repository, work, lambda: pytest.fail('started work must not be cancelled'))
    executor.drain()
    assert repository.admission.get_ticket(ticket.id).state == 'running'
    assert repository.submission(owner, row['id'])['recognition_status'] == 'running'
    runner.reap()
    runner.shutdown()
    assert executions == [ticket.id]
    assert not runner.finalizations
    assert repository.admission.get_ticket(ticket.id).state == 'finished'
    assert repository.submission(owner, row['id'])['recognition_status'] == 'interrupted'
    with repository.db.connect() as connection:
        assert connection.scalar(sa.select(TICKETS.c.consumed).where(TICKETS.c.id == ticket.id))
    assert repository.admission.reserve(owner, 'continuation', row['id']).created


def test_old_finalization_cannot_interrupt_a_new_run_on_the_same_submission(repository):
    owner = student(repository)
    row, _created = submission(repository, owner)
    admission = repository.admission
    admission.set_generation_enabled(True)
    old = admission.reserve(owner, 'generation', row['id'])
    admission.start(old.id)
    admission.finish(old.id)
    current = repository.reserve_lesson(owner, row['id'], 'continuation')
    repository.interrupt_admitted(old)
    assert repository.submission(owner, row['id'])['lesson_status'] == 'running'
    admission.start(current.id)
    repository.set_state(row['id'], recognition_state='reviewed', lesson_state='failed')
    admission.finish(current.id)
    repository.interrupt_admitted(old)
    assert repository.submission(owner, row['id'])['lesson_status'] == 'failed'
