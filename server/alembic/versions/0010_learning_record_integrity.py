"""Retire public nodes and keep raw practice events immutable."""

from pathlib import Path

from sqlalchemy import text

from alembic import op

revision = "0010_learning_record_integrity"
down_revision = "0009_learning_graph"
branch_labels = depends_on = None


def upgrade():
    op.get_bind().execute(text(Path(__file__).with_suffix(".sql").read_text()))


def downgrade():
    raise RuntimeError("Restore into a separate instance; do not discard student data.")
