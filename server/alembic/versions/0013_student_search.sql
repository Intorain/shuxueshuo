CREATE TABLE search_problems (
    id uuid PRIMARY KEY,
    identity_version integer NOT NULL,
    fingerprint text NOT NULL,
    identity_json jsonb NOT NULL,
    statement text NOT NULL,
    structured_problem jsonb NOT NULL,
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled')),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (identity_version, fingerprint)
);
CREATE TABLE search_pages (
    id text PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users(id),
    parent_page_id text,
    root_page_id text NOT NULL,
    storage_key text NOT NULL UNIQUE,
    sha256 text NOT NULL,
    width integer NOT NULL,
    height integer NOT NULL,
    metadata jsonb NOT NULL,
    image_state text NOT NULL DEFAULT 'active' CHECK (image_state IN ('active','expired')),
    pending_cleanup_keys jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    UNIQUE (id, user_id),
    FOREIGN KEY (parent_page_id, user_id) REFERENCES search_pages(id, user_id)
);
CREATE TABLE search_submissions (
    id text PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users(id),
    page_id text NOT NULL,
    problem_id uuid REFERENCES search_problems(id),
    client_request_id text,
    crop_box jsonb NOT NULL,
    storage_key text NOT NULL UNIQUE,
    crop_sha256 text NOT NULL,
    original_sha256 text NOT NULL,
    width integer NOT NULL,
    height integer NOT NULL,
    recognition_status text NOT NULL DEFAULT 'queued' CHECK (recognition_status IN ('queued','running','reviewed','needs_confirmation','failed','interrupted')),
    lesson_status text NOT NULL DEFAULT 'not_started' CHECK (lesson_status IN ('not_started','running','ready','unsupported','failed','interrupted','expired')),
    artifact_state text NOT NULL DEFAULT 'active' CHECK (artifact_state IN ('active','expired')),
    error_code text,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    UNIQUE (user_id, client_request_id),
    FOREIGN KEY (page_id, user_id) REFERENCES search_pages(id, user_id)
);
CREATE TABLE student_search_problems (
    user_id uuid NOT NULL REFERENCES users(id),
    problem_id uuid NOT NULL REFERENCES search_problems(id),
    first_searched_at timestamptz NOT NULL,
    last_searched_at timestamptz NOT NULL,
    PRIMARY KEY (user_id, problem_id)
);
CREATE INDEX ix_search_pages_expiry ON search_pages(expires_at);
CREATE INDEX ix_search_pages_owner ON search_pages(user_id, id);
CREATE INDEX ix_search_submissions_owner_problem ON search_submissions(user_id, problem_id, created_at);
CREATE INDEX ix_search_submissions_page ON search_submissions(page_id, user_id);
CREATE INDEX ix_search_submissions_expiry ON search_submissions(expires_at);
CREATE INDEX ix_student_search_recent ON student_search_problems(user_id, last_searched_at DESC);
CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON search_problems
FOR EACH ROW EXECUTE FUNCTION product_immutable('status');
