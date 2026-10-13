-- Existing installations must use the explicit local rebuild command. Ordinary
-- migration is never authorization to discard public identities or student data.
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM knowledge_nodes) OR EXISTS(SELECT 1 FROM student_practice_attempts)
    OR EXISTS(SELECT 1 FROM knowledge_drill_attempts) THEN
  RAISE EXCEPTION 'learning.rebuild_required: legacy learning content exists; run the explicit local rebuild-learning command';
 END IF;
END $$;

ALTER TABLE knowledge_nodes DROP CONSTRAINT knowledge_nodes_kind_check;
ALTER TABLE knowledge_nodes ADD CONSTRAINT knowledge_nodes_kind_check
 CHECK(kind IN ('textbook','chapter','section','knowledge','skill','method','problem_type','judgment_rule'));
ALTER TABLE knowledge_nodes ADD CONSTRAINT knowledge_nodes_subtype_check
 CHECK((kind='judgment_rule' AND subtype IS NOT NULL AND subtype IN ('method_selection','step_selection'))
       OR (kind<>'judgment_rule' AND subtype IS NULL));
ALTER TABLE knowledge_nodes ADD COLUMN aliases jsonb NOT NULL DEFAULT '[]' CHECK(jsonb_typeof(aliases)='array');
ALTER TABLE knowledge_nodes ADD COLUMN body jsonb NOT NULL DEFAULT '{}' CHECK(jsonb_typeof(body)='object');
CREATE TABLE knowledge_entries (
 node_id text NOT NULL REFERENCES knowledge_nodes(id), entry_id text NOT NULL,
 entry_type text NOT NULL CHECK(entry_type IN ('entry','operation','step','branch')),
 title text NOT NULL, position integer NOT NULL CHECK(position>=0),
 body jsonb NOT NULL CHECK(jsonb_typeof(body)='object'), is_active boolean NOT NULL DEFAULT true,
 PRIMARY KEY(node_id,entry_id)
);
ALTER TABLE knowledge_edges DROP CONSTRAINT knowledge_edges_relation_type_check;
ALTER TABLE knowledge_edges ADD CONSTRAINT knowledge_edges_relation_type_check
 CHECK(relation_type IN ('contains','extends','prerequisite','involves','candidate','method_rule','calls','step_rule','selects','uses'));
ALTER TABLE knowledge_edges ADD COLUMN occurrences jsonb NOT NULL DEFAULT '[]' CHECK(jsonb_typeof(occurrences)='array');
CREATE TABLE knowledge_resources (
 id text PRIMARY KEY, body jsonb NOT NULL CHECK(jsonb_typeof(body)='object'),
 version text NOT NULL, is_active boolean NOT NULL DEFAULT true
);
CREATE TABLE learning_content_releases (
 content_version text PRIMARY KEY, schema_version integer NOT NULL CHECK(schema_version=2),
 counts jsonb NOT NULL CHECK(jsonb_typeof(counts)='object'), published_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE learning_content_current (
 id text PRIMARY KEY CHECK(id='public'), content_version text NOT NULL REFERENCES learning_content_releases(content_version)
);
ALTER TABLE practice_topics ADD COLUMN body jsonb NOT NULL DEFAULT '{}';
ALTER TABLE practice_topics ADD COLUMN groups jsonb NOT NULL DEFAULT '[]';
ALTER TABLE practice_topics ADD COLUMN is_active boolean NOT NULL DEFAULT true;
ALTER TABLE practice_topic_problems ADD COLUMN position integer NOT NULL DEFAULT 0 CHECK(position>=0);
ALTER TABLE practice_problems ADD COLUMN contract_hash text NOT NULL DEFAULT '';
ALTER TABLE practice_problems ADD COLUMN association_hash text NOT NULL DEFAULT '';
CREATE TABLE practice_problem_types (
 problem_id text NOT NULL REFERENCES practice_problems(id), node_id text NOT NULL REFERENCES knowledge_nodes(id),
 PRIMARY KEY(problem_id,node_id)
);
CREATE TABLE practice_routes (
 problem_id text NOT NULL REFERENCES practice_problems(id), route_id text NOT NULL, label text NOT NULL,
 methods jsonb NOT NULL, association_hash text NOT NULL, is_active boolean NOT NULL DEFAULT true,
 PRIMARY KEY(problem_id,route_id)
);
ALTER TABLE practice_steps DROP CONSTRAINT practice_steps_problem_id_route_id_fkey;
ALTER TABLE student_practice_attempts DROP CONSTRAINT student_practice_attempts_problem_id_route_id_fkey;
DROP TABLE practice_problem_methods;
ALTER TABLE practice_steps ADD FOREIGN KEY(problem_id,route_id) REFERENCES practice_routes(problem_id,route_id);
ALTER TABLE student_practice_attempts ADD FOREIGN KEY(problem_id,route_id) REFERENCES practice_routes(problem_id,route_id);
ALTER TABLE practice_steps ADD COLUMN refs jsonb NOT NULL DEFAULT '[]';
ALTER TABLE practice_steps ADD COLUMN tip jsonb;
ALTER TABLE practice_steps ADD COLUMN reason text;
ALTER TABLE practice_steps ADD COLUMN is_active boolean NOT NULL DEFAULT true;
ALTER TABLE student_practice_attempts ADD COLUMN content_version text NOT NULL REFERENCES learning_content_releases(content_version);
ALTER TABLE student_practice_attempts ADD COLUMN association_hash text NOT NULL;
ALTER TABLE student_practice_attempts ADD COLUMN association_snapshot jsonb NOT NULL DEFAULT '{}' CHECK(jsonb_typeof(association_snapshot)='object');
ALTER TABLE knowledge_drill_items DROP CONSTRAINT knowledge_drill_items_pkey;
ALTER TABLE knowledge_drill_items ADD PRIMARY KEY(item_id);
ALTER TABLE knowledge_drill_items ADD COLUMN entry_id text;
ALTER TABLE knowledge_drill_items ADD FOREIGN KEY(node_id,entry_id) REFERENCES knowledge_entries(node_id,entry_id);
ALTER TABLE knowledge_drill_items ADD COLUMN origin jsonb NOT NULL DEFAULT '{}';
ALTER TABLE knowledge_drill_items ADD COLUMN content_hash text NOT NULL;
CREATE INDEX ix_drill_active_node ON knowledge_drill_items(node_id,item_id) WHERE is_active;
ALTER TABLE knowledge_drill_attempts ADD COLUMN content_version text NOT NULL REFERENCES learning_content_releases(content_version);
ALTER TABLE knowledge_drill_attempts ADD COLUMN association_hash text NOT NULL;
ALTER TABLE knowledge_drill_answers ADD COLUMN node_id text NOT NULL REFERENCES knowledge_nodes(id);
ALTER TABLE knowledge_drill_answers ADD COLUMN entry_id text;
ALTER TABLE knowledge_drill_answers ADD FOREIGN KEY(node_id,entry_id) REFERENCES knowledge_entries(node_id,entry_id);
ALTER TABLE knowledge_drill_answers ADD COLUMN content_hash text NOT NULL;
ALTER TABLE knowledge_drill_answers ADD COLUMN item_snapshot jsonb NOT NULL DEFAULT '{}' CHECK(jsonb_typeof(item_snapshot)='object');
CREATE INDEX ix_drill_answer_evidence ON knowledge_drill_answers(node_id,answered_at,attempt_id) WHERE answered_at IS NOT NULL;
CREATE TABLE student_node_assessments (
 user_id uuid NOT NULL REFERENCES users(id), node_id text NOT NULL REFERENCES knowledge_nodes(id),
 status text NOT NULL CHECK(status IN ('unassessed','mastered','needs_review')),
 probability double precision CHECK(probability>=0 AND probability<=1), strategy_version text NOT NULL,
 evidence_attempt_id uuid REFERENCES knowledge_drill_attempts(id), evidence_position bigint NOT NULL CHECK(evidence_position>=0),
 correct_count integer CHECK(correct_count BETWEEN 0 AND 5), evaluated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(user_id,node_id)
);
