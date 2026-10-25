"""Live expiry stays minute-based while backup scans have an hourly budget."""

import sys
import traceback
from types import SimpleNamespace

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from shuxueshuo_server.product.admin import cli, search_backup
from shuxueshuo_server.product.errors import IntegrityFailure
from shuxueshuo_server.search import application, maintenance


@pytest.fixture
def scheduled_cleanup(tmp_path, monkeypatch):
    now = [0.0]
    live_calls = []
    backup_calls = []
    settings = SimpleNamespace(root=tmp_path)
    repository = SimpleNamespace(cleanup=lambda: live_calls.append(now[0]) or {})
    monkeypatch.setattr(search_backup, 'prune_backups',
                        lambda selected: backup_calls.append((now[0], selected)) or {'failures': []})
    scheduled = application._SearchMaintenance(repository, settings, clock=lambda: now[0])
    return SimpleNamespace(now=now, live_calls=live_calls, backup_calls=backup_calls,
                           settings=settings, repository=repository, scheduled=scheduled)


def test_live_cleanup_runs_each_minute_but_backups_only_startup_and_hourly(scheduled_cleanup):
    fixture = scheduled_cleanup
    for elapsed in range(0, 3600, 60):
        fixture.now[0] = elapsed
        fixture.scheduled.cleanup()
    assert len(fixture.live_calls) == 60
    assert fixture.backup_calls == [(0, fixture.settings)]
    fixture.now[0] = 3599.999
    fixture.scheduled.cleanup()
    assert len(fixture.backup_calls) == 1
    fixture.now[0] = 3600
    fixture.scheduled.cleanup()
    assert fixture.backup_calls == [(0, fixture.settings), (3600, fixture.settings)]
    assert application.CLEANUP_INTERVAL == 60
    assert application.BACKUP_CLEANUP_INTERVAL == 3600


@pytest.mark.parametrize('raises', [False, True])
def test_backup_failure_is_logged_and_retried_hourly_not_each_minute(
        scheduled_cleanup, monkeypatch, caplog, raises):
    fixture = scheduled_cleanup
    calls = []

    def fail(_settings):
        calls.append(fixture.now[0])
        if raises:
            raise OSError('offline backup scan failure')
        return {'failures': ['unregistered-file']}

    monkeypatch.setattr(search_backup, 'prune_backups', fail)
    fixture.scheduled.cleanup()
    for elapsed in range(60, 3600, 60):
        fixture.now[0] = elapsed
        fixture.scheduled.cleanup()
    assert calls == [0]
    assert len(caplog.records) == 1
    fixture.now[0] = 3600
    fixture.scheduled.cleanup()
    assert calls == [0, 3600]
    assert len(fixture.live_calls) == 61
    assert len(caplog.records) == 2


def test_live_cleanup_failure_cannot_skip_due_backup_cleanup(scheduled_cleanup):
    fixture = scheduled_cleanup

    def fail():
        raise OSError('offline live cleanup failure')

    fixture.repository.cleanup = fail
    for elapsed in (0, 60, 3600):
        fixture.now[0] = elapsed
        with pytest.raises(OSError, match='offline live cleanup failure'):
            fixture.scheduled.cleanup()
    assert fixture.backup_calls == [(0, fixture.settings), (3600, fixture.settings)]


@pytest.mark.parametrize('backup_fails', [False, True])
def test_lifespan_runs_backup_once_and_shares_schedule_with_background(
        tmp_path, monkeypatch, caplog, backup_fails):
    calls = []
    now = [0.0]
    settings = SimpleNamespace(root=tmp_path)
    repository = SimpleNamespace(recover=lambda: calls.append('recover'),
                                 admission=SimpleNamespace(recover=lambda: calls.append('admission-recover')),
                                 cleanup=lambda: calls.append('live'))

    def backup(_settings):
        calls.append('backup')
        if backup_fails:
            raise OSError('offline backup startup failure')
        return {'failures': []}

    async def background(scheduled, stopped):
        now[0] = 60
        scheduled.cleanup()
        await stopped.wait()

    monkeypatch.setattr(application, 'SearchRepository', lambda *_args: repository)
    monkeypatch.setattr(application, 'create_search_router', lambda *_args: APIRouter())
    monkeypatch.setattr(application, 'monotonic', lambda: now[0])
    monkeypatch.setattr(application, 'maintain_search', background)
    monkeypatch.setattr(search_backup, 'prune_backups', backup)
    app = FastAPI()
    app.state.product = SimpleNamespace(db=object(), settings=settings)
    application.install_search(app)
    with TestClient(app):
        assert app.state.search_accepting is True
    assert calls == ['admission-recover', 'recover', 'live', 'backup', 'live']
    assert app.state.search_accepting is False
    assert len(caplog.records) == int(backup_fails)


def test_explicit_cleanup_and_backup_prune_are_not_throttled(
        scheduled_cleanup, monkeypatch, capsys):
    fixture = scheduled_cleanup
    fixture.scheduled.cleanup()
    fixture.settings.url = lambda: 'offline-database'
    disposed = []
    monkeypatch.setattr(maintenance.Settings, 'load', lambda *_args: fixture.settings)
    monkeypatch.setattr(maintenance, 'engine',
                        lambda _url: SimpleNamespace(dispose=lambda: disposed.append(True)))
    monkeypatch.setattr(maintenance, 'SearchRepository', lambda *_args: fixture.repository)
    monkeypatch.setattr(sys, 'argv', ['maintenance', 'cleanup'])
    for _attempt in range(2):
        maintenance.main()
        cli.execute(fixture.settings, SimpleNamespace(command='backup-prune'))
    assert len(fixture.backup_calls) == 5
    assert len(fixture.live_calls) == 3
    assert len(disposed) == 2
    assert capsys.readouterr().out.count('"backups"') == 2


@pytest.mark.parametrize('live_fails', [False, True])
@pytest.mark.parametrize('backup_fails', [False, True])
def test_explicit_cleanup_preserves_primary_error_and_reports_backup_error(
        tmp_path, caplog, live_fails, backup_fails):
    settings = SimpleNamespace(root=tmp_path)
    if backup_fails:
        target = tmp_path / 'backup-target'
        target.mkdir()
        (tmp_path / 'backups').symlink_to(target, target_is_directory=True)
    primary_error = OSError('offline live cleanup failure')

    def live_cleanup():
        if live_fails:
            raise primary_error
        return {'expired_pages': 2}

    repository = SimpleNamespace(cleanup=live_cleanup)
    if live_fails:
        with pytest.raises(OSError, match='offline live cleanup failure') as raised:
            application.cleanup_search(repository, settings)
        assert raised.value is primary_error
        assert traceback.extract_tb(raised.tb)[-1].name == 'live_cleanup'
        assert len(caplog.records) == int(backup_fails)
        if backup_fails:
            record = caplog.records[0]
            assert record.message == 'Search backup cleanup also failed after live cleanup failed'
            assert isinstance(record.exc_info[1], IntegrityFailure)
            assert str(record.exc_info[1]) == 'backup.search_symlink'
    elif backup_fails:
        with pytest.raises(IntegrityFailure, match='backup.search_symlink'):
            application.cleanup_search(repository, settings)
        assert not caplog.records
    else:
        assert application.cleanup_search(repository, settings) == {
            'expired_pages': 2,
            'backups': {'removed_backups': 0, 'pruned_search_files': 0, 'failures': []},
        }
        assert not caplog.records


@pytest.mark.parametrize('live_fails', [False, True])
def test_explicit_cleanup_without_settings_never_runs_backup_cleanup(monkeypatch, live_fails):
    def unexpected_backup(_settings):
        pytest.fail('cleanup without settings must not scan backups')

    def live_cleanup():
        if live_fails:
            raise OSError('offline live cleanup failure')
        return {'expired_pages': 2}

    monkeypatch.setattr(search_backup, 'prune_backups', unexpected_backup)
    repository = SimpleNamespace(cleanup=live_cleanup)
    if live_fails:
        with pytest.raises(OSError, match='offline live cleanup failure'):
            application.cleanup_search(repository)
    else:
        assert application.cleanup_search(repository) == {'expired_pages': 2}


@pytest.mark.parametrize('live_fails', [False, True])
def test_cleanup_command_does_not_report_success_after_cleanup_error(
        tmp_path, monkeypatch, capsys, live_fails):
    target = tmp_path / 'backup-target'
    target.mkdir()
    (tmp_path / 'backups').symlink_to(target, target_is_directory=True)
    settings = SimpleNamespace(root=tmp_path, url=lambda: 'offline-database')
    disposed = []

    def live_cleanup():
        if live_fails:
            raise OSError('offline live cleanup failure')
        return {}

    monkeypatch.setattr(maintenance.Settings, 'load', lambda *_args: settings)
    monkeypatch.setattr(maintenance, 'engine',
                        lambda _url: SimpleNamespace(dispose=lambda: disposed.append(True)))
    monkeypatch.setattr(maintenance, 'SearchRepository',
                        lambda *_args: SimpleNamespace(cleanup=live_cleanup))
    monkeypatch.setattr(sys, 'argv', ['maintenance', 'cleanup'])
    error = OSError if live_fails else IntegrityFailure
    message = 'offline live cleanup failure' if live_fails else 'backup.search_symlink'
    with pytest.raises(error, match=message):
        maintenance.main()
    assert disposed == [True]
    assert capsys.readouterr().out == ''
