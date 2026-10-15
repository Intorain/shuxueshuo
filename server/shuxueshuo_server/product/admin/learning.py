"""Explicit local replacement of legacy learning data, separate from publishing."""
import os

from sqlalchemy import text

from ..db import engine, lock
from ..errors import Conflict, ProductError
from . import database
from .backup import backup, stopped_writes

# Deliberately no CASCADE: an unexpected foreign key must stop the replacement.
LEGACY_TABLES = (
    'student_step_results', 'student_practice_events', 'student_practice_attempts',
    'knowledge_drill_answers', 'knowledge_drill_attempts',
    'practice_step_nodes', 'practice_steps', 'practice_problem_methods',
    'practice_topic_problems', 'practice_topics', 'practice_problems',
    'knowledge_drill_items', 'knowledge_edges', 'knowledge_nodes',
)


def legacy_scope(connection):
    revision = connection.scalar(text('SELECT version_num FROM alembic_version'))
    if revision != '0010_learning_record_integrity':
        raise Conflict('learning.rebuild_requires_legacy_0010')
    counts = {table: connection.scalar(text(f'SELECT count(*) FROM {table}'))
              for table in LEGACY_TABLES}
    counts['student_learning_marks'] = connection.scalar(text(
        'SELECT count(*) FROM student_learning_marks '
        'WHERE problem_id IN (SELECT id FROM practice_problems)'))
    return counts


def replace_legacy(connection, settings, rows):
    """Caller owns the transaction, including the DDL and publication."""
    from ...learning.content import publish

    lock(connection, 'learning.publish')
    scope = legacy_scope(connection)
    connection.execute(text('DELETE FROM student_learning_marks '
                            'WHERE problem_id IN (SELECT id FROM practice_problems)'))
    for table in LEGACY_TABLES:
        connection.execute(text(f'DELETE FROM {table}'))
    database.migrate(settings, connection=connection)
    result = publish(connection, rows)
    return {'cleared': scope, 'publication': result}


def rebuild(settings):
    from ...learning.content import load_content

    if settings.mode != 'local' or os.environ.get('PRODUCT_IN_CONTAINER') == '1':
        raise ProductError('learning.rebuild_local_only')
    rows = load_content()
    db = engine(settings.url('migration'))
    try:
        with db.connect() as connection:
            scope = legacy_scope(connection)
        # Surface the exact scope before stopping writes or creating a backup.
        print('本地重建清理范围：' + ', '.join(f'{name}={count}' for name, count in scope.items()), flush=True)
        with stopped_writes(settings, keep_on_failure=True):
            saved = backup(settings, fenced=True)
            with db.begin() as connection:
                result = replace_legacy(connection, settings, rows)
            checks = database.doctor(settings, maintenance=True)
        return {**checks, **saved, **result}
    finally:
        db.dispose()


def reassess(settings):
    from ...learning.assessment import rebuild as rebuild_assessments

    db = engine(settings.url('migration'))
    try:
        return rebuild_assessments(db)
    finally:
        db.dispose()


PERSONAL_TABLES = (
    'student_step_results', 'student_practice_events', 'student_practice_attempts',
    'knowledge_drill_answers', 'knowledge_drill_attempts', 'student_learning_marks',
)
LEGACY_PUBLIC_TABLES = tuple(t for t in LEGACY_TABLES if t not in PERSONAL_TABLES)


def inspect_content(connection):
    """Only SELECTs; usable inside an explicitly read-only transaction on an old DB."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from ..config import REPO

    existing = set(connection.execute(text(
        "SELECT tablename FROM pg_tables WHERE schemaname='public'")).scalars())
    revisions = (list(connection.execute(text('SELECT version_num FROM alembic_version')).scalars())
                 if 'alembic_version' in existing else [])
    revision = revisions[0] if len(revisions) == 1 else None
    counts = {table: connection.scalar(text(f'SELECT count(*) FROM {table}'))
              for table in (*PERSONAL_TABLES, 'knowledge_nodes') if table in existing}
    result = {'revision': revision, 'counts': counts, 'content_version': None,
              'schema_version': None, 'state': 'blocked'}
    scripts = ScriptDirectory.from_config(Config(str(REPO / 'server/alembic.ini')))
    known = {item.revision for item in scripts.walk_revisions()}
    if (existing and revision is None) or len(revisions) > 1 or (revision is not None and revision not in known):
        return {**result, 'reason': 'learning.unknown_database_revision'}
    if 'learning_content_current' in existing:
        current = connection.execute(text(
            "SELECT c.content_version,r.schema_version FROM learning_content_current c "
            "JOIN learning_content_releases r USING(content_version) WHERE c.id='public'")).mappings().first()
        if current:
            if current['schema_version'] != 2:
                return {**result, 'reason': 'learning.unsupported_content_schema'}
            return {**result, **dict(current), 'state': 'current', 'action': 'deploy'}
    if any(counts.get(table, 0) for table in PERSONAL_TABLES):
        # Before 0009 there is no public content to replace and the only personal table is
        # the whole-problem marks, which 0008 renames in place; nothing in the chain deletes them.
        if 'knowledge_nodes' not in existing and set(counts) & set(PERSONAL_TABLES) == {'student_learning_marks'}:
            return {**result, 'state': 'empty', 'action': 'deploy',
                    'kept': {'student_learning_marks': counts['student_learning_marks']}}
        return {**result, 'reason': 'learning.legacy_personal_records_present'}
    if counts.get('knowledge_nodes', 0):
        if revision != '0010_learning_record_integrity':
            return {**result, 'reason': 'learning.public_replacement_requires_0010'}
        return {**result, 'state': 'legacy_public_only', 'action': 'deploy --replace-legacy-public'}
    return {**result, 'state': 'empty', 'action': 'install' if not revision else 'deploy'}


def preflight(settings):
    db = engine(settings.url('migration'))
    try:
        with db.begin() as connection:
            connection.execute(text('SET TRANSACTION READ ONLY'))
            result = inspect_content(connection)
        return result
    finally:
        db.dispose()


def replace_legacy_public(connection, settings, rows):
    """Explicit first publication. Never delete any personal or unrelated product rows."""
    from ...learning.content import publish

    lock(connection, 'learning.publish')
    state = inspect_content(connection)
    if state['state'] != 'legacy_public_only':
        raise Conflict(state.get('reason', 'learning.public_replacement_not_applicable'))
    removed = legacy_scope(connection)
    for table in LEGACY_PUBLIC_TABLES:
        connection.execute(text(f'DELETE FROM {table}'))
    database.migrate(settings, connection=connection)
    result = publish(connection, rows)
    return {'replaced_public': {k: v for k, v in removed.items() if k in LEGACY_PUBLIC_TABLES},
            'publication': result}


def deploy(settings, *, replace_public=False):
    """Backup, then atomic DDL and publication under one write fence.

    The public site is not part of the release: the server repository's site/
    is updated with git pull and checked by verify_release."""
    from ...learning.content import load_content, publish

    rows = load_content()
    state = preflight(settings)
    if state['state'] == 'blocked':
        raise Conflict(state['reason'])
    if (state['state'] == 'legacy_public_only') != replace_public:
        raise Conflict('learning.explicit_public_replacement_required' if not replace_public
                       else 'learning.public_replacement_not_applicable')
    db = engine(settings.url('migration'))
    try:
        with stopped_writes(settings, keep_on_failure=True):
            saved = backup(settings, fenced=True)
            with db.begin() as connection:
                lock(connection, 'learning.publish')
                # Recheck after fencing; a preflight result never authorizes a stale delete.
                current = inspect_content(connection)
                if current['state'] == 'blocked':
                    raise Conflict(current['reason'])
                if replace_public:
                    result = replace_legacy_public(connection, settings, rows)
                else:
                    if current['state'] == 'legacy_public_only':
                        raise Conflict('learning.explicit_public_replacement_required')
                    database.migrate(settings, connection=connection)
                    result = publish(connection, rows)
            checks = database.doctor(settings, maintenance=True)
        return {**checks, **saved, **result}
    finally:
        db.dispose()


CONTENT_KEYS = ('content_version', 'schema_version')


def site_content(site_version):
    """Content version of the git-pulled site; None if unreadable or invalid."""
    import json
    import re

    if site_version is None:
        return None
    try:
        if not site_version.is_file():
            return None
        data = json.loads(site_version.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    version = data.get('content_version')
    schema = data.get('schema_version')
    if not isinstance(version, str) or re.fullmatch(r'[0-9a-f]{64}', version) is None:
        return None
    if type(schema) is not int or schema <= 0:
        return None
    return data


def verify_release(settings, site_version=None, *, require_site=True):
    """The database must hold this image's content. The public site (pages from
    git pull) must match it too; otherwise practice pages stop saving progress."""
    from ...learning.content import load_content

    expected = load_content()['_meta']
    state = preflight(settings)
    if state['state'] != 'current' or any(state[k] != expected[k] for k in CONTENT_KEYS):
        raise Conflict('release.content_version_mismatch')
    site = site_content(site_version)
    site_state = ('missing' if site is None else
                  'match' if all(site[k] == expected[k] for k in CONTENT_KEYS) else 'mismatch')
    if require_site and site_state != 'match':
        raise Conflict(f'release.site_content_{site_state}')
    return {'ok': True, 'content_version': expected['content_version'], 'site': site_state}
