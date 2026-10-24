"""Portable logical backups. Original instance and artifact keys remain untouched."""
import json
import os
import subprocess
from contextlib import ExitStack, contextmanager, nullcontext
from dataclasses import asdict
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import psycopg
from sqlalchemy import func, select

from .. import models as m
from ..db import engine, transaction
from ..errors import Conflict, IntegrityFailure
from ..storage import LocalArtifactStorage, parts
from .database import doctor, dsn, grant
from .search_backup import backup_lease, collect_search_files, restore_search_files, validate_search_files


def require_restore_complete(settings):
    if (settings.root / 'locks/restore-incomplete').exists():
        raise Conflict('restore.incomplete_target_requires_new_restore')


def _file_hash(path):
    digest = sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path, value):
    with path.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    path.chmod(0o600)


def _sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def stopped_writes(settings, *, keep_on_failure=False):
    """P1 owns one app role. Fence new logins; reject live app sessions, never kill them."""
    with psycopg.connect(dsn(settings.url('bootstrap')), autocommit=True) as c:
        c.execute('SELECT pg_advisory_lock(1783392101)')
        enabled = c.execute("SELECT rolcanlogin FROM pg_roles WHERE rolname='product_app'").fetchone()[0]
        if not enabled:
            raise Conflict('backup.app_already_in_maintenance')
        c.execute('ALTER ROLE product_app NOLOGIN')
        succeeded = False
        try:
            if c.execute("SELECT count(*) FROM pg_stat_activity WHERE usename='product_app'").fetchone()[0]:
                raise Conflict('backup.stop_application_connections_first')
            yield
            succeeded = True
        finally:
            if succeeded or not keep_on_failure:
                c.execute('ALTER ROLE product_app LOGIN')
            c.execute('SELECT pg_advisory_unlock(1783392101)')


def pg_tool(settings, tool, *args):
    from sqlalchemy.engine import make_url
    url = make_url(settings.url('migration'))
    env = {**os.environ, 'PGHOST': url.host, 'PGPORT': str(url.port), 'PGUSER': url.username,
           'PGPASSWORD': url.password, 'PGDATABASE': url.database}
    subprocess.run([str(settings.pg_bin / tool), *map(str, args)], env=env, check=True, capture_output=True)


def table_counts(c):
    # deploy backs up before migrating, so newer models may not have tables yet.
    existing = set(c.exec_driver_sql("SELECT tablename FROM pg_tables WHERE schemaname='public'").scalars())
    return {name: c.scalar(select(func.count()).select_from(t))
            for name, t in m.metadata.tables.items() if name in existing}


def backup(settings, *, fenced=False, now=None):
    require_restore_complete(settings)
    now = now or datetime.now(UTC)
    identity = uuid4().hex
    temp = settings.root / 'backups' / (identity + '.incomplete')
    temp.mkdir(mode=0o700)
    _write_json(temp / 'backup-state.json', {'schema_version': 'product-backup-state/v1', 'created_at': now.isoformat()})
    storage = LocalArtifactStorage(settings.artifact_root)
    target = LocalArtifactStorage(temp / 'artifacts')
    with backup_lease(temp, create=True), nullcontext() if fenced else stopped_writes(settings):
        db = engine(settings.url('migration'))
        try:
            recovery_cursor = None
            with db.connect() as connection:
                has_recovery = connection.exec_driver_sql("SELECT to_regclass('search_recovery_state')").scalar() is not None
            if has_recovery:
                from ...search.repository import SearchRepository
                repository = SearchRepository(db, settings.root / 'work/search/private-v1', clock=lambda: now)
                repository.cleanup()
                recovery_cursor = repository.recovery.snapshot().cursor
            with transaction(db) as c:
                rows = c.execute(select(m.artifacts)).mappings().all()
                counts = table_counts(c)
                revision = c.exec_driver_sql('SELECT version_num FROM alembic_version').scalar_one()
                search_files = collect_search_files(c, settings.root / 'work/search/private-v1', temp, now=now)
            pg_tool(settings, 'pg_dump', '--format=custom', '--no-owner', '--no-acl', '--file', temp / 'database.dump')
            (temp / 'database.dump').chmod(0o600)
            artifacts = []
            for row in rows:
                with storage.open(row['storage_key']) as stream:
                    saved = target.put_immutable(row['storage_key'], stream, row['sha256'])
                if saved.size_bytes != row['size_bytes']:
                    raise IntegrityFailure('backup.artifact_size')
                artifacts.append(asdict(saved))
            dump_hash = _file_hash(temp / 'database.dump')
            manifest = dict(schema_version='product-backup/v2', revision=revision, counts=counts,
                application_version=os.environ.get('PRODUCT_RELEASE_ID', 'development'),
                created_at=now.isoformat(), search_files=search_files, search_recovery_cursor=recovery_cursor,
                database_sha256=dump_hash, artifacts=artifacts, complete=True)
            release_path = settings.root / 'config/release-path'
            if release_path.is_file():
                manifest['previous_release_path'] = release_path.read_text().strip()
            _write_json(temp / 'manifest.json', manifest)
            for name in ('database.dump', 'manifest.json'):
                with (temp / name).open('rb') as f:
                    os.fsync(f.fileno())
            os.rename(temp, temp.with_suffix(''))
            _sync_directory(temp.parent)
            return {'backup': str(temp.with_suffix('')), 'artifacts': len(artifacts), 'search_files': len(search_files)}
        finally:
            db.dispose()


def _restore_search(db, settings, source, manifest, snapshot, now):
    from ...search.recovery import initialize_restored_authority
    from ...search.repository import PAGES, SUBMISSIONS, SearchRepository

    with db.connect() as connection:
        has_recovery = connection.exec_driver_sql("SELECT to_regclass('search_recovery_state')").scalar() is not None
    if not has_recovery:
        return {'files': 0, 'deleted_search_ids': []}
    deleted = {'deleted_search_ids': []}
    if snapshot is not None:
        repository = SearchRepository(db, settings.root / 'work/search/private-v1', clock=lambda: now, initialize_recovery=False)
        deleted = repository.replay_deletions(snapshot)
    initialize_restored_authority(db, settings.root / 'work/search/private-v1')
    with db.connect() as connection:
        owners = {}
        for category, table in (('pages', PAGES), ('submissions', SUBMISSIONS)):
            for row in connection.execute(select(table)).mappings():
                owners[(category, row['id'])] = row
        entries = {entry['storage_key']: entry for entry in manifest.get('search_files', [])}
        for (category, _identifier), owner in owners.items():
            state = 'image_state' if category == 'pages' else 'artifact_state'
            if owner[state] != 'active' or owner['expires_at'] <= now:
                continue
            required = {'page.png': 'sha256'} if category == 'pages' else {
                'question.png': 'crop_sha256', 'original.png': 'original_sha256'}
            for filename, column in required.items():
                entry = entries.get(owner['storage_key'] + '/' + filename)
                if entry is None or entry['sha256'] != owner[column]:
                    raise IntegrityFailure('restore.search_required_file')
        selected = []
        for entry in manifest.get('search_files', []):
            owner = owners.get((entry['owner_type'], entry['owner_id']))
            if owner is None:
                continue
            state = 'image_state' if entry['owner_type'] == 'pages' else 'artifact_state'
            if (entry['storage_key'].split('/')[:2] != owner['storage_key'].split('/')
                    or datetime.fromisoformat(entry['expires_at']) != owner['expires_at']):
                raise IntegrityFailure('restore.search_file_owner')
            if owner[state] == 'active' and owner['expires_at'] > now:
                selected.append(entry)
    restored = restore_search_files(source, settings.root / 'work/search/private-v1', manifest.get('search_files', []),
                                    selected_keys={entry['storage_key'] for entry in selected}, now=now)
    repository = SearchRepository(db, settings.root / 'work/search/private-v1', clock=lambda: now)
    cleanup = repository.cleanup()
    recovered = repository.recover()
    with db.connect() as connection:
        if any(connection.scalars(select(PAGES.c.pending_cleanup_keys))):
            raise IntegrityFailure('restore.search_cleanup_incomplete')
    return {**deleted, 'files': restored, 'cleanup': cleanup, 'interrupted': recovered}


def restore_data(settings, source, *, search_recovery_root=None, now=None):
    clock = (lambda: now) if now is not None else (lambda: datetime.now(UTC))
    now = now or datetime.now(UTC)
    source = Path(source).resolve()
    db = engine(settings.url('migration'))
    try:
        with db.connect() as c:
            if c.exec_driver_sql("SELECT count(*) FROM pg_tables WHERE schemaname='public'").scalar():
                raise Conflict('restore.target_database_not_empty')
        storage = LocalArtifactStorage(settings.artifact_root)
        if storage.orphan_report([]):
            raise Conflict('restore.target_artifacts_not_empty')
        private_root = settings.root / 'work/search/private-v1'
        if private_root.exists() and any(private_root.iterdir()):
            raise Conflict('restore.target_search_not_empty')
        marker = settings.root / 'locks/restore-incomplete'
        _write_json(marker, {'state': 'restoring', 'started_at': now.isoformat()})
        _sync_directory(marker.parent)
        with stopped_writes(settings, keep_on_failure=True), ExitStack() as stack:
            if (source / '.lease').exists():
                stack.enter_context(backup_lease(source, shared=True))
            manifest = json.loads((source / 'manifest.json').read_text())
            version = manifest.get('schema_version')
            if version not in {'product-backup/v1', 'product-backup/v2'} or not manifest.get('complete'):
                raise IntegrityFailure('restore.incomplete_backup')
            if version == 'product-backup/v2' and not (source / '.lease').is_file():
                raise IntegrityFailure('restore.backup_lease_missing')
            if _file_hash(source / 'database.dump') != manifest['database_sha256']:
                raise IntegrityFailure('restore.dump_hash')
            has_search = any(manifest['counts'].get(name, 0) for name in ('search_pages', 'search_submissions'))
            snapshot = None
            if has_search:
                if version != 'product-backup/v2' or not manifest.get('search_recovery_cursor'):
                    raise IntegrityFailure('restore.search_backup_unsupported')
                if search_recovery_root is None:
                    raise IntegrityFailure('restore.current_search_recovery_required')
                authority_root = Path(search_recovery_root).resolve()
                if authority_root == source or source in authority_root.parents or authority_root == private_root.resolve():
                    raise IntegrityFailure('restore.independent_search_recovery_required')
                from ...search.recovery import RecoveryJournal
                snapshot = stack.enter_context(RecoveryJournal(authority_root).locked_snapshot())
                snapshot.validate_cursor(manifest['search_recovery_cursor'])
            if version == 'product-backup/v2':
                validate_search_files(source, manifest['search_files'], now=now)
            original = LocalArtifactStorage(source / 'artifacts')
            for artifact in manifest['artifacts']:
                parts(artifact['storage_key'])
                if not original.verify(artifact['storage_key'], artifact['sha256'], artifact['size_bytes']).ok:
                    raise IntegrityFailure('restore.artifact_hash')
            pg_tool(settings, 'pg_restore', '--exit-on-error', '--single-transaction', '--no-owner', '--no-acl',
                    '--dbname', 'product', source / 'database.dump')
            with transaction(db) as c:
                grant(c)
                if table_counts(c) != manifest['counts']:
                    raise IntegrityFailure('restore.row_count')
                if c.exec_driver_sql('SELECT version_num FROM alembic_version').scalar_one() != manifest['revision']:
                    raise IntegrityFailure('restore.revision')
                c.execute(m.student_login_sessions.update().values(revoked_at=now))
                c.execute(m.student_sms_challenges.update().where(
                    m.student_sms_challenges.c.consumed_at.is_(None)).values(consumed_at=now))
            for artifact in manifest['artifacts']:
                with original.open(artifact['storage_key']) as stream:
                    storage.put_immutable(artifact['storage_key'], stream, artifact['sha256'])
            search = _restore_search(db, settings, source, manifest, snapshot, clock())
            result = doctor(settings, maintenance=True)
            marker.unlink()
            _sync_directory(marker.parent)
        return {**result, 'search': search}
    finally:
        db.dispose()
