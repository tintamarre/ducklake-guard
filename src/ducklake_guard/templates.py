from __future__ import annotations

import string

INIT_SQL = string.Template("""\
INSTALL ducklake;
INSTALL postgres;

CREATE OR REPLACE SECRET s3_secret (
    TYPE s3,
    PROVIDER config,
    ENDPOINT getenv('S3_ENDPOINT'),
    KEY_ID getenv('S3_ACCESS_KEY'),
    SECRET getenv('S3_SECRET_KEY'),
    REGION getenv('S3_REGION'),
    URL_STYLE 'path',
    USE_SSL CAST(getenv('S3_USE_SSL') AS BOOLEAN)
);

CREATE OR REPLACE SECRET postgres_secret (
    TYPE postgres,
    HOST getenv('POSTGRES_HOST'),
    PORT 5432,
    DATABASE ducklake_catalog,
    USER 'dga_$name',
    PASSWORD getenv('DGA_CATALOG_PASSWORD')
);

CREATE SECRET ducklake_secret (
    TYPE ducklake,
    METADATA_PATH '',
    DATA_PATH getenv('S3_DATA_PATH'),
    METADATA_PARAMETERS MAP {'TYPE': 'postgres', 'SECRET': 'postgres_secret'}
);

ATTACH 'ducklake:ducklake_secret' AS ducklake;
USE ducklake;
SELECT 'Connected as $name' as status;
""")

PG_HBA_PATH = "/etc/postgresql/16/main/pg_hba.conf"
PG_HBA_LINE = (
    "host    ducklake_guard            ducklake         0.0.0.0/0          md5"
)

SERVER_INIT_SQL = """\
SELECT 'CREATE DATABASE ducklake_guard OWNER ducklake'
WHERE NOT EXISTS (
    SELECT 1 FROM pg_database WHERE datname = 'ducklake_guard'
) \\gexec

\\c ducklake_guard

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'permission_type') THEN
        CREATE TYPE permission_type AS ENUM ('read_only', 'read_write');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'log_action') THEN
        CREATE TYPE log_action AS ENUM ('create', 'delete', 'allow', 'deny', 'sync');
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS users (
    name          TEXT PRIMARY KEY,
    access_key    TEXT NOT NULL UNIQUE,
    project_id    TEXT NOT NULL,
    principal_arn TEXT GENERATED ALWAYS AS
        ('arn:aws:iam:::user/p' || project_id
         || ':' || access_key) STORED,
    created_at    TIMESTAMPTZ DEFAULT now(),
    created_by    TEXT
);

CREATE TABLE IF NOT EXISTS grants (
    user_name   TEXT REFERENCES users(name)
                ON DELETE CASCADE,
    table_name  TEXT NOT NULL,
    permission  permission_type NOT NULL,
    granted_at  TIMESTAMPTZ DEFAULT now(),
    granted_by  TEXT,
    PRIMARY KEY (user_name, table_name)
);

CREATE TABLE IF NOT EXISTS policy_log (
    id         SERIAL PRIMARY KEY,
    user_name  TEXT,
    action     log_action NOT NULL,
    detail     JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_policy_log_user_name ON policy_log (user_name);
CREATE INDEX IF NOT EXISTS idx_policy_log_created_at ON policy_log (created_at);

GRANT ALL ON ALL TABLES IN SCHEMA public TO ducklake;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO ducklake;

\\c ducklake_catalog
ALTER ROLE ducklake CREATEROLE;
ALTER TABLE ducklake_table ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS admin_all ON ducklake_table;
CREATE POLICY admin_all ON ducklake_table FOR SELECT TO ducklake USING (true);
"""
