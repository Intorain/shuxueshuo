CREATE TABLE knowledge_nodes (
 id text PRIMARY KEY, label text NOT NULL, kind text NOT NULL CHECK(kind IN ('knowledge','method')),
 subtype text, summary text NOT NULL, explanation_md text NOT NULL, sheet text
);
CREATE TABLE knowledge_edges (
 source_id text NOT NULL REFERENCES knowledge_nodes(id), target_id text NOT NULL REFERENCES knowledge_nodes(id),
 relation_type text NOT NULL CHECK(relation_type IN ('uses','prerequisite')),
 PRIMARY KEY(source_id,target_id,relation_type), CHECK(source_id<>target_id)
);
CREATE TABLE practice_topics (id text PRIMARY KEY, label text NOT NULL, path text NOT NULL);
CREATE TABLE practice_problems (
 id text PRIMARY KEY, label text NOT NULL, path text NOT NULL, lesson_file text NOT NULL,
 statement_md text NOT NULL, problem_data jsonb NOT NULL, is_active boolean NOT NULL DEFAULT true
);
CREATE TABLE practice_topic_problems (
 topic_id text REFERENCES practice_topics(id), problem_id text REFERENCES practice_problems(id), PRIMARY KEY(topic_id,problem_id)
);
CREATE TABLE practice_problem_methods (
 problem_id text REFERENCES practice_problems(id), route_id text NOT NULL,
 method_node_id text NOT NULL REFERENCES knowledge_nodes(id), PRIMARY KEY(problem_id,route_id)
);
CREATE TABLE practice_steps (
 problem_id text NOT NULL, route_id text NOT NULL, step_id text NOT NULL, title text NOT NULL,
 position integer NOT NULL CHECK(position>=0), PRIMARY KEY(problem_id,route_id,step_id),
 UNIQUE(problem_id,route_id,position), FOREIGN KEY(problem_id,route_id) REFERENCES practice_problem_methods(problem_id,route_id)
);
CREATE TABLE practice_step_nodes (
 problem_id text NOT NULL, route_id text NOT NULL, step_id text NOT NULL, node_id text REFERENCES knowledge_nodes(id),
 PRIMARY KEY(problem_id,route_id,step_id,node_id),
 FOREIGN KEY(problem_id,route_id,step_id) REFERENCES practice_steps(problem_id,route_id,step_id)
);
CREATE TABLE knowledge_drill_items (
 node_id text REFERENCES knowledge_nodes(id), item_id text NOT NULL, statement_md text NOT NULL,
 question_type text NOT NULL CHECK(question_type IN ('choice','multi','boolean','fill')),
 options jsonb, answer_spec jsonb NOT NULL, explanation_md text NOT NULL, is_active boolean NOT NULL DEFAULT true,
 PRIMARY KEY(node_id,item_id)
);
CREATE TABLE knowledge_drill_attempts (
 id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES users(id), node_id text NOT NULL REFERENCES knowledge_nodes(id),
 status text NOT NULL DEFAULT 'in_progress' CHECK(status IN ('in_progress','completed','closed')),
 started_at timestamptz NOT NULL DEFAULT clock_timestamp(), completed_at timestamptz,
 CHECK((status='completed')=(completed_at IS NOT NULL)), CHECK(completed_at IS NULL OR completed_at>=started_at)
);
CREATE UNIQUE INDEX uq_knowledge_drill_active ON knowledge_drill_attempts(user_id,node_id) WHERE status='in_progress';
CREATE INDEX ix_knowledge_drill_latest_completed ON knowledge_drill_attempts(user_id,node_id,completed_at DESC,id DESC) WHERE status='completed';
CREATE TABLE knowledge_drill_answers (
 attempt_id uuid REFERENCES knowledge_drill_attempts(id), position integer CHECK(position BETWEEN 1 AND 5),
 item_id text NOT NULL, selected jsonb, is_correct boolean, answered_at timestamptz,
 PRIMARY KEY(attempt_id,position), UNIQUE(attempt_id,item_id),
 CHECK((answered_at IS NULL)=(is_correct IS NULL)), CHECK(answered_at IS NOT NULL OR selected IS NULL),
 CHECK(selected IS NULL OR jsonb_typeof(selected)='array')
);
CREATE TABLE student_practice_attempts (
 id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES users(id), problem_id text NOT NULL, route_id text NOT NULL,
 problem_context jsonb NOT NULL, status text NOT NULL DEFAULT 'in_progress' CHECK(status IN ('in_progress','completed','closed')),
 started_at timestamptz NOT NULL DEFAULT clock_timestamp(), updated_at timestamptz NOT NULL DEFAULT clock_timestamp(), completed_at timestamptz,
 FOREIGN KEY(problem_id,route_id) REFERENCES practice_problem_methods(problem_id,route_id),
 CHECK((status='completed')=(completed_at IS NOT NULL)), CHECK(completed_at IS NULL OR completed_at>=started_at)
);
CREATE UNIQUE INDEX uq_student_practice_active ON student_practice_attempts(user_id,problem_id) WHERE status='in_progress';
CREATE INDEX ix_student_practice_history ON student_practice_attempts(user_id,started_at DESC);
CREATE INDEX ix_student_practice_problem_history ON student_practice_attempts(user_id,problem_id,started_at DESC);
CREATE TABLE student_practice_events (
 id uuid PRIMARY KEY, attempt_id uuid NOT NULL REFERENCES student_practice_attempts(id), step_id text NOT NULL,
 sequence bigint NOT NULL CHECK(sequence>0), event_type text NOT NULL CHECK(event_type IN ('context','answer','grade','hint','message')),
 related_event_id uuid REFERENCES student_practice_events(id), payload jsonb NOT NULL CHECK(jsonb_typeof(payload)='object'),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(), UNIQUE(attempt_id,sequence)
);
CREATE INDEX ix_student_practice_step_events ON student_practice_events(attempt_id,step_id,sequence);
CREATE TABLE student_step_results (
 attempt_id uuid REFERENCES student_practice_attempts(id), step_id text NOT NULL, passed boolean NOT NULL DEFAULT false,
 submit_count integer NOT NULL DEFAULT 0, wrong_count integer NOT NULL DEFAULT 0,
 hint_used boolean NOT NULL DEFAULT false, last_grading_source text CHECK(last_grading_source IN ('rule','llm')),
 last_submitted_at timestamptz, summary_through_sequence bigint NOT NULL DEFAULT 0,
 PRIMARY KEY(attempt_id,step_id), CHECK(wrong_count>=0 AND submit_count>=wrong_count)
);
