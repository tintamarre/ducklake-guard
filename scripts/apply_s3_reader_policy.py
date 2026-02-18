"""Apply a per-table read-only bucket policy for DuckLake on Hetzner Object Storage.

Hetzner gives every S3 key in a project full access to all buckets by default.
This script applies Deny-only statements to restrict the reader key:
  - Deny write operations on the entire bucket.
  - Deny GetObject on everything except the allowed table prefix (via NotResource).

The default project-level access provides the implicit Allow.

Create the reader key pair in Hetzner Console first, then run this script.

Required env vars: S3_ENDPOINT, S3_ACCESS_KEY, S3_SECRET_KEY, S3_DATA_PATH,
HETZNER_PROJECT_ID, S3_READER_ACCESS_KEY, READER_TABLE.
"""

import json
import os
from urllib.parse import urlparse

from minio import Minio


def bucket_from_data_path(data_path: str) -> str:
    """Extract the bucket name from an S3 data path.

    Handles both 's3://bucket/...' URLs and plain 'bucket/...' paths.
    """
    parsed = urlparse(data_path)
    if parsed.scheme in ("s3", "s3a"):
        return parsed.netloc
    return data_path.split("/")[0]


def main():
    endpoint = os.environ["S3_ENDPOINT"]
    access_key = os.environ["S3_ACCESS_KEY"]
    secret_key = os.environ["S3_SECRET_KEY"]
    data_path = os.environ["S3_DATA_PATH"]
    project_id = os.environ["HETZNER_PROJECT_ID"]
    reader_access_key = os.environ["S3_READER_ACCESS_KEY"]
    table = os.environ["READER_TABLE"]
    use_ssl = os.environ.get("S3_USE_SSL", "false").lower() == "true"

    bucket = bucket_from_data_path(data_path)
    reader_principal = f"arn:aws:iam:::user/p{project_id}:{reader_access_key}"
    table_prefix = f"main/{table}"

    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "DenyWrite",
                "Effect": "Deny",
                "Principal": {"AWS": reader_principal},
                "Action": [
                    "s3:PutObject",
                    "s3:DeleteObject",
                    "s3:AbortMultipartUpload",
                ],
                "Resource": [
                    f"arn:aws:s3:::{bucket}",
                    f"arn:aws:s3:::{bucket}/*",
                ],
            },
            {
                "Sid": "DenyReadOutsideTable",
                "Effect": "Deny",
                "Principal": {"AWS": reader_principal},
                "Action": ["s3:GetObject"],
                "NotResource": [f"arn:aws:s3:::{bucket}/{table_prefix}/*"],
            },
        ],
    }

    client = Minio(endpoint, access_key, secret_key, secure=use_ssl)
    client.set_bucket_policy(bucket, json.dumps(policy))

    print(f"Applied table-scoped policy on '{bucket}'")
    print(f"  Reader key: {reader_access_key}")
    print(f"  Allowed: s3:GetObject on {table_prefix}/*")
    print(f"  Denied: writes + reads outside {table_prefix}/")


if __name__ == "__main__":
    main()
