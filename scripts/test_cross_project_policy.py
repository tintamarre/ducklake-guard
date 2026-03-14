"""Test that a reader key with read-only access cannot tamper with bucket policy.

Flow:
  A. Admin applies a whole-bucket Allow policy for the reader key.
  B. Reader key reads from the bucket (positive control).
  C. Reader key attempts to delete/replace the policy and write objects (must fail).
  D. Admin switches to a prefix-scoped policy; reader key reads allowed table
     and is denied on a different table.
  E. Admin restores the per-table reader policy.

Required env vars:
  S3_ENDPOINT, S3_USE_SSL, S3_DATA_PATH,
  S3_ACCESS_KEY, S3_SECRET_KEY,
  HETZNER_EXT_PROJECT_ID, S3_READER_EXT_ACCESS_KEY, S3_READER_EXT_SECRET_KEY,
  READER_TABLE
"""

import io
import json
import os
import sys
from minio import Minio
from minio.error import S3Error

from apply_s3_reader_policy import bucket_from_data_path


def _client(access_key: str, secret_key: str, endpoint: str, secure: bool) -> Minio:
    return Minio(endpoint, access_key, secret_key, secure=secure)


def _whole_bucket_read_policy(
    bucket: str, ext_project_id: str, ext_access_key: str
) -> dict:
    """Allow policy granting the reader key read-only access to the whole bucket."""
    principal = f"arn:aws:iam:::user/p{ext_project_id}:{ext_access_key}"
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllowExtRead",
                "Effect": "Allow",
                "Principal": {"AWS": principal},
                "Action": [
                    "s3:GetObject",
                    "s3:GetBucketLocation",
                    "s3:ListBucket",
                ],
                "Resource": [
                    f"arn:aws:s3:::{bucket}",
                    f"arn:aws:s3:::{bucket}/*",
                ],
            },
        ],
    }


def _table_read_policy(
    bucket: str, ext_project_id: str, ext_access_key: str, table: str
) -> dict:
    """Allow policy granting the reader key read-only access to a single table prefix."""
    principal = f"arn:aws:iam:::user/p{ext_project_id}:{ext_access_key}"
    table_prefix = f"main/{table}"
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllowExtGetBucketLocation",
                "Effect": "Allow",
                "Principal": {"AWS": principal},
                "Action": "s3:GetBucketLocation",
                "Resource": f"arn:aws:s3:::{bucket}",
            },
            {
                "Sid": "AllowExtListPrefix",
                "Effect": "Allow",
                "Principal": {"AWS": principal},
                "Action": "s3:ListBucket",
                "Resource": f"arn:aws:s3:::{bucket}",
                "Condition": {
                    "StringLike": {"s3:prefix": [f"{table_prefix}/*"]}
                },
            },
            {
                "Sid": "AllowExtGetObject",
                "Effect": "Allow",
                "Principal": {"AWS": principal},
                "Action": "s3:GetObject",
                "Resource": f"arn:aws:s3:::{bucket}/{table_prefix}/*",
            },
        ],
    }


def _expect_denied(label: str, fn) -> bool:
    """Run fn and expect an S3Error with code 403 or AccessDenied."""
    try:
        fn()
        print(f"[FAIL] {label} — succeeded (expected 403)")
        return False
    except S3Error as e:
        if e.code in ("AccessDenied", "403"):
            print(f"[PASS] {label} — denied ({e.code})")
            return True
        print(f"[FAIL] {label} — unexpected S3 error: {e.code} {e.message}")
        return False
    except Exception as e:
        print(f"[FAIL] {label} — unexpected error: {e}")
        return False


def main():
    endpoint = os.environ["S3_ENDPOINT"]
    use_ssl = os.environ.get("S3_USE_SSL", "false").lower() == "true"
    data_path = os.environ["S3_DATA_PATH"]
    bucket = bucket_from_data_path(data_path)

    # Admin credentials (bucket owner)
    admin_ak = os.environ["S3_ACCESS_KEY"]
    admin_sk = os.environ["S3_SECRET_KEY"]
    table = os.environ["READER_TABLE"]

    # Reader credentials (separate project)
    ext_project_id = os.environ["HETZNER_EXT_PROJECT_ID"]
    ext_ak = os.environ["S3_READER_EXT_ACCESS_KEY"]
    ext_sk = os.environ["S3_READER_EXT_SECRET_KEY"]

    admin = _client(admin_ak, admin_sk, endpoint, use_ssl)
    ext = _client(ext_ak, ext_sk, endpoint, use_ssl)

    passed = 0
    failed = 0

    # --- Phase A: Setup ---
    print("--- Setup: applying whole-bucket read-only policy ---")
    policy = _whole_bucket_read_policy(bucket, ext_project_id, ext_ak)
    admin.set_bucket_policy(bucket, json.dumps(policy))
    print("Applied read-only policy\n")

    try:
        # --- Phase B: Positive control ---
        print("--- Positive control ---")

        # list_objects
        try:
            objects = list(ext.list_objects(bucket))[:1]
            print("[PASS] list_objects succeeded")
            passed += 1
        except Exception as e:
            print(f"[FAIL] list_objects — {e}")
            failed += 1

        # get_object — find a non-directory object
        try:
            obj_key = None
            for obj in ext.list_objects(bucket, prefix="main/", recursive=True):
                if not obj.is_dir and obj.size and obj.size > 0:
                    obj_key = obj.object_name
                    break
            if obj_key:
                resp = ext.get_object(bucket, obj_key)
                resp.read()
                resp.close()
                resp.release_conn()
                print(f"[PASS] get_object succeeded ({obj_key})")
                passed += 1
            else:
                print("[FAIL] get_object — no readable objects found")
                failed += 1
        except Exception as e:
            print(f"[FAIL] get_object — {e}")
            failed += 1

        # --- Phase C: Escalation tests ---
        print("\n--- Escalation tests ---")

        # delete_bucket_policy
        if _expect_denied(
            "delete_bucket_policy",
            lambda: ext.delete_bucket_policy(bucket),
        ):
            passed += 1
        else:
            failed += 1

        # set_bucket_policy (try to grant itself write access)
        escalation_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "EscalateToWrite",
                    "Effect": "Allow",
                    "Principal": {
                        "AWS": f"arn:aws:iam:::user/p{ext_project_id}:{ext_ak}"
                    },
                    "Action": "s3:*",
                    "Resource": [
                        f"arn:aws:s3:::{bucket}",
                        f"arn:aws:s3:::{bucket}/*",
                    ],
                }
            ],
        }
        if _expect_denied(
            "set_bucket_policy",
            lambda: ext.set_bucket_policy(bucket, json.dumps(escalation_policy)),
        ):
            passed += 1
        else:
            failed += 1

        # put_object
        if _expect_denied(
            "put_object",
            lambda: ext.put_object(
                bucket,
                "test-cross-project-write",
                io.BytesIO(b"should not work"),
                length=15,
            ),
        ):
            passed += 1
        else:
            failed += 1

        # --- Phase D: Prefix isolation ---
        print("\n--- Prefix isolation: restricting to single table ---")
        table_policy = _table_read_policy(
            bucket, ext_project_id, ext_ak, table
        )
        admin.set_bucket_policy(bucket, json.dumps(table_policy))
        print(f"Applied prefix-scoped policy for main/{table}/\n")

        # Should succeed — reading allowed table
        try:
            obj_key = None
            for obj in ext.list_objects(
                bucket, prefix=f"main/{table}/", recursive=True
            ):
                if not obj.is_dir and obj.size and obj.size > 0:
                    obj_key = obj.object_name
                    break
            if obj_key:
                resp = ext.get_object(bucket, obj_key)
                resp.read()
                resp.close()
                resp.release_conn()
                print(f"[PASS] get_object on main/{table}/ succeeded ({obj_key})")
                passed += 1
            else:
                print(f"[FAIL] get_object on main/{table}/ — no objects found")
                failed += 1
        except Exception as e:
            print(f"[FAIL] get_object on main/{table}/ — {e}")
            failed += 1

        # Should fail — reading a different table
        other_table = "orders" if table != "orders" else "nation"
        if _expect_denied(
            f"get_object on main/{other_table}/ (outside allowed prefix)",
            lambda: ext.get_object(
                bucket, f"main/{other_table}/nonexistent"
            ),
        ):
            passed += 1
        else:
            failed += 1

    finally:
        # --- Phase E: Teardown ---
        print("\n--- Teardown: restoring per-table reader policy ---")
        reader_policy = _table_read_policy(
            bucket, ext_project_id, ext_ak, table
        )
        admin.set_bucket_policy(bucket, json.dumps(reader_policy))
        print(f"Restored reader policy for main/{table}/")

    print(f"\nResults: {passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
