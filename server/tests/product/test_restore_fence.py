from types import SimpleNamespace

import pytest

from shuxueshuo_server.product.admin import cli, runtime
from shuxueshuo_server.product.admin.backup import require_restore_complete
from shuxueshuo_server.product.application import Application
from shuxueshuo_server.product.errors import Conflict
from shuxueshuo_server.search.application import cleanup_search


def test_restore_marker_blocks_resume_application_and_process_spawn(tmp_path):
    settings = SimpleNamespace(root=tmp_path, mode='local')
    marker = tmp_path / 'locks/restore-incomplete'
    marker.parent.mkdir()
    marker.write_text('{"state":"restoring"}')
    for operation in (
        lambda: require_restore_complete(settings),
        lambda: cli.execute(settings, SimpleNamespace(command='resume')),
        lambda: Application(settings),
        lambda: runtime.spawn_named(SimpleNamespace(settings=settings), 'fixture', ('api',)),
    ):
        with pytest.raises(Conflict, match='restore.incomplete_target'):
            operation()


def test_backup_retention_still_runs_when_live_cleanup_fails(tmp_path, monkeypatch):
    from shuxueshuo_server.product.admin import search_backup

    calls = []

    def fail():
        raise OSError('offline cleanup failure')

    monkeypatch.setattr(search_backup, 'prune_backups', lambda settings: calls.append(settings) or {'failures': []})
    settings = SimpleNamespace(root=tmp_path)
    with pytest.raises(OSError, match='offline cleanup failure'):
        cleanup_search(SimpleNamespace(cleanup=fail), settings)
    assert calls == [settings]


def test_backup_prune_command_does_not_need_database_or_journal(tmp_path):
    result = cli.execute(SimpleNamespace(root=tmp_path), SimpleNamespace(command='backup-prune'))
    assert result == {'removed_backups': 0, 'pruned_search_files': 0, 'failures': []}
