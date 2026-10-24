"""PostgreSQL-owned lesson execution state and calculation accounting."""

from pathlib import Path

from sqlalchemy import text

from alembic import op

revision = '0014_lesson_execution'
down_revision = '0013_student_search'
branch_labels = depends_on = None


def upgrade():
    op.get_bind().execute(text(Path(__file__).with_suffix('.sql').read_text()))


def downgrade():
    raise RuntimeError('Restore into a separate instance; do not discard execution evidence.')
