"""Site-wide search content and private student submissions."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


def register(metadata):
    sa.Table('search_admission_control', metadata,
        sa.Column('singleton', sa.Boolean, primary_key=True, server_default=sa.text('true')),
        sa.Column('generation_enabled', sa.Boolean, nullable=False, server_default=sa.text('false')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.CheckConstraint('singleton', name='search_admission_singleton'))
    tickets = sa.Table('search_admission_tickets', metadata,
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('search_id', sa.Text, nullable=False),
        sa.Column('kind', sa.Text, nullable=False),
        sa.Column('request_id', sa.Text),
        sa.Column('quota_day', sa.Date, nullable=False),
        sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('state', sa.Text, nullable=False),
        sa.Column('consumed', sa.Boolean, nullable=False, server_default=sa.text('false')),
        sa.Column('started_at', sa.DateTime(timezone=True)),
        sa.Column('finished_at', sa.DateTime(timezone=True)),
        sa.Column('error_code', sa.Text),
        sa.UniqueConstraint('user_id', 'kind', 'request_id'),
        sa.CheckConstraint("kind IN ('generation','rerun','continuation')", name='search_admission_kind'),
        sa.CheckConstraint("state IN ('reserved','running','finished','cancelled','interrupted')", name='search_admission_state'),
        sa.CheckConstraint("NOT consumed OR (kind IN ('generation','rerun') AND started_at IS NOT NULL)", name='search_admission_consumed'),
        sa.CheckConstraint("state != 'reserved' OR (NOT consumed AND started_at IS NULL AND finished_at IS NULL)", name='search_admission_reserved'),
        sa.CheckConstraint("state NOT IN ('running','finished','interrupted') OR started_at IS NOT NULL", name='search_admission_started'),
        sa.CheckConstraint("state NOT IN ('finished','cancelled','interrupted') OR finished_at IS NOT NULL", name='search_admission_finished'))
    sa.Index('ix_search_admission_active', tickets.c.state, tickets.c.user_id,
             postgresql_where=tickets.c.state.in_(('reserved', 'running')))
    sa.Index('ix_search_admission_daily', tickets.c.quota_day, tickets.c.kind, tickets.c.user_id,
             postgresql_where=sa.or_(tickets.c.consumed.is_(True), tickets.c.state == 'reserved'))
    sa.Index('ix_search_admission_submission', tickets.c.search_id,
             postgresql_where=tickets.c.state == 'reserved')
    sa.Table('search_recovery_state', metadata,
        sa.Column('singleton', sa.Boolean, primary_key=True, server_default=sa.text('true')),
        sa.Column('authority_id', UUID(as_uuid=True), nullable=False),
        sa.Column('initialized', sa.Boolean, nullable=False, server_default=sa.text('false')),
        sa.Column('sequence', sa.BigInteger, nullable=False, server_default=sa.text('0')),
        sa.Column('replayed_sequence', sa.BigInteger, nullable=False, server_default=sa.text('0')),
        sa.Column('digest', sa.Text, nullable=False, server_default=''),
        sa.CheckConstraint('singleton', name='search_recovery_singleton'),
        sa.CheckConstraint('sequence >= 0', name='search_recovery_sequence'),
        sa.CheckConstraint('replayed_sequence >= 0 AND replayed_sequence <= sequence', name='search_recovery_replayed'))
    problems = sa.Table('search_problems', metadata,
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('identity_version', sa.Integer, nullable=False),
        sa.Column('fingerprint', sa.Text, nullable=False),
        sa.Column('identity_json', JSONB, nullable=False),
        sa.Column('statement', sa.Text, nullable=False),
        sa.Column('structured_problem', JSONB, nullable=False),
        sa.Column('status', sa.Text, nullable=False, server_default='active'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.UniqueConstraint('identity_version', 'fingerprint'),
        sa.CheckConstraint("status IN ('active','disabled')", name='search_problem_status'))
    pages = sa.Table('search_pages', metadata,
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('parent_page_id', sa.Text),
        sa.Column('root_page_id', sa.Text, nullable=False),
        sa.Column('storage_key', sa.Text, nullable=False, unique=True),
        sa.Column('sha256', sa.Text, nullable=False),
        sa.Column('width', sa.Integer, nullable=False),
        sa.Column('height', sa.Integer, nullable=False),
        sa.Column('metadata', JSONB, nullable=False),
        sa.Column('image_state', sa.Text, nullable=False, server_default='active'),
        sa.Column('pending_cleanup_keys', JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('id', 'user_id'),
        sa.ForeignKeyConstraint(['parent_page_id', 'user_id'], ['search_pages.id', 'search_pages.user_id']),
        sa.CheckConstraint("image_state IN ('active','expired')", name='search_page_image_state'))
    submissions = sa.Table('search_submissions', metadata,
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('page_id', sa.Text, nullable=False),
        sa.Column('problem_id', UUID(as_uuid=True), sa.ForeignKey('search_problems.id')),
        sa.Column('client_request_id', sa.Text),
        sa.Column('crop_box', JSONB, nullable=False),
        sa.Column('storage_key', sa.Text, nullable=False, unique=True),
        sa.Column('crop_sha256', sa.Text, nullable=False),
        sa.Column('original_sha256', sa.Text, nullable=False),
        sa.Column('width', sa.Integer, nullable=False),
        sa.Column('height', sa.Integer, nullable=False),
        sa.Column('recognition_status', sa.Text, nullable=False, server_default='queued'),
        sa.Column('lesson_status', sa.Text, nullable=False, server_default='not_started'),
        sa.Column('artifact_state', sa.Text, nullable=False, server_default='active'),
        sa.Column('error_code', sa.Text),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('user_id', 'client_request_id'),
        sa.ForeignKeyConstraint(['page_id', 'user_id'], ['search_pages.id', 'search_pages.user_id']),
        sa.CheckConstraint("recognition_status IN ('queued','running','reviewed','needs_confirmation','failed','interrupted')", name='search_recognition_status'),
        sa.CheckConstraint("lesson_status IN ('not_started','running','ready','unsupported','failed','interrupted','expired')", name='search_lesson_status'),
        sa.CheckConstraint("artifact_state IN ('active','expired')", name='search_artifact_state'))
    relations = sa.Table('student_search_problems', metadata,
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id'), primary_key=True),
        sa.Column('problem_id', UUID(as_uuid=True), sa.ForeignKey('search_problems.id'), primary_key=True),
        sa.Column('first_searched_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_searched_at', sa.DateTime(timezone=True), nullable=False))
    sa.Index('ix_search_pages_expiry', pages.c.expires_at)
    sa.Index('ix_search_pages_owner', pages.c.user_id, pages.c.id)
    sa.Index('ix_search_submissions_owner_problem', submissions.c.user_id, submissions.c.problem_id, submissions.c.created_at)
    sa.Index('ix_search_submissions_page', submissions.c.page_id, submissions.c.user_id)
    sa.Index('ix_search_submissions_expiry', submissions.c.expires_at)
    sa.Index('ix_student_search_recent', relations.c.user_id, relations.c.last_searched_at.desc())
    return problems, pages, submissions, relations
