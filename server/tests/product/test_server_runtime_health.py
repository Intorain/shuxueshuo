"""Required service health must fail the admin command before reopening admission."""

import json
import urllib.error
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from shuxueshuo_server.product.admin import cli, server_runtime


@pytest.fixture
def health_command(tmp_path, monkeypatch):
    settings = SimpleNamespace(mode='server', root=tmp_path)
    runtime = SimpleNamespace(settings=settings, broker_url='amqp://fixture', broker_host='rabbitmq',
                              values={'BROKER_PORT': '5672', 'OCR_PYTHON': '/unused'})
    replies = {
        'ocr': {'ok': True, 'ready': True},
        'api': {'status': 'ok', 'mode': 'product'},
        'admission': {'status': 'ok', 'accepting': True, 'draining': False},
    }

    def urlopen(url, *, timeout):
        assert timeout == 5
        endpoints = {'http://ocr:8080/health': 'ocr', 'http://api:8000/api/product/v1/health': 'api',
                     'http://api:8000/api/health': 'admission'}
        assert url in endpoints
        value = replies[endpoints[url]]
        if isinstance(value, Exception):
            raise value
        return BytesIO(value if isinstance(value, bytes) else json.dumps(value).encode())

    monkeypatch.setenv('PRODUCT_OCR_URL', 'http://ocr:8080')
    monkeypatch.setattr(server_runtime.urllib.request, 'urlopen', urlopen)
    monkeypatch.setattr(server_runtime.database, 'doctor', lambda _settings: {'ok': True})
    monkeypatch.setattr(server_runtime, 'Connection', MagicMock())
    monkeypatch.setattr(server_runtime.RuntimeConfig, 'load', lambda _settings: runtime)
    monkeypatch.setattr(cli.Settings, 'load', lambda *_args, **_kwargs: settings)
    return replies


def run_doctor():
    return cli.main(['--mode', 'server', 'services-doctor'])


def test_healthy_services_preserve_success_contract(health_command, capsys):
    assert run_doctor() == 0
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result['ok'] is True and result['api'] is True and result['ocr_sidecar'] is True
    assert result['api_health'] == health_command['api']
    assert result['ocr_sidecar_health'] == health_command['ocr']
    assert result['accepting'] is True and result['draining'] is False
    assert captured.err == ''


@pytest.mark.parametrize('service', ['ocr', 'api', 'admission'])
@pytest.mark.parametrize('failure', [
    urllib.error.URLError('private transport detail'),
    urllib.error.HTTPError('http://private/', 503, 'unavailable', {}, None),
    TimeoutError('private timeout detail'),
    b'not-json',
    [],
    None,
    {},
], ids=['connection', 'http-503', 'timeout', 'malformed-json', 'list', 'null', 'missing-fields'])
def test_required_service_failures_make_admin_exit_nonzero(health_command, capsys, service, failure):
    health_command[service] = failure
    assert run_doctor() == 2
    captured = capsys.readouterr()
    assert captured.out == ''
    assert captured.err == f'runtime.{"ocr" if service == "ocr" else "api"}_not_ready\n'


@pytest.mark.parametrize('service', ['ocr', 'api'])
@pytest.mark.parametrize('field', ['ok', 'ready'])
@pytest.mark.parametrize('value', [False, 1, 'true', None])
def test_http_200_does_not_override_negative_or_invalid_readiness(health_command, capsys, service, field, value):
    health_command[service][field] = value
    assert run_doctor() == 2
    assert capsys.readouterr().err == f'runtime.{service}_not_ready\n'


@pytest.mark.parametrize('body', [
    {'status': 'degraded', 'mode': 'product'},
    {'status': 'ok', 'mode': 'legacy'},
    {'ok': True, 'ready': True},
])
def test_api_health_must_match_product_service(health_command, capsys, body):
    health_command['api'] = body
    assert run_doctor() == 2
    assert capsys.readouterr().err == 'runtime.api_not_ready\n'


def test_missing_ocr_endpoint_does_not_fall_back_to_interpreter(health_command, monkeypatch, capsys):
    monkeypatch.delenv('PRODUCT_OCR_URL')
    assert run_doctor() == 2
    assert capsys.readouterr().err == 'runtime.ocr_not_ready\n'


@pytest.mark.parametrize('draining', [False, True])
def test_doctor_reports_admission_without_mutating_real_marker(health_command, tmp_path, monkeypatch, capsys, draining):
    marker = tmp_path / 'locks/services-draining'
    marker.parent.mkdir()
    if draining:
        marker.write_text('operator requested drain')
    health_command['admission'].update(accepting=not draining, draining=draining)
    monkeypatch.setattr(server_runtime.database, 'doctor', lambda _settings: {
        'ok': True, 'accepting': draining, 'draining': not draining,
    })
    assert run_doctor() == 0
    result = json.loads(capsys.readouterr().out)
    assert result['api'] is True and result['ok'] is True
    assert result['accepting'] is not draining and result['draining'] is draining
    assert marker.exists() is draining
    if draining:
        assert marker.read_text() == 'operator requested drain'


@pytest.mark.parametrize('body', [
    {'status': 'ok', 'accepting': True},
    {'status': 'ok', 'draining': True},
    {'status': 'ok', 'accepting': 'false', 'draining': True},
    {'status': 'ok', 'accepting': False, 'draining': 1},
    {'status': 'ok', 'accepting': True, 'draining': True},
    {'status': 'ok', 'accepting': False, 'draining': False},
])
def test_doctor_rejects_unknown_admission_state(health_command, capsys, body):
    health_command['admission'] = body
    assert run_doctor() == 2
    assert capsys.readouterr().err == 'runtime.api_not_ready\n'
