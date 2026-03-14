"""Apply a per-table read-only bucket policy for a reader key.

The reader key lives in a separate Hetzner project so it has zero implicit
access. This script applies Allow-only statements granting read access to a
single DuckLake table prefix. The reader key cannot modify or delete the
policy, and removing the policy reverts access to zero.

Required env vars:
  S3_ENDPOINT, S3_ACCESS_KEY, S3_SECRET_KEY, S3_DATA_PATH, S3_USE_SSL,
  HETZNER_EXT_PROJECT_ID, S3_READER_EXT_ACCESS_KEY, READER_TABLE
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
    ext_project_id = os.environ["HETZNER_EXT_PROJECT_ID"]
    reader_access_key = os.environ["S3_READER_EXT_ACCESS_KEY"]
    table = os.environ["READER_TABLE"]
    use_ssl = os.environ.get("S3_USE_SSL", "false").lower() == "true"

    bucket = bucket_from_data_path(data_path)
    principal = f"arn:aws:iam:::user/p{ext_project_id}:{reader_access_key}"
    table_prefix = f"main/{table}"

    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllowReaderGetBucketLocation",
                "Effect": "Allow",
                "Principal": {"AWS": principal},
                "Action": "s3:GetBucketLocation",
                "Resource": f"arn:aws:s3:::{bucket}",
            },
            {
                "Sid": "AllowReaderListPrefix",
                "Effect": "Allow",
                "Principal": {"AWS": principal},
                "Action": "s3:ListBucket",
                "Resource": f"arn:aws:s3:::{bucket}",
                "Condition": {
                    "StringLike": {"s3:prefix": [f"{table_prefix}/*"]}
                },
            },
            {
                "Sid": "AllowReaderGetObject",
                "Effect": "Allow",
                "Principal": {"AWS": principal},
                "Action": "s3:GetObject",
                "Resource": f"arn:aws:s3:::{bucket}/{table_prefix}/*",
            },
        ],
    }

    client = Minio(endpoint, access_key, secret_key, secure=use_ssl)
    client.set_bucket_policy(bucket, json.dumps(policy))

    print(f"Applied read-only policy on '{bucket}'")
    print(f"  Reader key: {reader_access_key} (project {ext_project_id})")
    print(f"  Allowed: s3:GetObject + s3:ListBucket on {table_prefix}/*")


if __name__ == "__main__":
    main()
