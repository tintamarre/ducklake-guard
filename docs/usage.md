# Usage

## Initialize

[!NOTE] This requires quite some permissions to setup, and is now here for convenience, might be decoupled to avoid needing global access later.

`dga init` creates the `ducklake_guard` database, schema, `pg_hba` entry, and enables RLS on `ducklake_table`. It SSHes into the PostgreSQL server and runs the setup as the `postgres` superuser.

```bash
cp .env.sample .env
# Fill in credentials (see .env.sample for required variables)

dga init
```

The SSH host is read from `POSTGRES_HOST` in the environment. Override with `--ssh-host`:

```bash
dga init --ssh-host my-server
```

## Load sample data (optional)

```bash
set -a && source .env && set +a
uv run python scripts/load_sample_data.py
```

## Create a user

S3 credentials must be created manually in the [Hetzner Console](https://console.hetzner.cloud) first (there is no API for credential lifecycle). Then register them with `dga`:

```bash
dga user create tim \
  --access-key DCVYO3GHE6HFYH9AQH37 \
  --project-id 13793486
```

This does three things:

1. Stores the user in `ducklake_guard` (access key, project ID, derived principal ARN).
2. Creates a catalog role `dga_tim` in `ducklake_catalog` with a generated password — printed once, save it immediately.
3. Writes an `init-tim.sql` file that uses `getenv()` for all secrets (`S3_ACCESS_KEY`, `S3_SECRET_KEY`, `DGA_CATALOG_PASSWORD`). No credentials are written to disk.

The `--project-id` must be from a separate Hetzner project, not the one that owns the bucket. Same-project keys have full access by default and can delete the bucket policy. Separate-project keys start with zero access.

## Grant access

```bash
dga allow tim --table customer --read-only
dga allow tim --table orders --read-write
```

Each command updates the grant in Postgres, rebuilds the full S3 bucket policy, and recreates the user's RLS policy. Running `allow` on a table that already has a grant UPSERTs the permission level.

`--read-only` grants `GetObject`, `ListBucket` (prefix-scoped), and `GetBucketLocation`. `--read-write` adds `PutObject` and `DeleteObject`.

## Verify with DuckDB

```bash
set -a && source .env && set +a
duckdb -init init-tim.sql
```

```sql
SHOW TABLES;        -- only granted tables visible
SELECT * FROM customer LIMIT 10;  -- works (read-only)
SELECT * FROM orders LIMIT 10;    -- works (read-write)
INSERT INTO orders (...) VALUES (...);  -- works (read-write)
INSERT INTO customer (...) VALUES (...);  -- fails (read-only, S3 403)
```

## Revoke access

```bash
dga deny tim --table orders
```

Removes the grant from Postgres, rebuilds S3 policy without that table's prefixes, and recreates the RLS policy. The user's `SHOW TABLES` no longer lists the table, and S3 returns 403 on data access.

## Sync

If S3 or RLS have drifted from the Postgres grant state (manual bucket policy edit, failed push, partial commit), `dga sync` converges them:

```bash
dga sync
```

Sync reads all grants, rebuilds the desired S3 policy and RLS policies, compares against the live state, and pushes any differences. Safe to run at any time.

## Delete a user

```bash
dga user delete tim
```

This removes the user from `ducklake_guard`, scrubs their statements from the S3 bucket policy, drops their RLS policy, and drops the `dga_tim` catalog role.

The CLI prints a reminder to delete the S3 credential in the Hetzner Console. There is no API for this, so it must be done manually.
