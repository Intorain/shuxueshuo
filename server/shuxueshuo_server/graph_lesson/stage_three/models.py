"""Shared execution tables; run identity is the mandatory partition key."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


def register(metadata):
    runs = sa.Table("lesson_runs", metadata,
        sa.Column("run_id", sa.Text, primary_key=True),
        sa.Column("submission_id", sa.Text, sa.ForeignKey("search_submissions.id", ondelete="CASCADE")),
        sa.Column("identity", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")))
    sa.Index("ix_lesson_runs_submission", runs.c.submission_id)

    def table(name, keys, fields, *constraints):
        columns = [sa.Column("run_id", sa.Text, sa.ForeignKey("lesson_runs.run_id", ondelete="CASCADE"), primary_key=True)]
        columns.extend(sa.Column(key, sa.Text, primary_key=True) for key in keys.split())
        for column_name, kind, nullable in fields:
            columns.append(sa.Column(column_name, kind, nullable=nullable))
        return sa.Table("lesson_" + name, metadata, *columns, *constraints)

    def fields(*names):
        return [(name, sa.Text, False) for name in names]

    table("metadata", "key", fields("value"))
    commits = table("commits", "id", fields("digest", "result"))
    commits.append_column(sa.Column("sequence", sa.BigInteger, sa.Identity(always=True), nullable=False))
    table("checkpoints", "target route", fields("value"))
    table("steps", "target route step", [("ordinal", sa.BigInteger, False), *fields("value")],
          sa.UniqueConstraint("run_id", "target", "route", "ordinal"))
    sa.Table("lesson_events", metadata,
        sa.Column("run_id", sa.Text, sa.ForeignKey("lesson_runs.run_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("seq", sa.BigInteger, primary_key=True), sa.Column("value", sa.Text, nullable=False))
    table("goals", "target", fields("value"))
    table("handoffs", "target route", fields("value"))
    table("qa", "target route step", fields("value"))
    table("selection_chunks", "target kind", [("seq", sa.BigInteger, False), *fields("value")])
    table("step_summaries", "target route step", [("ordinal", sa.BigInteger, False), *fields("hash")],
          sa.UniqueConstraint("run_id", "target", "route", "ordinal"))
    table("interaction_states", "target route step", [("ordinal", sa.BigInteger, False), *fields("hash", "status"),
                                                       ("interaction_id", sa.Text, True)])
    table("interactions", "interaction_id", [*fields("target", "route"), ("ordinal", sa.BigInteger, False), *fields("value")])
    table("calculation_budgets", "target route bucket", [("limit_seconds", sa.Double, False), ("initial_seconds", sa.Double, False)])
    table("calculation_leases", "target route", [*fields("owner"), ("pid", sa.BigInteger, False),
        ("acquired_at", sa.Double, False), ("released", sa.Integer, False)])
    attempts = table("calculation_attempts", "attempt_id", [*fields("target", "route", "bucket", "operation_key", "input_hash"),
        ("ordinal", sa.BigInteger, False), *fields("owner", "status"),
        ("allowance_seconds", sa.Double, False), ("elapsed_seconds", sa.Double, False),
        ("reserved_upper_seconds", sa.Double, False), ("receipt", sa.Text, True)],
        sa.UniqueConstraint("run_id", "target", "route", "bucket", "operation_key", "ordinal"))
    attempts.append_column(sa.Column("sequence", sa.BigInteger, sa.Identity(always=True), nullable=False))
    return runs
