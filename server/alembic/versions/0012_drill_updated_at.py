"""Track drill round activity and closure without changing original evidence."""

from pathlib import Path

from sqlalchemy import text

from alembic import op

revision = '0012_drill_updated_at'
down_revision = '0011_public_learning_content'
branch_labels = depends_on = None


def upgrade():
    op.get_bind().execute(text(Path(__file__).with_suffix('.sql').read_text()))


def downgrade():
    raise RuntimeError('Restore into a separate instance; do not discard student data.')
