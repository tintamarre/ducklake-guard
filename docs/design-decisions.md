# Design decisions

Had to make quite a few decisions to get things working in Hetzner, here you will find what those were, and can serve as inspiration for future implementations.

## 1. Separate Hetzner projects for access control

Hetzner gives every S3 key in the same project full access to all buckets by default. A key in the bucket-owning project can delete the bucket policy and restore unrestricted access. There is no way to prevent this within a single project.

By creating user credentials in a separate Hetzner project, the defaults flip: the key starts with zero access and cannot touch the bucket policy (403 on `delete_bucket_policy`, `set_bucket_policy`, and `put_object`). The bucket owner's policy is the only way to grant access.

| Scenario | Same-project key | Separate-project key |
|---|---|---|
| Default access | Full (implicit Allow) | None |
| Restrict to table | Deny + NotResource | Allow on specific prefix |
| Policy deleted | Key regains full access | Key has zero access |
| Policy tampering | Key can delete its own restrictions | Key cannot touch policy (403) |

This is why `dga user create` requires a `--project-id` from a different project. Same-project keys would undermine the access model.

## 2. RLS on `ducklake_table`

DuckLake's `SHOW TABLES` reads from `ducklake_table` in the Postgres catalog. Row-Level Security on that table controls which tables the user can see. Without RLS, S3 blocks data access but the user still sees every table name listed.

RLS is deny-by-default: once enabled, rows are hidden unless a policy grants access. Each user gets a policy like:

```sql
CREATE POLICY dga_tim_tables ON ducklake_table
  FOR SELECT TO dga_tim USING (table_name IN ('customer', 'orders'));
```

**Limitation:** Only `ducklake_table` is filtered (for now, will revisit later). Other metadata tables (`ducklake_column`, `ducklake_data_file`) are not filtered, so a user could infer table names from column or file metadata. S3 remains the real security boundary. RLS is a usability feature, not a security guarantee.

## 3. Postgres as source of truth

The S3 bucket policy and RLS policies are derived artifacts. Every mutation rebuilds both from the full grant set in Postgres, inside an open transaction with an advisory lock.

The push-before-commit pattern means the common failure (S3 or RLS push fails) leaves Postgres unchanged. No grant was written, no drift. The rare failure (commit fails after S3/RLS success) leaves S3 or RLS ahead of Postgres. `dga sync` converges everything back.

This is a deliberate trade-off: brief inconsistency windows are possible, but the system always has a single authoritative state to converge toward. No distributed consensus, no two-phase commit. Just one database and a fix-everything command.

## 4. Full policy rewrite on every change

Hetzner's S3 implementation only supports `set_bucket_policy` (full replace) and `delete_bucket_policy`. There is no API to patch individual statements or add/remove a single grant from an existing policy. Every change — granting one table to one user — requires reading the full grant set from Postgres, rebuilding the entire policy JSON, and pushing it as a whole.

This constraint is why the sync pattern exists: since every mutation already does a full rewrite, convergence is just the same operation without a preceding grant change. It also means `dga sync` is always safe to run — it's the same code path as a normal grant, minus the INSERT.

## 5. Statement bundling for policy size

Hetzner enforces a 1 MB limit on bucket policies. A naive approach (one statement per table per action per user) generates 3 to 5 statements per table grant. At 100 tables and 50 users, that exceeds the limit.

Bundling helps mitigate this: all table prefixes for the same action go into a single statement as arrays. Each user produces 3 to 5 statements total, regardless of how many tables they have:

```
AllowGetBucketLocation-tim  → bucket-wide, one per user
AllowListPrefix-tim         → all table prefixes in Condition array
AllowGetObject-tim          → all table prefixes in Resource array
AllowPutObject-tim          → read-write table prefixes only
AllowDeleteObject-tim       → read-write table prefixes only
```

`PutObject` and `DeleteObject` statements are only emitted when the user has at least one `read_write` grant. This keeps the policy compact enough for roughly 120 users with 100 tables each.

## 6. Postgres role naming and permissions

Each user gets a Postgres role named `dga_<user>` with `GRANT ALL` on catalog tables. This sounds permissive, but DuckLake's write path needs metadata updates (inserting rows into `ducklake_data_file`, updating `ducklake_table` metadata). A `SELECT`-only role would break DuckLake writes.

RLS controls what the user can see in `ducklake_table`. S3 controls what data they can read or write. The Postgres role is just the authentication mechanism for DuckDB's catalog connection. The actual access boundaries live in the other two layers.
