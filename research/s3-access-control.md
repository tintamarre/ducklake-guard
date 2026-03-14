# S3: per-table read-only access

https://ducklake.select/docs/stable/duckdb/guides/access_control#access-control-with-s3-and-postgresql

## Hetzner requires two projects for access control: one for the bucket, one for user credentials.

Hetzner gives every S3 key in the same project full access to all buckets by default.
This negates any ability to have granular S3 access within the same bucket.

However, by creating S3 keys in a separate project, access is denied by default.
This gives us the space manage permissions without the risk of users deleting these constraints themselves.

| | Same-project key | Separate-project key |
|---|---|---|
| Default access | Full (implicit Allow) | None |
| Restrict to table | Deny + NotResource | Allow on specific prefix |
| Policy deleted | Key regains full access | Key has zero access |
| Policy tampering | Key can delete its own restrictions | Key cannot touch policy (403) |

## 1. Create a reader key pair

Create a second Hetzner Cloud project for the reader credentials. In that project,
create an S3 key pair:

https://console.hetzner.cloud → Project → Security → S3 Credentials

Add to `.env`:

```
S3_READER_EXT_ACCESS_KEY="..."
S3_READER_EXT_SECRET_KEY="..."
HETZNER_EXT_PROJECT_ID="..."
```

The principal ARN uses the reader's project ID (not the project that owns the
bucket):

```
arn:aws:iam:::user/p<PROJECT_ID>:<ACCESS_KEY>
```

## 2. Apply the bucket policy

The policy uses three Allow statements granting the reader key read-only access
to a single DuckLake table prefix:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowReaderGetBucketLocation",
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam:::user/p<PROJECT_ID>:<ACCESS_KEY>"
      },
      "Action": "s3:GetBucketLocation",
      "Resource": "arn:aws:s3:::<bucket>"
    },
    {
      "Sid": "AllowReaderListPrefix",
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam:::user/p<PROJECT_ID>:<ACCESS_KEY>"
      },
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::<bucket>",
      "Condition": {
        "StringLike": { "s3:prefix": ["main/<table>/*"] }
      }
    },
    {
      "Sid": "AllowReaderGetObject",
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam:::user/p<PROJECT_ID>:<ACCESS_KEY>"
      },
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::<bucket>/main/<table>/*"
    }
  ]
}
```

`s3:GetBucketLocation` is required — the minio client calls it before any list
or get operation.

The script applies this automatically:

```bash
set -a && source .env && set +a
READER_TABLE=customer uv run python scripts/apply_s3_reader_policy.py
```

## Test

```bash
set -a && source .env && set +a && duckdb -init init-reader.sql
```

Should succeed — reading the allowed table:

```sql
SELECT * FROM customer LIMIT 10;
```

Should fail — reading a table outside the allowed prefix (HTTP 403):

```sql
SELECT * FROM orders LIMIT 10;
```

Should fail — inserting into the allowed table (PutObject denied):

```sql
INSERT INTO customer (c_custkey) VALUES (999999);
```

## Escalation test

Verifies that a reader key with read-only access cannot escalate privileges:

```bash
set -a && source .env && set +a
READER_TABLE=customer uv run python scripts/test_cross_project_policy.py
```

The script:

1. Admin applies a whole-bucket Allow policy for the reader key.
2. Reader key lists and reads objects (positive control — must succeed).
3. Reader key attempts `delete_bucket_policy`, `set_bucket_policy`, and
   `put_object` (must all fail with 403).
4. Admin switches to a prefix-scoped policy for `main/<table>/` only.
5. Reader key reads the allowed table (must succeed) and a different table
   (must fail with 403).
6. Admin restores the per-table reader policy.
