"""python -m shuxueshuo_server.product.admin.cli --mode local COMMAND"""
import argparse
import fcntl
import json
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import psycopg
from sqlalchemy.exc import SQLAlchemyError

from ..config import Settings
from ..db import engine
from ..errors import Conflict, IntegrityFailure, ProductError
from . import database, native


@contextmanager
def instance_lock(root):
    directory = root / 'locks'
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (directory / 'admin.lock').open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Conflict('admin.instance_busy') from None
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def main(argv=None):
    p = argparse.ArgumentParser(description='Product P1 administration (no Review import)')
    p.add_argument('--mode', required=True, choices=['local', 'server'])
    p.add_argument('--data-dir')
    p.add_argument('--instance')
    p.add_argument('--port', type=int)
    p.add_argument('--pg-bin')
    p.add_argument('command', choices=['configure', 'install', 'deploy', 'resume', 'bootstrap', 'migrate', 'seed', 'doctor', 'status', 'db-start', 'db-stop', 'backup', 'backup-prune', 'restore',
        'publish-learning', 'check-learning', 'preflight-learning', 'verify-release', 'rebuild-learning', 'reassess-learning',
        'services-install', 'services-start', 'services-stop', 'services-status', 'services-doctor'])
    p.add_argument('--backup')
    p.add_argument('--search-recovery-root', type=Path, help='current independent source search root, never a backup copy')
    p.add_argument('--target')
    p.add_argument('--site-version', type=Path, help='knowledge/teaching/version.json of the served site')
    p.add_argument('--site-optional', action='store_true', help='report, but do not refuse, a site content mismatch')
    p.add_argument('--replace-legacy-public', action='store_true')
    args = p.parse_args(argv)
    try:
        initialize = args.command in ('configure', 'install', 'restore')
        if args.command == 'restore':
            if not args.target or not args.backup or not args.data_dir or args.target == (args.instance or args.mode):
                raise ProductError('restore.requires_new_target_and_data_dir')
            if (Path(args.data_dir) / 'config').exists():
                raise Conflict('restore.target_already_installed')
            args.instance = args.target
        settings = Settings.load(args.mode, args.data_dir, args.instance, args.port, initialize=initialize, pg_bin=args.pg_bin)
        if args.replace_legacy_public and args.command != 'deploy':
            raise ProductError('learning.public_replacement_requires_deploy')
        if args.command in ('preflight-learning', 'verify-release'):
            result = execute(settings, args)
        else:
            with instance_lock(settings.root):
                result = execute(settings, args)
        print(json.dumps(result or {'ok': True}, ensure_ascii=False, default=str))
        return 0
    except IntegrityFailure as exc:
        print(str(exc), file=sys.stderr)
        return 5
    except (ProductError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 4 if str(exc).startswith('migration.') else 2
    except (SQLAlchemyError, psycopg.Error, subprocess.CalledProcessError) as exc:
        # Drivers/commands may contain secrets in their exception text. Never echo it.
        print(f'operation failed: {type(exc).__name__}; inspect the instance logs', file=sys.stderr)
        return 4 if args.command in ('migrate', 'install') else 3
    except Exception as exc:
        print(f'operation failed: {type(exc).__name__}', file=sys.stderr)
        return 4 if args.command in ('migrate', 'install') else 5


def execute(settings, args):
    operation = args.command
    if operation.startswith('services-'):
        from .runtime import execute as execute_runtime
        return execute_runtime(settings, operation)
    if operation == 'deploy':
        from .learning import deploy
        return deploy(settings, replace_public=args.replace_legacy_public)
    if operation == 'preflight-learning':
        from .learning import preflight
        return preflight(settings)
    if operation == 'verify-release':
        from .learning import verify_release
        return verify_release(settings, args.site_version, require_site=not args.site_optional)
    if operation == 'publish-learning':
        if settings.mode == 'server':
            from .learning import verify_release
            verify_release(settings, require_site=False)
        return publish_learning(settings)
    if operation == 'check-learning':
        from ...learning.content import load_content
        return load_content()['_meta']
    if operation in ('rebuild-learning', 'reassess-learning'):
        from .learning import reassess, rebuild
        return (rebuild if operation == 'rebuild-learning' else reassess)(settings)
    if operation == 'resume':
        from .backup import require_restore_complete
        require_restore_complete(settings)
        if settings.mode == 'server':
            from .learning import verify_release
            verify_release(settings, require_site=False)
        result = database.doctor(settings, maintenance=True)
        with psycopg.connect(database.dsn(settings.url('bootstrap')), autocommit=True) as c:
            c.execute('ALTER ROLE product_app LOGIN')
        return result
    if operation == 'configure':
        return {'ok': True, 'data_dir': str(settings.root), 'instance': settings.instance}
    if operation in ('db-start', 'db-stop'):
        if settings.mode != 'local':
            raise ProductError('use_server_compose_for_database_lifecycle')
        return (native.start if operation == 'db-start' else native.stop)(settings)
    if operation == 'status':
        return {'instance': settings.instance, 'data_dir': str(settings.root),
                'running': native.status(settings) if settings.mode == 'local' else database.doctor(settings, probe=False)['ok']}
    if operation in ('install', 'restore'):
        if settings.mode == 'local':
            native.start(settings)
        database.bootstrap(settings)
    if operation == 'bootstrap':
        return database.bootstrap(settings)
    if operation in ('install', 'migrate'):
        database.migrate(settings)
    if operation in ('install', 'seed'):
        db = engine(settings.url('migration'))
        try:
            context = database.seed(db)
        finally:
            db.dispose()
        if operation == 'seed':
            return {'workspace_id': context.workspace_id, 'user_id': context.user_id}
    if operation == 'install':
        publish_learning(settings)
    if operation in ('install', 'doctor'):
        return database.doctor(settings)
    if operation == 'backup':
        from .backup import backup
        return backup(settings)
    if operation == 'backup-prune':
        from .search_backup import prune_backups
        return prune_backups(settings)
    if operation == 'restore':
        from .backup import restore_data
        return restore_data(settings, args.backup, search_recovery_root=args.search_recovery_root)




def publish_learning(settings):
    from ...learning.content import load_content, publish
    db = engine(settings.url('migration'))
    try:
        return publish(db, load_content())
    finally:
        db.dispose()

if __name__ == '__main__':
    sys.exit(main())
