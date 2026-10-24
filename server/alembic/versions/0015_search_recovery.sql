CREATE TABLE search_recovery_state (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    authority_id uuid NOT NULL,
    initialized boolean NOT NULL DEFAULT false,
    sequence bigint NOT NULL DEFAULT 0 CHECK (sequence >= 0),
    replayed_sequence bigint NOT NULL DEFAULT 0 CHECK (replayed_sequence >= 0 AND replayed_sequence <= sequence),
    digest text NOT NULL DEFAULT ''
);
INSERT INTO search_recovery_state (authority_id) VALUES (gen_random_uuid());
