"""Read/permission metadata; reviewed migrations own constraints and indexes."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


def register(metadata):
    sa.Table(
        "knowledge_nodes",
        metadata,
        sa.Column("id", sa.Text, primary_key=True, nullable=False),
        sa.Column("label", sa.Text, primary_key=False, nullable=False),
        sa.Column("kind", sa.Text, primary_key=False, nullable=False),
        sa.Column("subtype", sa.Text, primary_key=False, nullable=True),
        sa.Column("summary", sa.Text, primary_key=False, nullable=False),
        sa.Column("explanation_md", sa.Text, primary_key=False, nullable=False),
        sa.Column("sheet", sa.Text, primary_key=False, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False),
    )
    sa.Table(
        "knowledge_edges",
        metadata,
        sa.Column("source_id", sa.Text, primary_key=True, nullable=False),
        sa.Column("target_id", sa.Text, primary_key=True, nullable=False),
        sa.Column("relation_type", sa.Text, primary_key=True, nullable=False),
    )
    sa.Table(
        "practice_problems",
        metadata,
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("label", sa.Text, nullable=False),
        sa.Column("path", sa.Text, nullable=False),
        sa.Column("lesson_file", sa.Text, nullable=False),
        sa.Column("statement_md", sa.Text, nullable=False),
        sa.Column("problem_data", JSONB, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False),
    )
    sa.Table(
        "practice_topic_problems",
        metadata,
        sa.Column("topic_id", sa.Text, primary_key=True, nullable=False),
        sa.Column("problem_id", sa.Text, primary_key=True, nullable=False),
    )
    sa.Table(
        "practice_problem_methods",
        metadata,
        sa.Column("problem_id", sa.Text, primary_key=True, nullable=False),
        sa.Column("route_id", sa.Text, primary_key=True, nullable=False),
        sa.Column("method_node_id", sa.Text, primary_key=False, nullable=False),
    )
    sa.Table(
        "practice_steps",
        metadata,
        sa.Column("problem_id", sa.Text, primary_key=True, nullable=False),
        sa.Column("route_id", sa.Text, primary_key=True, nullable=False),
        sa.Column("step_id", sa.Text, primary_key=True, nullable=False),
        sa.Column("title", sa.Text, primary_key=False, nullable=False),
        sa.Column("position", sa.Integer, primary_key=False, nullable=False),
    )
    sa.Table(
        "practice_step_nodes",
        metadata,
        sa.Column("problem_id", sa.Text, primary_key=True, nullable=False),
        sa.Column("route_id", sa.Text, primary_key=True, nullable=False),
        sa.Column("step_id", sa.Text, primary_key=True, nullable=False),
        sa.Column("node_id", sa.Text, primary_key=True, nullable=False),
    )
    sa.Table(
        "knowledge_drill_items",
        metadata,
        sa.Column("node_id", sa.Text, primary_key=True, nullable=False),
        sa.Column("item_id", sa.Text, primary_key=True, nullable=False),
        sa.Column("statement_md", sa.Text, primary_key=False, nullable=False),
        sa.Column("question_type", sa.Text, primary_key=False, nullable=False),
        sa.Column("options", JSONB, primary_key=False, nullable=True),
        sa.Column("answer_spec", JSONB, primary_key=False, nullable=False),
        sa.Column("explanation_md", sa.Text, primary_key=False, nullable=False),
        sa.Column("is_active", sa.Boolean, primary_key=False, nullable=False),
    )
    sa.Table(
        "knowledge_drill_attempts",
        metadata,
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), primary_key=False, nullable=False),
        sa.Column("node_id", sa.Text, primary_key=False, nullable=False),
        sa.Column("status", sa.Text, primary_key=False, nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), primary_key=False, nullable=False
        ),
        sa.Column(
            "completed_at", sa.DateTime(timezone=True), primary_key=False, nullable=True
        ),
    )
    sa.Table(
        "knowledge_drill_answers",
        metadata,
        sa.Column("attempt_id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("position", sa.Integer, primary_key=True, nullable=False),
        sa.Column("item_id", sa.Text, primary_key=False, nullable=False),
        sa.Column("selected", JSONB, primary_key=False, nullable=True),
        sa.Column("is_correct", sa.Boolean, primary_key=False, nullable=True),
        sa.Column(
            "answered_at", sa.DateTime(timezone=True), primary_key=False, nullable=True
        ),
    )
    sa.Table(
        "student_practice_attempts",
        metadata,
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), primary_key=False, nullable=False),
        sa.Column("problem_id", sa.Text, primary_key=False, nullable=False),
        sa.Column("route_id", sa.Text, primary_key=False, nullable=False),
        sa.Column("problem_context", JSONB, primary_key=False, nullable=False),
        sa.Column("status", sa.Text, primary_key=False, nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), primary_key=False, nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), primary_key=False, nullable=False
        ),
        sa.Column(
            "completed_at", sa.DateTime(timezone=True), primary_key=False, nullable=True
        ),
    )
    sa.Table(
        "student_practice_events",
        metadata,
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("attempt_id", UUID(as_uuid=True), primary_key=False, nullable=False),
        sa.Column("step_id", sa.Text, primary_key=False, nullable=False),
        sa.Column("sequence", sa.BigInteger, primary_key=False, nullable=False),
        sa.Column("event_type", sa.Text, primary_key=False, nullable=False),
        sa.Column(
            "related_event_id", UUID(as_uuid=True), primary_key=False, nullable=True
        ),
        sa.Column("payload", JSONB, primary_key=False, nullable=False),
        sa.Column("displayed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), primary_key=False, nullable=False
        ),
    )
    sa.Table(
        "student_step_results",
        metadata,
        sa.Column("attempt_id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("step_id", sa.Text, primary_key=True, nullable=False),
        sa.Column("passed", sa.Boolean, primary_key=False, nullable=False),
        sa.Column("submit_count", sa.Integer, primary_key=False, nullable=False),
        sa.Column("wrong_count", sa.Integer, primary_key=False, nullable=False),
        sa.Column("hint_used", sa.Boolean, primary_key=False, nullable=False),
        sa.Column("last_grading_source", sa.Text, primary_key=False, nullable=True),
        sa.Column(
            "last_submitted_at",
            sa.DateTime(timezone=True),
            primary_key=False,
            nullable=True,
        ),
        sa.Column(
            "summary_through_sequence", sa.BigInteger, primary_key=False, nullable=False
        ),
    )
    sa.Table(
        "practice_topics",
        metadata,
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("label", sa.Text, nullable=False),
        sa.Column("path", sa.Text, nullable=False),
    )
