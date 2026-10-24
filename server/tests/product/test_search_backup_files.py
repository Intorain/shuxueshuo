import json
import os
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from shuxueshuo_server.product.admin.search_backup import (
    backup_lease,
    collect_search_files,
    prune_backups,
    restore_search_files,
    validate_search_files,
)
from shuxueshuo_server.product.errors import Conflict, IntegrityFailure, ProductError


NOW = datetime(2026, 10, 24, 12, tzinfo=UTC)


def saved_file(backup, key='pages/111111111111/page.png', *, expires=None, content=b'private'):
    path = backup / 'search' / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    owner_type, owner_id, *_rest = key.split('/')
    return {'storage_key': key, 'owner_type': owner_type, 'owner_id': owner_id,
            'expires_at': (expires or NOW + timedelta(hours=1)).isoformat(),
            'sha256': sha256(content).hexdigest(), 'size_bytes': len(content)}


def managed_backup(tmp_path, *, created=None, incomplete=False, name=None):
    directory = tmp_path / 'backups' / ((name or 'a' * 32) + ('.incomplete' if incomplete else ''))
    directory.mkdir(parents=True)
    manifest = {'schema_version': 'product-backup-state/v1' if incomplete else 'product-backup/v2',
                'created_at': (created or NOW).isoformat(), 'complete': True, 'search_files': []}
    marker = directory / ('backup-state.json' if incomplete else 'manifest.json')
    marker.write_text(json.dumps(manifest))
    with backup_lease(directory, create=True):
        pass
    return directory, manifest, marker


def test_restore_keeps_only_unexpired_content_and_original_deadline(tmp_path):
    backup = tmp_path / 'snapshot'
    active = saved_file(backup)
    expired = saved_file(backup, 'submissions/222222222222/result.json', expires=NOW)
    (backup / 'search' / expired['storage_key']).unlink()
    entries = [active, expired]
    assert validate_search_files(backup, entries, now=NOW) == [active]
    destination = tmp_path / 'restored'
    assert restore_search_files(backup, destination, entries, now=NOW) == 1
    assert (destination / active['storage_key']).read_bytes() == b'private'
    assert not (destination / expired['storage_key']).exists()
    assert active['expires_at'] == (NOW + timedelta(hours=1)).isoformat()


@pytest.mark.parametrize('mutation', ['corrupt', 'missing', 'extra_file', 'extra_directory', 'symlink_file', 'symlink_directory'])
def test_restore_rejects_incomplete_or_unregistered_content(tmp_path, mutation):
    backup = tmp_path / 'snapshot'
    entry = saved_file(backup)
    path = backup / 'search' / entry['storage_key']
    if mutation == 'corrupt':
        path.write_bytes(b'wrong')
    elif mutation == 'missing':
        path.unlink()
    elif mutation == 'extra_file':
        path.with_name('unexpected').write_text('private')
    elif mutation == 'extra_directory':
        path.with_name('unexpected').mkdir()
    elif mutation == 'symlink_file':
        original = tmp_path / 'original'
        path.replace(original)
        path.symlink_to(original)
    else:
        original = tmp_path / 'original'
        path.parent.replace(original)
        path.parent.symlink_to(original, target_is_directory=True)
    with pytest.raises(IntegrityFailure):
        validate_search_files(backup, [entry], now=NOW)


@pytest.mark.parametrize('change', [
    {'storage_key': '../outside'},
    {'storage_key': 'pages/111111111111/../../outside'},
    {'storage_key': '/pages/111111111111/page.png'},
    {'storage_key': 'pages/222222222222/page.png'},
    {'owner_type': 'locks'},
    {'owner_id': 'bad'},
    {'expires_at': '2026-10-24T12:00:00'},
    {'sha256': 'bad'},
    {'size_bytes': True},
])
def test_restore_rejects_invalid_manifest_fields(tmp_path, change):
    entry = saved_file(tmp_path)
    with pytest.raises(ProductError):
        validate_search_files(tmp_path, [{**entry, **change}], now=NOW)


def test_restore_rejects_duplicate_and_inconsistent_owner_deadlines(tmp_path):
    entry = saved_file(tmp_path)
    with pytest.raises(IntegrityFailure, match='invalid_search_key'):
        validate_search_files(tmp_path, [entry, entry], now=NOW)
    second = saved_file(tmp_path, 'pages/111111111111/source.png', expires=NOW + timedelta(hours=2))
    with pytest.raises(IntegrityFailure, match='inconsistent_search_expiry'):
        validate_search_files(tmp_path, [entry, second], now=NOW)


def test_restore_refuses_existing_target_before_copy(tmp_path):
    entry = saved_file(tmp_path / 'backup')
    target = tmp_path / 'target'
    target.mkdir()
    (target / 'untouched').write_text('keep')
    with pytest.raises(Conflict, match='target_search_not_empty'):
        restore_search_files(tmp_path / 'backup', target, [entry], now=NOW)
    assert list(target.iterdir()) == [target / 'untouched']


def test_expired_corrupt_content_is_not_restored(tmp_path):
    entry = saved_file(tmp_path, expires=NOW)
    (tmp_path / 'search' / entry['storage_key']).write_bytes(b'corrupt')
    assert validate_search_files(tmp_path, [entry], now=NOW) == []


def test_restore_selection_preserves_new_recovery_authority(tmp_path):
    backup, target = tmp_path / 'backup', tmp_path / 'target'
    remaining = saved_file(backup)
    deleted = saved_file(backup, 'submissions/222222222222/original.png')
    for name in ('pages', 'submissions', 'locks', 'recovery'):
        (target / name).mkdir(parents=True)
    journal = target / 'recovery/deletions.jsonl'
    journal.write_text('new-authority')
    assert restore_search_files(backup, target, [remaining, deleted],
                                selected_keys={remaining['storage_key']}, now=NOW) == 1
    assert journal.read_text() == 'new-authority'
    assert (target / remaining['storage_key']).is_file()
    assert not (target / deleted['storage_key']).exists()


def test_restore_selection_still_verifies_unselected_source_files(tmp_path):
    entry = saved_file(tmp_path / 'backup')
    (tmp_path / 'backup/search' / entry['storage_key']).write_text('corrupt')
    with pytest.raises(IntegrityFailure, match='search_file_hash'):
        restore_search_files(tmp_path / 'backup', tmp_path / 'target', [entry], selected_keys=set(), now=NOW)


def test_restore_rejects_keys_outside_source_manifest(tmp_path):
    entry = saved_file(tmp_path / 'backup')
    with pytest.raises(IntegrityFailure, match='invalid_search_selection'):
        restore_search_files(tmp_path / 'backup', tmp_path / 'target', [entry], selected_keys={'unexpected'}, now=NOW)


@pytest.mark.parametrize('category', ['pages', 'submissions', 'locks'])
def test_restore_refuses_nonempty_existing_private_directories(tmp_path, category):
    entry = saved_file(tmp_path / 'backup')
    target = tmp_path / 'target'
    (target / category).mkdir(parents=True)
    (target / category / 'existing').write_text('keep')
    with pytest.raises(Conflict, match='target_search_not_empty'):
        restore_search_files(tmp_path / 'backup', target, [entry], now=NOW)


def test_source_validation_does_not_write_to_readonly_backup(tmp_path, monkeypatch):
    entry = saved_file(tmp_path)

    def forbidden(*_args, **_kwargs):
        pytest.fail('read-only verification attempted a write')

    monkeypatch.setattr(os, 'mkdir', forbidden)
    monkeypatch.setattr(Path, 'mkdir', forbidden)
    assert validate_search_files(tmp_path, [entry], now=NOW) == [entry]
    assert not (tmp_path / 'search/.tmp').exists()


def test_pruning_uses_original_file_deadline_and_preserves_manifest(tmp_path):
    directory, manifest, marker = managed_backup(tmp_path)
    expired = saved_file(directory, expires=NOW)
    active = saved_file(directory, 'submissions/222222222222/original.png')
    manifest['search_files'] = [expired, active]
    marker.write_text(json.dumps(manifest))
    before = marker.read_bytes()
    result = prune_backups(SimpleNamespace(root=tmp_path), now=NOW)
    assert result == {'removed_backups': 0, 'pruned_search_files': 1, 'failures': []}
    assert marker.read_bytes() == before
    assert validate_search_files(directory, manifest['search_files'], now=NOW) == [active]
    assert prune_backups(SimpleNamespace(root=tmp_path), now=NOW)['pruned_search_files'] == 0


@pytest.mark.parametrize('incomplete,age,before', [
    (False, timedelta(days=30), timedelta(microseconds=1)),
    (True, timedelta(hours=1), timedelta(microseconds=1)),
])
def test_managed_bundle_retention_boundaries(tmp_path, incomplete, age, before):
    directory, _manifest, _marker = managed_backup(tmp_path, created=NOW - age, incomplete=incomplete)
    settings = SimpleNamespace(root=tmp_path)
    assert prune_backups(settings, now=NOW - before)['removed_backups'] == 0
    assert directory.exists()
    assert prune_backups(settings, now=NOW)['removed_backups'] == 1
    assert not directory.exists()


def test_pruning_never_touches_unmanaged_or_old_backup_directories(tmp_path):
    directory, manifest, marker = managed_backup(tmp_path, created=NOW - timedelta(days=40))
    manifest['schema_version'] = 'product-backup/v1'
    marker.write_text(json.dumps(manifest))
    unknown = tmp_path / 'backups/manual-copy'
    unknown.mkdir()
    orphan = tmp_path / 'backups' / ('b' * 32 + '.incomplete')
    orphan.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'private').write_text('keep')
    (tmp_path / 'backups' / ('c' * 32)).symlink_to(outside, target_is_directory=True)
    result = prune_backups(SimpleNamespace(root=tmp_path), now=NOW)
    assert result == {'removed_backups': 0, 'pruned_search_files': 0, 'failures': []}
    assert directory.exists() and unknown.exists() and orphan.exists()
    assert (outside / 'private').read_text() == 'keep'


@pytest.mark.parametrize('shared', [False, True])
def test_pruning_does_not_race_backup_or_restore_lease(tmp_path, shared):
    directory, _manifest, _marker = managed_backup(tmp_path, created=NOW - timedelta(days=40))
    settings = SimpleNamespace(root=tmp_path)
    with backup_lease(directory, shared=shared):
        assert prune_backups(settings, now=NOW)['removed_backups'] == 0
        assert directory.exists()
    assert prune_backups(settings, now=NOW)['removed_backups'] == 1


def test_pruning_failure_retries_without_destroying_evidence(tmp_path, monkeypatch):
    directory, manifest, marker = managed_backup(tmp_path)
    entry = saved_file(directory, expires=NOW)
    manifest['search_files'] = [entry]
    marker.write_text(json.dumps(manifest))
    before = marker.read_bytes()
    original = Path.unlink

    def fail_private(path, *args, **kwargs):
        if path.name == 'page.png':
            raise PermissionError('fixture')
        return original(path, *args, **kwargs)

    with monkeypatch.context() as scoped:
        scoped.setattr(Path, 'unlink', fail_private)
        result = prune_backups(SimpleNamespace(root=tmp_path), now=NOW)
    assert len(result['failures']) == 1
    assert marker.read_bytes() == before
    assert prune_backups(SimpleNamespace(root=tmp_path), now=NOW)['pruned_search_files'] == 1


class InventoryConnection:
    def __init__(self, rows, pending=(), existing=True):
        self.rows, self.pending, self.existing = rows, pending, existing

    def exec_driver_sql(self, _query):
        return SimpleNamespace(scalars=lambda: ['search_pages', 'search_submissions'] if self.existing else [])

    def scalars(self, _query):
        return [list(self.pending)]

    def execute(self, query):
        table = query.get_final_froms()[0].name
        rows = self.rows.get(table, [])
        state = 'image_state' if table == 'search_pages' else 'artifact_state'
        instant = next(value for value in query.compile().params.values() if isinstance(value, datetime))
        active = [row for row in rows if row[state] == 'active' and row['expires_at'] > instant]
        return SimpleNamespace(mappings=lambda: active)


def inventory_row(source, category, identifier, *, state='active', expires=None):
    key = category + '/' + identifier
    root = source / key
    root.mkdir(parents=True)
    row = {'id': identifier, 'storage_key': key, 'expires_at': expires or NOW + timedelta(hours=1),
           'image_state' if category == 'pages' else 'artifact_state': state}
    required = {'page.png': 'sha256'} if category == 'pages' else {'question.png': 'crop_sha256', 'original.png': 'original_sha256'}
    for name, column in required.items():
        (root / name).write_bytes(name.encode())
        row[column] = sha256(name.encode()).hexdigest()
    return row


def test_collect_copies_only_registered_active_unexpired_nonpending_owners(tmp_path):
    source, backup = tmp_path / 'source', tmp_path / 'backup'
    page = inventory_row(source, 'pages', '1' * 12)
    submission = inventory_row(source, 'submissions', '2' * 12)
    expired = inventory_row(source, 'pages', '3' * 12, expires=NOW)
    inactive = inventory_row(source, 'submissions', '4' * 12, state='expired')
    pending = inventory_row(source, 'submissions', '5' * 12)
    inventory_row(source, 'pages', '6' * 12)
    (source / 'locks').mkdir()
    (source / 'locks/private.lock').write_text('ignore')
    nested = source / submission['storage_key'] / 'stage-two-1/result.json'
    nested.parent.mkdir()
    nested.write_text('{"private":true}')
    (nested.parent / '.stage-three.lock').write_text('transient flock')
    (source / submission['storage_key'] / '.lesson.lock').touch()
    connection = InventoryConnection({'search_pages': [page, expired], 'search_submissions': [submission, inactive, pending]},
                                     [{'key': pending['storage_key']}])
    entries = collect_search_files(connection, source, backup, now=NOW)
    assert len(entries) == 4
    assert {entry['owner_id'] for entry in entries} == {'1' * 12, '2' * 12}
    assert validate_search_files(backup, entries, now=NOW) == entries
    assert not (backup / 'search/locks').exists()
    assert not any(entry['storage_key'].endswith('.lock') for entry in entries)


@pytest.mark.parametrize('mutation', ['symlink', 'missing', 'wrong_hash', 'wrong_owner'])
def test_collect_refuses_unsafe_or_incomplete_registered_owner(tmp_path, mutation):
    source = tmp_path / 'source'
    row = inventory_row(source, 'pages', '1' * 12)
    path = source / row['storage_key'] / 'page.png'
    if mutation == 'missing':
        path.unlink()
    elif mutation == 'wrong_hash':
        path.write_text('wrong')
    elif mutation == 'wrong_owner':
        row['storage_key'] = 'pages/' + '2' * 12
    else:
        original = tmp_path / 'original'
        path.replace(original)
        path.symlink_to(original)
    with pytest.raises(ProductError):
        collect_search_files(InventoryConnection({'search_pages': [row]}), source, tmp_path / 'backup', now=NOW)


def test_collect_legacy_schema_without_search_tables_is_empty(tmp_path):
    assert collect_search_files(InventoryConnection({}, existing=False), tmp_path / 'source', tmp_path / 'backup', now=NOW) == []
