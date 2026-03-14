"""Test the bucket policy size limit on Hetzner Object Storage.

Generates policies of increasing size and attempts to apply them.
Reports byte size before sending and whether the apply succeeded.

Required env vars:
  S3_ENDPOINT, S3_ACCESS_KEY, S3_SECRET_KEY, S3_DATA_PATH, S3_USE_SSL,
  HETZNER_EXT_PROJECT_ID, S3_READER_EXT_ACCESS_KEY
"""

import json
import os
from urllib.parse import urlparse

from minio import Minio


def bucket_from_data_path(data_path: str) -> str:
    parsed = urlparse(data_path)
    if parsed.scheme in ("s3", "s3a"):
        return parsed.netloc
    return data_path.split("/")[0]


def build_policy(
    bucket: str, base_principal: str, num_users: int, num_tables: int
) -> str:
    """Build a policy JSON string with num_users principals, each granted num_tables."""
    tables = [f"fake_table_{i:04d}" for i in range(num_tables)]
    statements = []

    for u in range(num_users):
        principal = f"{base_principal}_user{u:03d}"
        sid_suffix = f"U{u:03d}"

        statements.append(
            {
                "Sid": f"GetBucketLocation{sid_suffix}",
                "Effect": "Allow",
                "Principal": {"AWS": principal},
                "Action": "s3:GetBucketLocation",
                "Resource": f"arn:aws:s3:::{bucket}",
            }
        )
        statements.append(
            {
                "Sid": f"ListPrefix{sid_suffix}",
                "Effect": "Allow",
                "Principal": {"AWS": principal},
                "Action": "s3:ListBucket",
                "Resource": f"arn:aws:s3:::{bucket}",
                "Condition": {
                    "StringLike": {"s3:prefix": [f"main/{t}/*" for t in tables]}
                },
            }
        )
        statements.append(
            {
                "Sid": f"GetObject{sid_suffix}",
                "Effect": "Allow",
                "Principal": {"AWS": principal},
                "Action": "s3:GetObject",
                "Resource": [f"arn:aws:s3:::{bucket}/main/{t}/*" for t in tables],
            }
        )

    policy = {"Version": "2012-10-17", "Statement": statements}
    return json.dumps(policy)


def main():
    endpoint = os.environ["S3_ENDPOINT"]
    access_key = os.environ["S3_ACCESS_KEY"]
    secret_key = os.environ["S3_SECRET_KEY"]
    data_path = os.environ["S3_DATA_PATH"]
    ext_project_id = os.environ["HETZNER_EXT_PROJECT_ID"]
    reader_access_key = os.environ["S3_READER_EXT_ACCESS_KEY"]
    use_ssl = os.environ.get("S3_USE_SSL", "false").lower() == "true"

    bucket = bucket_from_data_path(data_path)
    principal = f"arn:aws:iam:::user/p{ext_project_id}:{reader_access_key}"

    client = Minio(endpoint, access_key, secret_key, secure=use_ssl)

    # Save current policy to restore later
    try:
        original_policy = client.get_bucket_policy(bucket)
    except Exception:
        original_policy = None

    print(f"Bucket: {bucket}")
    print(f"Testing policy size limits (users x tables)...\n")
    print(f"  {'Users':>5}  {'Tables':>6}  {'Stmts':>5}  {'Size':>10}  Result")
    print(f"  {'-----':>5}  {'------':>6}  {'-----':>5}  {'----':>10}  ------")

    scenarios = [
        (5, 10),
        (10, 25),
        (25, 50),
        (50, 50),
        (100, 100),
        (120, 100),
        (125, 100),
    ]

    for num_users, num_tables in scenarios:
        policy_json = build_policy(bucket, principal, num_users, num_tables)
        size_bytes = len(policy_json.encode())
        size_label = (
            f"{size_bytes:,} B" if size_bytes < 1024 else f"{size_bytes / 1024:.1f} KB"
        )
        num_stmts = num_users * 3

        print(
            f"  {num_users:>5}  {num_tables:>6}  {num_stmts:>5}  {size_label:>10}  ",
            end="",
            flush=True,
        )

        try:
            client.set_bucket_policy(bucket, policy_json)
            print("OK")
        except Exception as e:
            print(f"REJECTED — {e}")
            break

    # Restore original policy
    print()
    if original_policy:
        client.set_bucket_policy(bucket, original_policy)
        print("Restored original bucket policy.")
    else:
        client.delete_bucket_policy(bucket)
        print("Removed test policy (no original to restore).")


if __name__ == "__main__":
    main()
