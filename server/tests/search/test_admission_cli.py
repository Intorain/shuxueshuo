"""Operator controls remain usable independently of API limits and restore state."""

import json
import sys
from types import SimpleNamespace

import pytest

from shuxueshuo_server.product.errors import Conflict
from shuxueshuo_server.search import maintenance
from tests.search.test_repository import repository as repository_fixture
from tests.search.test_repository import student


@pytest.fixture
def repository(tmp_path):
    yield from repository_fixture.__wrapped__(tmp_path)


@pytest.fixture
def command(repository, tmp_path, monkeypatch, capsys):
    settings = SimpleNamespace(root=tmp_path / 'instance', url=lambda: 'isolated-database')
    (settings.root / 'locks').mkdir(parents=True)
    monkeypatch.setattr(maintenance.Settings, 'load', lambda *_args: settings)
    monkeypatch.setattr(maintenance, 'engine', lambda _url: repository.db)

    def run(name):
        monkeypatch.setattr(sys, 'argv', ['maintenance', name])
        maintenance.main()
        return json.loads(capsys.readouterr().out)

    return run, settings


def test_operator_stop_is_hot_and_does_not_depend_on_valid_api_configuration(repository, command, monkeypatch):
    run, _settings = command
    assert run('generation-status') == {'generation_enabled': False, 'cancelled': 0}
    assert run('generation-enable')['generation_enabled'] is True
    ticket = repository.admission.reserve(student(repository), 'generation', 'fixture')
    monkeypatch.setenv('SEARCH_GENERATION_WORKERS', 'broken-config')
    assert run('generation-stop') == {'generation_enabled': False, 'cancelled': 1}
    assert repository.admission.get_ticket(ticket.id).state == 'cancelled'
    assert run('generation-status')['generation_enabled'] is False


def test_incomplete_restore_can_be_stopped_but_never_enabled(repository, command):
    run, settings = command
    (settings.root / 'locks/restore-incomplete').touch()
    with pytest.raises(Conflict, match='restore.incomplete'):
        run('generation-enable')
    assert run('generation-stop')['generation_enabled'] is False
    assert not repository.admission.generation_enabled()
