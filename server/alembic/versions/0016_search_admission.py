"""Persist search admission and quotas without coupling them to private retention."""

from pathlib import Path

from sqlalchemy import text

from alembic import op

revision = '0016_search_admission'
down_revision = '0015_search_recovery'
branch_labels = depends_on = None


def upgrade():
    op.get_bind().execute(text(Path(__file__).with_suffix('.sql').read_text()))


def downgrade():
    raise RuntimeError('Consumed search quotas must not be reset by downgrade.')
