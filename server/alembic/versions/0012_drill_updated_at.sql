ALTER TABLE knowledge_drill_attempts ADD COLUMN updated_at timestamptz;

-- Historical closed rounds have no recorded closure time. Use the latest
-- recorded activity, rather than inventing a closure timestamp during migration.
UPDATE knowledge_drill_attempts a SET updated_at = greatest(
 a.started_at, a.completed_at,
 (SELECT max(r.answered_at) FROM knowledge_drill_answers r WHERE r.attempt_id=a.id)
);

ALTER TABLE knowledge_drill_attempts ALTER COLUMN updated_at SET NOT NULL;
ALTER TABLE knowledge_drill_attempts ALTER COLUMN updated_at SET DEFAULT clock_timestamp();
