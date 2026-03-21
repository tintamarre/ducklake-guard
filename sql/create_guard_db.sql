CREATE DATABASE ducklake_guard;

\c ducklake_guard

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'permission_type') THEN
        CREATE TYPE permission_type AS ENUM ('read_only', 'read_write');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'log_action') THEN
        CREATE TYPE log_action AS ENUM ('create', 'delete', 'allow', 'deny', 'sync');
    END IF;
END $$;

CREATE TABLE users (
    name            TEXT PRIMARY KEY,
    access_key      TEXT NOT NULL UNIQUE,
    project_id      TEXT NOT NULL,
    principal_arn   TEXT GENERATED ALWAYS AS
                      ('arn:aws:iam:::user/p' || project_id || ':' || access_key) STORED,
    created_at      TIMESTAMPTZ DEFAULT now(),
    created_by      TEXT
);

CREATE TABLE grants (
    user_name       TEXT REFERENCES users(name) ON DELETE CASCADE,
    table_name      TEXT NOT NULL,
    permission      permission_type NOT NULL,
    granted_at      TIMESTAMPTZ DEFAULT now(),
    granted_by      TEXT,
    PRIMARY KEY (user_name, table_name)
);

CREATE TABLE policy_log (
    id              SERIAL PRIMARY KEY,
    user_name       TEXT,
    action          log_action NOT NULL,
    detail          JSONB,
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_policy_log_user_name ON policy_log (user_name);
CREATE INDEX idx_policy_log_created_at ON policy_log (created_at);
