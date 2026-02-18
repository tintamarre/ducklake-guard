# ducklake-guard

Explores access control for [DuckLake](https://ducklake.select) lakehouses — restricting a reader to read-only access on specific tables across the Postgres catalog and S3 data layer.

## Setup

```bash
cp .env.sample .env
# Fill in credentials — see comments in .env.sample
```

## 1. Load sample data

Generates TPC-H tables (scale factor 0.01) and loads them into the lakehouse.

```bash
set -a && source .env && set +a
uv run python scripts/load_sample_data.py
```

## 2. Apply granular read-only policies

### PostgreSQL catalog

Create a read-only Postgres user that can query the DuckLake metadata catalog but not modify it. See [research/postgres-access-control.md](research/postgres-access-control.md) for the full walkthrough, or apply the SQL directly:

```bash
ssh ducklake-guard
su - postgres
psql -d ducklake_catalog -f sql/create_reader.sql
```

### S3 data layer

Restrict an S3 reader key to `GetObject` on a single table prefix. See [research/s3-access-control.md](research/s3-access-control.md) for how the bucket policy works.

```bash
set -a && source .env && set +a
READER_TABLE=customer uv run python scripts/apply_s3_reader_policy.py
```

## 3. Verify

Connect as the reader and confirm the restrictions:

```bash
set -a && source .env && set +a && duckdb -init init-reader.sql
```

```sql
-- Should succeed
SELECT * FROM customer LIMIT 10;

-- Should fail (HTTP 403 — outside allowed prefix)
SELECT * FROM orders LIMIT 10;

-- Should fail (PutObject denied)
INSERT INTO customer (c_custkey) VALUES (999999);
```
