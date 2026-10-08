"""Public content and student learning evidence."""
from pathlib import Path
from sqlalchemy import text
from alembic import op

revision = '0009_learning_graph'
down_revision = '0008_practice_identity'
branch_labels = depends_on = None


def upgrade():
    op.get_bind().execute(text(Path(__file__).with_suffix('.sql').read_text()))


def downgrade():
    raise RuntimeError('Restore into a separate instance; do not discard student data.')
