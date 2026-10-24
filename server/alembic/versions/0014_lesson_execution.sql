CREATE TABLE lesson_runs (
	run_id TEXT NOT NULL,
	submission_id TEXT,
	identity JSONB NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_lesson_runs PRIMARY KEY (run_id),
	CONSTRAINT fk_lesson_runs_submission_id_search_submissions FOREIGN KEY(submission_id) REFERENCES search_submissions (id) ON DELETE CASCADE
);

CREATE TABLE lesson_calculation_attempts (
	run_id TEXT NOT NULL,
	attempt_id TEXT NOT NULL,
	target TEXT NOT NULL,
	route TEXT NOT NULL,
	bucket TEXT NOT NULL,
	operation_key TEXT NOT NULL,
	input_hash TEXT NOT NULL,
	ordinal BIGINT NOT NULL,
	owner TEXT NOT NULL,
	status TEXT NOT NULL,
	allowance_seconds DOUBLE PRECISION NOT NULL,
	elapsed_seconds DOUBLE PRECISION NOT NULL,
	reserved_upper_seconds DOUBLE PRECISION NOT NULL,
	receipt TEXT,
	sequence BIGINT GENERATED ALWAYS AS IDENTITY,
	CONSTRAINT pk_lesson_calculation_attempts PRIMARY KEY (run_id, attempt_id),
	CONSTRAINT uq_lesson_calculation_attempts_run_id UNIQUE (run_id, target, route, bucket, operation_key, ordinal),
	CONSTRAINT fk_lesson_calculation_attempts_run_id_lesson_runs FOREIGN KEY(run_id) REFERENCES lesson_runs (run_id) ON DELETE CASCADE
);

CREATE TABLE lesson_calculation_budgets (
	run_id TEXT NOT NULL,
	target TEXT NOT NULL,
	route TEXT NOT NULL,
	bucket TEXT NOT NULL,
	limit_seconds DOUBLE PRECISION NOT NULL,
	initial_seconds DOUBLE PRECISION NOT NULL,
	CONSTRAINT pk_lesson_calculation_budgets PRIMARY KEY (run_id, target, route, bucket),
	CONSTRAINT fk_lesson_calculation_budgets_run_id_lesson_runs FOREIGN KEY(run_id) REFERENCES lesson_runs (run_id) ON DELETE CASCADE
);

CREATE TABLE lesson_calculation_leases (
	run_id TEXT NOT NULL,
	target TEXT NOT NULL,
	route TEXT NOT NULL,
	owner TEXT NOT NULL,
	pid BIGINT NOT NULL,
	acquired_at DOUBLE PRECISION NOT NULL,
	released INTEGER NOT NULL,
	CONSTRAINT pk_lesson_calculation_leases PRIMARY KEY (run_id, target, route),
	CONSTRAINT fk_lesson_calculation_leases_run_id_lesson_runs FOREIGN KEY(run_id) REFERENCES lesson_runs (run_id) ON DELETE CASCADE
);

CREATE TABLE lesson_checkpoints (
	run_id TEXT NOT NULL,
	target TEXT NOT NULL,
	route TEXT NOT NULL,
	value TEXT NOT NULL,
	CONSTRAINT pk_lesson_checkpoints PRIMARY KEY (run_id, target, route),
	CONSTRAINT fk_lesson_checkpoints_run_id_lesson_runs FOREIGN KEY(run_id) REFERENCES lesson_runs (run_id) ON DELETE CASCADE
);

CREATE TABLE lesson_commits (
	run_id TEXT NOT NULL,
	id TEXT NOT NULL,
	digest TEXT NOT NULL,
	result TEXT NOT NULL,
	sequence BIGINT GENERATED ALWAYS AS IDENTITY,
	CONSTRAINT pk_lesson_commits PRIMARY KEY (run_id, id),
	CONSTRAINT fk_lesson_commits_run_id_lesson_runs FOREIGN KEY(run_id) REFERENCES lesson_runs (run_id) ON DELETE CASCADE
);

CREATE TABLE lesson_events (
	run_id TEXT NOT NULL,
	seq BIGINT NOT NULL,
	value TEXT NOT NULL,
	CONSTRAINT pk_lesson_events PRIMARY KEY (run_id, seq),
	CONSTRAINT fk_lesson_events_run_id_lesson_runs FOREIGN KEY(run_id) REFERENCES lesson_runs (run_id) ON DELETE CASCADE
);

CREATE TABLE lesson_goals (
	run_id TEXT NOT NULL,
	target TEXT NOT NULL,
	value TEXT NOT NULL,
	CONSTRAINT pk_lesson_goals PRIMARY KEY (run_id, target),
	CONSTRAINT fk_lesson_goals_run_id_lesson_runs FOREIGN KEY(run_id) REFERENCES lesson_runs (run_id) ON DELETE CASCADE
);

CREATE TABLE lesson_handoffs (
	run_id TEXT NOT NULL,
	target TEXT NOT NULL,
	route TEXT NOT NULL,
	value TEXT NOT NULL,
	CONSTRAINT pk_lesson_handoffs PRIMARY KEY (run_id, target, route),
	CONSTRAINT fk_lesson_handoffs_run_id_lesson_runs FOREIGN KEY(run_id) REFERENCES lesson_runs (run_id) ON DELETE CASCADE
);

CREATE TABLE lesson_interaction_states (
	run_id TEXT NOT NULL,
	target TEXT NOT NULL,
	route TEXT NOT NULL,
	step TEXT NOT NULL,
	ordinal BIGINT NOT NULL,
	hash TEXT NOT NULL,
	status TEXT NOT NULL,
	interaction_id TEXT,
	CONSTRAINT pk_lesson_interaction_states PRIMARY KEY (run_id, target, route, step),
	CONSTRAINT fk_lesson_interaction_states_run_id_lesson_runs FOREIGN KEY(run_id) REFERENCES lesson_runs (run_id) ON DELETE CASCADE
);

CREATE TABLE lesson_interactions (
	run_id TEXT NOT NULL,
	interaction_id TEXT NOT NULL,
	target TEXT NOT NULL,
	route TEXT NOT NULL,
	ordinal BIGINT NOT NULL,
	value TEXT NOT NULL,
	CONSTRAINT pk_lesson_interactions PRIMARY KEY (run_id, interaction_id),
	CONSTRAINT fk_lesson_interactions_run_id_lesson_runs FOREIGN KEY(run_id) REFERENCES lesson_runs (run_id) ON DELETE CASCADE
);

CREATE TABLE lesson_metadata (
	run_id TEXT NOT NULL,
	key TEXT NOT NULL,
	value TEXT NOT NULL,
	CONSTRAINT pk_lesson_metadata PRIMARY KEY (run_id, key),
	CONSTRAINT fk_lesson_metadata_run_id_lesson_runs FOREIGN KEY(run_id) REFERENCES lesson_runs (run_id) ON DELETE CASCADE
);

CREATE TABLE lesson_qa (
	run_id TEXT NOT NULL,
	target TEXT NOT NULL,
	route TEXT NOT NULL,
	step TEXT NOT NULL,
	value TEXT NOT NULL,
	CONSTRAINT pk_lesson_qa PRIMARY KEY (run_id, target, route, step),
	CONSTRAINT fk_lesson_qa_run_id_lesson_runs FOREIGN KEY(run_id) REFERENCES lesson_runs (run_id) ON DELETE CASCADE
);

CREATE TABLE lesson_selection_chunks (
	run_id TEXT NOT NULL,
	target TEXT NOT NULL,
	kind TEXT NOT NULL,
	seq BIGINT NOT NULL,
	value TEXT NOT NULL,
	CONSTRAINT pk_lesson_selection_chunks PRIMARY KEY (run_id, target, kind),
	CONSTRAINT fk_lesson_selection_chunks_run_id_lesson_runs FOREIGN KEY(run_id) REFERENCES lesson_runs (run_id) ON DELETE CASCADE
);

CREATE TABLE lesson_step_summaries (
	run_id TEXT NOT NULL,
	target TEXT NOT NULL,
	route TEXT NOT NULL,
	step TEXT NOT NULL,
	ordinal BIGINT NOT NULL,
	hash TEXT NOT NULL,
	CONSTRAINT pk_lesson_step_summaries PRIMARY KEY (run_id, target, route, step),
	CONSTRAINT uq_lesson_step_summaries_run_id UNIQUE (run_id, target, route, ordinal),
	CONSTRAINT fk_lesson_step_summaries_run_id_lesson_runs FOREIGN KEY(run_id) REFERENCES lesson_runs (run_id) ON DELETE CASCADE
);

CREATE TABLE lesson_steps (
	run_id TEXT NOT NULL,
	target TEXT NOT NULL,
	route TEXT NOT NULL,
	step TEXT NOT NULL,
	ordinal BIGINT NOT NULL,
	value TEXT NOT NULL,
	CONSTRAINT pk_lesson_steps PRIMARY KEY (run_id, target, route, step),
	CONSTRAINT uq_lesson_steps_run_id UNIQUE (run_id, target, route, ordinal),
	CONSTRAINT fk_lesson_steps_run_id_lesson_runs FOREIGN KEY(run_id) REFERENCES lesson_runs (run_id) ON DELETE CASCADE
);

CREATE INDEX ix_lesson_runs_submission ON lesson_runs (submission_id);
