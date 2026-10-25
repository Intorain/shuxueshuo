"""Explicit offline adapters and black-box checks; excluded from production images."""

import argparse
import importlib.util
import json
import os
import secrets
import shutil
import ssl
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from contextlib import asynccontextmanager
from hashlib import sha256
from io import BytesIO
from pathlib import Path

FIXTURES = Path('/rehearsal')
DATA = Path('/var/lib/shuxueshuo')
ORIGIN = 'https://shuxueshuo.com'


def forbidden(*_args, **_kwargs):
    raise AssertionError('Offline rehearsal forbids live models and real SMS')


def api():
    if os.getenv('SEARCH_OFFLINE_REHEARSAL') != '1':
        raise RuntimeError('Offline fixture API requires SEARCH_OFFLINE_REHEARSAL=1')
    import uvicorn

    from shuxueshuo_server.auth import api as auth_api
    from shuxueshuo_server.auth.sms import MockSms
    from shuxueshuo_server.graph_lesson.stage_one.runner import candidate_features
    from shuxueshuo_server.graph_lesson.stage_two import selection
    from shuxueshuo_server.graph_lesson.stage_two.runner import replay_run
    from shuxueshuo_server.problem_understanding import batch_smoke
    from shuxueshuo_server.problem_understanding.identity import revision
    from shuxueshuo_server.problem_understanding.workflow_ledger import save
    from shuxueshuo_server.search import dev_api, stage_three
    from shuxueshuo_server.search.identity import (
        EXTRACTION_CONTRACT,
        mathematical_candidate,
    )
    from shuxueshuo_server.solver.extraction import multimodal_provider

    auth_api.AliyunSms = lambda _config: MockSms(DATA / 'work/rehearsal-sms')
    batch_smoke.live_provider_factory = lambda *_args, **_kwargs: lambda: object()
    selection.live_provider_factory = lambda *_args, **_kwargs: forbidden
    multimodal_provider._default_client_factory = forbidden

    def recognize(png, directory, _provider, *, problem_id):
        candidate = json.loads((FIXTURES / 'candidate.json').read_text())
        candidate['public_content'] = {
            'completeness': 'complete', 'privacy': 'separated', 'figure': 'not_required',
            'scopes': [{'scope_ref': '/root', 'statement': candidate['original_text'],
                        'choices': [{'target_ref': '/root/goals/0', 'status': 'none',
                                     'selection_mode': 'none', 'options': []}]}],
        }
        projected = mathematical_candidate(candidate)
        features = candidate_features(projected)
        result = {
            'status': 'reviewed_candidate', 'source_reviewed': True, 'output_contract': EXTRACTION_CONTRACT,
            'candidate': projected, 'public_candidate': candidate, 'reviewed_candidate_revision': revision(candidate),
            'question_sha256': sha256(png).hexdigest(), 'sent_image_sha256': [sha256(png).hexdigest()],
            'review_findings': [], 'features': features['features'], 'features_ok': features['ok'],
            'elapsed_seconds': 0, 'offline_fixture': 'synthetic-review-not-model-evidence',
        }
        save(directory / dev_api.RESULT_FILE, result)
        return result

    def classify(directory, *_args, **_kwargs):
        output = directory / f'stage-two-{len(stage_three.attempts(directory)) + 1}'
        result = replay_run(FIXTURES / 'recording', output)
        assert result['replay_comparison']['ok'] and result['llm']['new_network_attempts'] == 0
        return result

    dev_api.run_question_image = recognize
    dev_api.run_stage_two = classify
    from shuxueshuo_server.main import app

    previous_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def fixture_lifespan(application):
        async with previous_lifespan(application) as state:
            application.state.search_repository.admission.set_generation_enabled(True)
            yield state

    app.router.lifespan_context = fixture_lifespan
    uvicorn.run(app, host='0.0.0.0', port=8000, proxy_headers=True,
                forwarded_allow_ips='127.0.0.1', access_log=False)


def ocr():
    from PIL import Image

    specification = importlib.util.spec_from_file_location('rehearsal_sidecar', FIXTURES / 'sidecar_server.py')
    sidecar = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(sidecar)

    def observe(image, *, auto_orient=True):
        with Image.open(image) as source:
            width, height = source.size
        scale = min(1.0, 1600 / max(width, height))
        width, height = round(width * scale), round(height * scale)
        return {'width': width, 'height': height, 'lines': [], 'layout': [], 'latency_ms': {'detect': 0},
                'orientation': {'status': 'upright' if auto_orient else 'manual', 'rotation_degrees': 0,
                                'predicted_degrees': 0 if auto_orient else None, 'confidence': 1.0}}

    sidecar.warmup = lambda: None
    sidecar.infer_search = observe
    raise SystemExit(sidecar.main())


def client():
    import httpx

    return httpx.Client(base_url=ORIGIN, verify=False, trust_env=False, timeout=180,
                        headers={'Origin': ORIGIN})


def checked(response, code=200):
    assert response.status_code == code, (response.status_code, response.text[:500])
    return response.json()


def login(browser, phone):
    challenge = checked(browser.post('/api/auth/sms/send', json={'phone': phone}))
    message = json.loads((DATA / f"work/rehearsal-sms/{challenge['challenge_id']}.json").read_text())
    response = browser.post('/api/auth/sms/verify', json={
        'phone': phone, 'challenge_id': challenge['challenge_id'], 'code': message['code'],
    })
    checked(response)
    cookie = response.headers['set-cookie'].lower()
    assert '__host-sss_session=' in cookie and 'secure' in cookie and 'httponly' in cookie
    user = checked(browser.get('/api/auth/me'))['user']
    browser.headers['X-Search-User'] = user['id']
    return user


def wait_lesson(browser, search_id):
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        detail = checked(browser.get(f'/api/search/problems/{search_id}'))
        if detail['lesson_status'] == 'ready':
            return detail
        assert detail['lesson_status'] not in {'failed', 'unsupported', 'unavailable', 'interrupted'}, detail
        time.sleep(0.5)
    raise TimeoutError('Recorded lesson did not finish')


def database(role='app'):
    from shuxueshuo_server.product.config import Settings
    from shuxueshuo_server.product.db import engine

    return engine(Settings.load('server', instance='search-rehearsal').url(role))


def maintenance(*arguments):
    subprocess.run([sys.executable, '-m', 'shuxueshuo_server.search.maintenance',
                    '--mode', 'server', '--instance', 'search-rehearsal', *arguments], check=True)


def wait_admission_idle(user_id):
    from sqlalchemy import text

    database_engine = database()
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            with database_engine.connect() as connection:
                remaining = connection.scalar(text(
                    "SELECT count(*) FROM search_admission_tickets WHERE user_id=:user "
                    "AND state IN ('reserved', 'running')"), {'user': user_id})
            if remaining == 0:
                return
            time.sleep(0.05)
        raise TimeoutError('Offline admission tasks did not finish')
    finally:
        database_engine.dispose()


def exercise():
    from PIL import Image
    from sqlalchemy import text
    from websockets.sync.client import connect

    from shuxueshuo_server.search.repository import SearchRepository

    checks = []
    with client() as browser, client() as other:
        health = checked(browser.get('/api/health'))
        assert health['accepting'] is True and health['draining'] is False
        assert browser.get('/lab/search/').status_code == 200
        checked(browser.get('/api/search/problems'), 401)
        user = login(browser, '19900000001')
        checks.append('production HTTPS login and secure cookie with fixture-only SMS')
        image = (FIXTURES / 'recording/source.png').read_bytes()
        assert len(image) > 4096
        page = checked(browser.post('/api/search/pages', content=image))
        with Image.new('RGB', (6000, 4000), 'white') as photograph, BytesIO() as encoded:
            photograph.save(encoded, format='JPEG')
            photograph_bytes = encoded.getvalue()
            large_page = checked(browser.post('/api/search/pages', content=photograph_bytes))
        assert (large_page['width'], large_page['height']) == (4096, 2731)
        normalized = DATA / 'work/search/private-v1/pages' / large_page['page_id'] / 'source.png'
        with Image.open(normalized) as source:
            assert source.size == (4096, 2731) and source.mode == 'RGB'
        assert normalized.stat().st_size < 64 * 1024 * 1024
        checks.append('24MP JPEG normalizes before real sidecar path and image validation')
        with Image.new('1', (8000, 4000), 1) as boundary, BytesIO() as encoded:
            boundary.save(encoded, format='PNG')
            boundary_page = checked(browser.post('/api/search/pages', content=encoded.getvalue()))
        assert (boundary_page['width'], boundary_page['height']) == (4096, 2048)
        checks.append('exact 32MP low-bit-depth PNG is accepted and normalized')
        oversized_pixels = bytearray(photograph_bytes)
        frame = oversized_pixels.index(b'\xff\xc0')
        oversized_pixels[frame + 5:frame + 9] = (4000).to_bytes(2, 'big') + (8001).to_bytes(2, 'big')
        with Image.open(BytesIO(oversized_pixels)) as header:
            assert header.size == (8001, 4000)
        rejected = checked(browser.post('/api/search/pages', content=bytes(oversized_pixels)), 413)
        assert rejected['detail'] == 'page.pixels'
        checks.append('above-32MP JPEG header is rejected before decoding or sidecar inference')
        rotated = checked(browser.post(f"/api/search/pages/{page['page_id']}/rotate", json={'degrees': 90}))
        assert rotated['page_id'] != page['page_id']
        checked(browser.post('/api/search/pages', content=image, headers={'Origin': 'https://invalid.example'}), 403)
        oversized = browser.post('/api/search/pages', content=b'x' * (20 * 1024 * 1024 + 1))
        assert oversized.status_code == 413
        request = {'page_id': page['page_id'], 'box': [0, 0, 1, 1], 'client_request_id': 'offline-image-request'}
        first = checked(browser.post('/api/search/problems', json=request))['search_id']
        assert checked(browser.post('/api/search/problems', json=request))['search_id'] == first
        ready = wait_lesson(browser, first)
        assert ready['user_id'] == user['id'] and ready['problem_id']
        stream = ready['lesson']['stream']
        assert checked(browser.get(stream['snapshot_url']))['run_id'] == stream['run_id']
        event_response = browser.get(stream['events_url'])
        checked(event_response)
        assert 'no-store' in event_response.headers['cache-control']
        cookie = '; '.join(f'{key}={value}' for key, value in browser.cookies.items())
        path = stream['websocket_url']
        url = path if path.startswith('wss://') else 'wss://shuxueshuo.com' + path
        with connect(url, ssl=ssl._create_unverified_context(), origin=ORIGIN,
                     additional_headers={'Cookie': cookie}, open_timeout=15) as websocket:
            assert websocket.recv(timeout=15)
        checks.append('real sidecar HTTP upload/rotation, request idempotency, recorded lesson and TLS WebSocket')
        wait_admission_idle(user['id'])
        rejected = checked(browser.post('/api/search/problems', json={**request, 'client_request_id': 'over-quota'}), 429)
        assert rejected['detail'] == 'search.daily_generation_limit'
        rerun = {'client_request_id': 'offline-rerun'}
        checked(browser.post(f'/api/search/problems/{first}/lesson', json=rerun))
        ready = wait_lesson(browser, first)
        wait_admission_idle(user['id'])
        assert checked(browser.post(f'/api/search/problems/{first}/lesson', json=rerun))['duplicate'] is True
        rejected = checked(browser.post(f'/api/search/problems/{first}/lesson',
                                        json={'client_request_id': 'over-rerun-quota'}), 429)
        assert rejected['detail'] == 'search.daily_rerun_limit'
        checks.append('fixture-only daily limits of 1 generation and 1 rerun; durable rejection and rerun idempotency')
        maintenance('generation-stop')
        try:
            rejected = checked(browser.post('/api/search/problems',
                                            json={**request, 'client_request_id': 'paused-request'}), 503)
            assert rejected['detail'] == 'search.generation_paused'
            checked(browser.get(f'/api/search/problems/{first}'))
            checked(browser.get('/api/search/problems'))
        finally:
            maintenance('generation-enable')
        checks.append('operator expense stop rejects generation while preserving private reads')
        login(other, '19900000002')
        checked(other.get(f'/api/search/problems/{first}'), 404)
        assert checked(other.get('/api/search/problems'))['items'] == []
        checks.append('production account isolation and authenticated history')
        draining = DATA / 'locks/services-draining'
        draining.touch()
        try:
            health = checked(browser.get('/api/health'))
            assert health['draining'] is True and health['accepting'] is False
            checked(browser.post('/api/search/pages', content=image), 503)
            checked(browser.post(f'/api/search/problems/{first}/lesson'), 503)
            checked(browser.get(f'/api/search/problems/{first}'))
        finally:
            draining.unlink()
        assert checked(browser.get('/api/health'))['accepting'] is True
        checks.append('draining rejects new work but permits private reads')
        maintenance('disable', ready['problem_id'])
        assert checked(browser.get(f'/api/search/problems/{first}'))['outcome'] == 'disabled'
        deleted = checked(browser.delete(f'/api/search/problems/{first}'))
        assert deleted['deleted_search_ids'] == [first]
        checked(browser.get(f'/api/search/problems/{first}'), 404)
        assert browser.get(page['image_url']).status_code == 200
        checks.append('server operator disable, deletion and source-page retention')
        database_engine = database()
        try:
            repository = SearchRepository(database_engine, DATA / 'work/search/private-v1')
            pending = secrets.token_hex(6)
            directory = repository.storage.path(repository.storage.submission_key(pending))
            directory.mkdir()
            for filename in ('question.png', 'original.png'):
                shutil.copyfile(FIXTURES / 'recording/source.png', directory / filename)
            (directory / 'crop.json').write_text(json.dumps({'page_id': page['page_id']}))
            repository.create_submission(user, pending, page['page_id'], [0, 0, 1, 1], client_request_id='interrupted-fixture')
            with database_engine.connect() as connection:
                assert connection.scalar(text('SELECT count(*) FROM lesson_runs WHERE submission_id=:id'), {'id': first}) == 0
        finally:
            database_engine.dispose()
        migration = database('migration')
        try:
            with migration.begin() as connection:
                connection.execute(text('UPDATE search_pages SET created_at=:created, expires_at=:expired WHERE id=:id'),
                                   {'created': datetime.now(UTC) - timedelta(days=2),
                                    'expired': datetime.now(UTC) - timedelta(days=1), 'id': rotated['page_id']})
        finally:
            migration.dispose()
        state = {'checks': checks, 'pending': pending, 'expired_page': rotated['page_id'], 'user_id': user['id'],
                 'cookies': dict(browser.cookies.items())}
        path = DATA / 'work/rehearsal-state.json'
        path.write_text(json.dumps(state))
        path.chmod(0o600)


def recovery():
    from sqlalchemy import text

    state = json.loads((DATA / 'work/rehearsal-state.json').read_text())
    with client() as browser:
        browser.cookies.update(state['cookies'])
        browser.headers['X-Search-User'] = state['user_id']
        detail = checked(browser.get('/api/search/problems/' + state['pending']))
        assert detail['recognition_status'] == 'interrupted'
        checked(browser.get(f"/api/search/pages/{state['expired_page']}/image"), 410)
    expired = DATA / 'work/search/private-v1/pages' / state['expired_page']
    assert not expired.exists()
    database_engine = database()
    try:
        with database_engine.connect() as connection:
            assert connection.scalar(text('SELECT image_state FROM search_pages WHERE id=:id'),
                                     {'id': state['expired_page']}) == 'expired'
    finally:
        database_engine.dispose()
    state['checks'].append('restart recovery, persistent production session and startup expiry cleanup')
    (DATA / 'work/rehearsal-report.json').write_text(json.dumps(state['checks'], ensure_ascii=False, indent=2))
    print(json.dumps({'passed': True, 'checks': state['checks']}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['api', 'ocr', 'exercise', 'recovery'])
    options = parser.parse_args()
    globals()[options.mode]()
