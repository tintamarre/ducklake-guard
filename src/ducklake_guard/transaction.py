from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import psycopg
from minio import Minio

from ducklake_guard.catalog import sync_rls_policies
from ducklake_guard.db import fetch_all_grants, fetch_all_users, insert_policy_log
from ducklake_guard.policy import build_policy

DGA_POLICY_LOCK_ID = 7_236_849_172_508_029_441


def apply_with_policy_sync(
    guard_conn: psycopg.Connection,
    catalog_conn: psycopg.Connection,
    s3_client: Minio,
    bucket: str,
    mutate: Callable[[psycopg.Cursor], dict[str, Any]],
) -> dict[str, Any]:
    with guard_conn.transaction():
        cur = guard_conn.cursor()
        cur.execute("SELECT pg_advisory_xact_lock(%s)", [DGA_POLICY_LOCK_ID])

        log_entry = mutate(cur)

        grants = fetch_all_grants(cur)
        users = fetch_all_users(cur)
        policy = build_policy(grants, users, bucket)
        serialized_policy = json.dumps(policy)
        if len(serialized_policy.encode()) > 1_000_000:
            size_kb = len(serialized_policy.encode()) // 1024
            raise ValueError(
                f"S3 policy exceeds 1 MB limit ({size_kb} KB). "
                "Reduce the number of grants or users."
            )

        sync_rls_policies(catalog_conn, grants, users)

        if policy["Statement"]:
            s3_client.set_bucket_policy(bucket, serialized_policy)
        else:
            s3_client.delete_bucket_policy(bucket)

        insert_policy_log(
            cur,
            user_name=log_entry.get("user_name"),
            action=log_entry["action"],
            detail=log_entry.get("detail"),
        )

    return log_entry
