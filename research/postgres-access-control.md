# PostgreSQL: read-only user

https://ducklake.select/docs/stable/duckdb/guides/access_control#access-control-with-s3-and-postgresql

## 1. Create the reader user

SSH into the server and switch to the postgres user:

```bash
ssh ducklake-guard
su - postgres
```

Create the user and grant read-only access:

```sql
psql -d ducklake_catalog -c "
CREATE USER reader WITH PASSWORD 'simple';
GRANT SELECT ON ALL TABLES IN SCHEMA public TO reader;
"
```

## 2. Allow remote connections to ducklake_catalog

Ensure `pg_hba.conf` has the following line to allow all users to connect to `ducklake_catalog`:

```
host    ducklake_catalog    all    0.0.0.0/0    scram-sha-256
```

Reload the configuration:

```sql
psql -c "SELECT pg_reload_conf();"
```

## Test

```bash
set -a && source .env && set +a && duckdb -init init-reader.sql
```

Writing to the catalog should fail:

```sql
CREATE TABLE ducklake.test (id INTEGER);
-- Expected: permission error from PostgreSQL reader user
```
