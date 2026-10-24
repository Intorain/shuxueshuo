"""Bounded private search snapshots, restored only within original lifetimes."""

import json
import fcntl
import os
import re
import shutil
import stat
from datetime import UTC, datetime, timedelta
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import select

from .. import models
from ..errors import Conflict, IntegrityFailure, ProductError
from ..storage import LocalArtifactStorage, parts


def _now(value=None):
    value = value or datetime.now(UTC)
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise IntegrityFailure('backup.invalid_time')
    return value.astimezone(UTC)


def _timestamp(value):
    try:
        return _now(datetime.fromisoformat(value))
    except (TypeError, ValueError) as exc:
        raise IntegrityFailure('backup.invalid_time') from exc


def _path(root, key):
    names = parts(key)
    root = Path(root).absolute()
    for parent in (root, *root.parents):
        if parent.is_symlink():
            raise IntegrityFailure('backup.search_symlink')
    current = root
    for name in names:
        current = current / name
        if current.is_symlink():
            raise IntegrityFailure('backup.search_symlink')
    return current


def _tree(root):
    root = Path(root).absolute()
    _path(root, 'probe')
    if not root.exists():
        return set(), set()
    if not root.is_dir():
        raise IntegrityFailure('backup.search_not_directory')
    files, directories = set(), set()
    for directory, child_directories, child_files in os.walk(root, followlinks=False):
        for name in child_directories + child_files:
            path = Path(directory) / name
            key = path.relative_to(root).as_posix()
            mode = path.lstat().st_mode
            if key == '.tmp' and stat.S_ISDIR(mode) and not any(path.iterdir()):
                directories.add(key)
                continue
            parts(key)
            if stat.S_ISDIR(mode):
                directories.add(key)
            elif stat.S_ISREG(mode):
                files.add(key)
            else:
                raise IntegrityFailure('backup.search_not_regular')
    return files, directories


@contextmanager
def backup_lease(directory, *, shared=False, blocking=True, create=False):
    path = _path(directory, '.lease')
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    if create:
        flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise IntegrityFailure('backup.invalid_lease')
        operation = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
        fcntl.flock(descriptor, operation | (0 if blocking else fcntl.LOCK_NB))
        if not path.exists() or path.stat().st_ino != os.fstat(descriptor).st_ino:
            raise IntegrityFailure('backup.lease_replaced')
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _entries(entries):
    if not isinstance(entries, list):
        raise IntegrityFailure('backup.invalid_search_manifest')
    keys, owners = set(), {}
    checked = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise IntegrityFailure('backup.invalid_search_manifest')
        owner_type, owner_id = entry.get('owner_type'), entry.get('owner_id')
        if owner_type not in ('pages', 'submissions') or not isinstance(owner_id, str) or not re.fullmatch('[0-9a-f]{12}', owner_id):
            raise IntegrityFailure('backup.invalid_search_owner')
        key = entry.get('storage_key')
        names = parts(key)
        if len(names) < 3 or names[:2] != [owner_type, owner_id] or key in keys:
            raise IntegrityFailure('backup.invalid_search_key')
        digest, size = entry.get('sha256'), entry.get('size_bytes')
        if (not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest)
                or type(size) is not int or size < 0):
            raise IntegrityFailure('backup.invalid_search_hash')
        expires = _timestamp(entry.get('expires_at'))
        owner = '/'.join(names[:2])
        if owner in owners and owners[owner] != expires:
            raise IntegrityFailure('backup.inconsistent_search_expiry')
        owners[owner] = expires
        keys.add(key)
        checked.append((entry, expires))
    return checked


def _inventory_matches(root, checked):
    files, directories = _tree(root)
    expected = {entry['storage_key'] for entry, _expires in checked}
    allowed_directories = set()
    for key in expected:
        names = key.split('/')
        allowed_directories.update('/'.join(names[:count]) for count in range(1, len(names)))
    if files - expected or directories - allowed_directories - {'.tmp'}:
        raise IntegrityFailure('restore.unregistered_search_files')


def collect_search_files(connection, source_root, backup_root, *, now=None):
    """The caller holds the application write fence throughout dump and copy."""
    now = _now(now)
    existing = set(connection.exec_driver_sql("SELECT tablename FROM pg_tables WHERE schemaname='public'").scalars())
    if not {'search_pages', 'search_submissions'} <= existing:
        return []
    pending = set()
    for entries in connection.scalars(select(models.search_pages.c.pending_cleanup_keys)):
        pending.update(entry['key'] for entry in entries)
    source = LocalArtifactStorage(source_root)
    destination = Path(backup_root) / 'search'
    if destination.exists() and any(destination.iterdir()):
        raise Conflict('backup.search_target_not_empty')
    _path(destination, 'probe')
    target = LocalArtifactStorage(destination)
    result = []
    for owner_type, table, state, required in (
        ('pages', models.search_pages, 'image_state', {'page.png': 'sha256'}),
        ('submissions', models.search_submissions, 'artifact_state', {'question.png': 'crop_sha256', 'original.png': 'original_sha256'}),
    ):
        rows = connection.execute(select(table).where(table.c[state] == 'active', table.c.expires_at > now)
                                  .order_by(table.c.id)).mappings()
        for row in rows:
            key = row['storage_key']
            if key != owner_type + '/' + row['id'] or not re.fullmatch('[0-9a-f]{12}', row['id']):
                raise IntegrityFailure('backup.invalid_search_owner')
            if key in pending:
                continue
            directory = _path(source_root, key)
            files, _directories = _tree(directory)
            if not set(required) <= files:
                raise IntegrityFailure('backup.search_required_file_missing')
            for relative in sorted(files):
                if relative.endswith('.lock'):
                    continue
                storage_key = key + '/' + relative
                with source.open(storage_key) as stream:
                    saved = target.put_immutable(storage_key, stream, row[required[relative]] if relative in required else None)
                result.append({'storage_key': saved.storage_key, 'sha256': saved.sha256,
                               'size_bytes': saved.size_bytes, 'owner_type': owner_type, 'owner_id': row['id'],
                               'expires_at': _now(row['expires_at']).isoformat()})
    return result


def validate_search_files(backup_root, entries, *, now=None):
    now = _now(now)
    checked = _entries(entries)
    root = Path(backup_root) / 'search'
    _inventory_matches(root, checked)
    storage = LocalArtifactStorage(root)
    active = []
    for entry, expires in checked:
        if expires <= now:
            continue
        if not storage.verify(entry['storage_key'], entry['sha256'], entry['size_bytes']).ok:
            raise IntegrityFailure('restore.search_file_hash')
        active.append(entry)
    return active


def restore_search_files(backup_root, destination_root, entries, *, selected_keys=None, now=None):
    active = validate_search_files(backup_root, entries, now=now)
    if selected_keys is not None:
        if not isinstance(selected_keys, (set, frozenset)) or not selected_keys <= {entry['storage_key'] for entry in entries}:
            raise IntegrityFailure('restore.invalid_search_selection')
        active = [entry for entry in active if entry['storage_key'] in selected_keys]
    destination = Path(destination_root)
    _path(destination, 'probe')
    if destination.exists():
        for child in destination.iterdir():
            if child.is_symlink() or not child.is_dir() or child.name not in {'pages', 'submissions', 'locks', 'recovery'}:
                raise Conflict('restore.target_search_not_empty')
            if child.name == 'recovery':
                _tree(child)
            elif any(child.iterdir()):
                raise Conflict('restore.target_search_not_empty')
    source = LocalArtifactStorage(Path(backup_root) / 'search')
    target = LocalArtifactStorage(destination)
    for entry in active:
        with source.open(entry['storage_key']) as stream:
            saved = target.put_immutable(entry['storage_key'], stream, entry['sha256'])
        if saved.size_bytes != entry['size_bytes']:
            raise IntegrityFailure('restore.search_file_size')
    return len(active)


def _json(path):
    storage = LocalArtifactStorage(path.parent)
    with storage.open(path.name) as stream:
        return json.load(stream)


def _prune_directory(directory, now):
    incomplete = directory.name.endswith('.incomplete')
    marker = directory / ('backup-state.json' if incomplete else 'manifest.json')
    if not marker.exists():
        return 0, 0
    manifest = _json(marker)
    expected = 'product-backup-state/v1' if incomplete else 'product-backup/v2'
    if not isinstance(manifest, dict) or manifest.get('schema_version') != expected:
        return 0, 0
    created = _timestamp(manifest.get('created_at'))
    retention = timedelta(hours=1) if incomplete else timedelta(days=30)
    if created + retention <= now:
        shutil.rmtree(directory)
        return 1, 0
    if incomplete:
        return 0, 0
    if manifest.get('complete') is not True:
        raise IntegrityFailure('backup.incomplete_manifest')
    checked = _entries(manifest.get('search_files'))
    search_root = directory / 'search'
    _inventory_matches(search_root, checked)
    removed = 0
    for entry, expires in checked:
        if expires > now:
            continue
        path = _path(search_root, entry['storage_key'])
        if not path.exists():
            continue
        path.unlink()
        removed += 1
        for parent in path.parents:
            if parent == search_root:
                break
            try:
                parent.rmdir()
            except OSError:
                break
    return 0, removed


def prune_backups(settings, *, now=None):
    """Only recognized snapshots under this instance's backups directory are pruned."""
    now = _now(now)
    root = settings.root / 'backups'
    _path(root, 'probe')
    result = {'removed_backups': 0, 'pruned_search_files': 0, 'failures': []}
    if not root.exists():
        return result
    for directory in sorted(root.iterdir()):
        if directory.is_symlink() or not directory.is_dir() or not re.fullmatch('[0-9a-f]{32}(?:\\.incomplete)?', directory.name):
            continue
        try:
            if not (directory / '.lease').exists():
                continue
            with backup_lease(directory, blocking=False):
                removed_backups, removed_files = _prune_directory(directory, now)
                result['removed_backups'] += removed_backups
                result['pruned_search_files'] += removed_files
        except BlockingIOError:
            continue
        except FileNotFoundError:
            continue
        except (OSError, ProductError, ValueError, KeyError) as exc:
            result['failures'].append({'backup': directory.name, 'error': str(exc) if isinstance(exc, ProductError) else type(exc).__name__})
    return result
