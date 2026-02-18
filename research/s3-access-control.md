# S3: per-table read-only access

https://ducklake.select/docs/stable/duckdb/guides/access_control#access-control-with-s3-and-postgresql

Hetzner Object Storage gives every S3 key in a project full access to all
buckets by default. We use a bucket policy to restrict a reader key to
read-only access on a single DuckLake table.

## 1. Create a reader key pair

Go to Hetzner Console and create a second S3 credential:

https://console.hetzner.cloud → Project → Security → S3 Credentials

Add the credentials to `.env`:

```
S3_READER_ACCESS_KEY="..."
S3_READER_SECRET_KEY="..."
```

## 2. Apply the bucket policy

The policy uses two Deny statements. Hetzner keys have full access by default
(implicit Allow), so we only need to deny what's forbidden:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DenyWrite",
      "Effect": "Deny",
      "Principal": {
        "AWS": "arn:aws:iam:::user/p<HETZNER_PROJECT_ID>:<READER_ACCESS_KEY>"
      },
      "Action": [
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:AbortMultipartUpload"
      ],
      "Resource": [
        "arn:aws:s3:::<bucket>",
        "arn:aws:s3:::<bucket>/*"
      ]
    },
    {
      "Sid": "DenyReadOutsideTable",
      "Effect": "Deny",
      "Principal": {
        "AWS": "arn:aws:iam:::user/p<HETZNER_PROJECT_ID>:<READER_ACCESS_KEY>"
      },
      "Action": ["s3:GetObject"],
      "NotResource": ["arn:aws:s3:::<bucket>/main/<table>/*"]
    }
  ]
}
```

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
