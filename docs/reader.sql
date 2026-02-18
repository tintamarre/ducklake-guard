-- Reader only (configure on Psql)
CREATE USER ducklake_reader WITH PASSWORD 'simple';
GRANT SELECT ON ALL TABLES IN SCHEMA main TO ducklake_reader;

-- 