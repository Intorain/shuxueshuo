CREATE TABLE search_admission_control (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    generation_enabled boolean NOT NULL DEFAULT false,
    updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO search_admission_control (singleton) VALUES (true);

CREATE TABLE search_admission_tickets (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users(id),
    search_id text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('generation','rerun','continuation')),
    request_id text,
    quota_day date NOT NULL,
    accepted_at timestamptz NOT NULL,
    state text NOT NULL CHECK (state IN ('reserved','running','finished','cancelled','interrupted')),
    consumed boolean NOT NULL DEFAULT false,
    started_at timestamptz,
    finished_at timestamptz,
    error_code text,
    UNIQUE (user_id, kind, request_id),
    CHECK (NOT consumed OR (kind IN ('generation','rerun') AND started_at IS NOT NULL)),
    CHECK (state != 'reserved' OR (NOT consumed AND started_at IS NULL AND finished_at IS NULL)),
    CHECK (state NOT IN ('running','finished','interrupted') OR started_at IS NOT NULL),
    CHECK (state NOT IN ('finished','cancelled','interrupted') OR finished_at IS NOT NULL)
);
CREATE INDEX ix_search_admission_active ON search_admission_tickets (state,user_id)
    WHERE state IN ('reserved','running');
CREATE INDEX ix_search_admission_daily ON search_admission_tickets (quota_day,kind,user_id)
    WHERE consumed OR state = 'reserved';
CREATE INDEX ix_search_admission_submission ON search_admission_tickets (search_id)
    WHERE state = 'reserved';
