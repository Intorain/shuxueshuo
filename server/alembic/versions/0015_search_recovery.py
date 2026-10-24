"""Bind independent search deletion authority to the database."""

from pathlib import Path

from sqlalchemy import text

from alembic import op

revision = '0015_search_recovery'
down_revision = '0014_lesson_execution'
branch_labels = depends_on = None


def upgrade():
    op.get_bind().execute(text(Path(__file__).with_suffix('.sql').read_text()))


def downgrade():
    raise RuntimeError('Deletion authority must survive restoration; downgrade is unsupported.')
