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
