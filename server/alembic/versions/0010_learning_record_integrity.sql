ALTER TABLE knowledge_nodes ADD COLUMN is_active boolean NOT NULL DEFAULT true;

ALTER TABLE student_practice_events ADD COLUMN displayed_at timestamptz;
UPDATE student_practice_events
SET displayed_at = (payload->>'displayed_at')::timestamptz,
    payload = payload - 'displayed_at'
WHERE payload ? 'displayed_at';
ALTER TABLE student_practice_events ADD CONSTRAINT ck_practice_event_display
    CHECK (displayed_at IS NULL OR event_type = 'hint'
        OR (event_type = 'message' AND coalesce(payload->>'role' = 'tutor', false)));

-- Revoke the former payload permission even when Alembic is run directly.
REVOKE UPDATE ON student_practice_events FROM product_app;
REVOKE UPDATE (payload) ON student_practice_events FROM product_app;
GRANT UPDATE (displayed_at) ON student_practice_events TO product_app;
