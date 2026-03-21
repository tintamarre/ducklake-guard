from __future__ import annotations

import json

import psycopg
from minio import Minio
from minio.error import S3Error

from ducklake_guard.catalog import sync_rls_policies
from ducklake_guard.db import fetch_all_grants, fetch_all_users, insert_policy_log
from ducklake_guard.policy import build_policy, normalize_policy
from ducklake_guard.transaction import DGA_POLICY_LOCK_ID


def sync(
    guard_conn: psycopg.Connection,
    catalog_conn: psycopg.Connection,
    s3_client: Minio,
    bucket: str,
) -> dict[str, bool]:
    result = {"s3_changed": False, "rls_changed": False}

    with guard_conn.transaction():
        cur = guard_conn.cursor()
        cur.execute("SELECT pg_advisory_xact_lock(%s)", [DGA_POLICY_LOCK_ID])

        grants = fetch_all_grants(cur)
        users = fetch_all_users(cur)
        desired = build_policy(grants, users, bucket)

        try:
            current_raw = s3_client.get_bucket_policy(bucket)
            current = json.loads(current_raw)
        except S3Error as e:
            if e.code != "NoSuchBucketPolicy":
                raise
            current = {"Version": "2012-10-17", "Statement": []}

        if normalize_policy(desired) != normalize_policy(current):
            if desired["Statement"]:
                s3_client.set_bucket_policy(bucket, json.dumps(desired))
            else:
                try:
                    s3_client.delete_bucket_policy(bucket)
                except S3Error as e:
                    if e.code != "NoSuchBucketPolicy":
                        raise
            result["s3_changed"] = True

        rls_changed = _sync_rls(catalog_conn, grants, users)
        result["rls_changed"] = rls_changed

        insert_policy_log(cur, user_name=None, action="sync", detail=result)

    return result


def _sync_rls(
    conn: psycopg.Connection,
    grants: list[dict[str, str]],
    users: dict[str, dict[str, str]],
) -> bool:
    user_tables: dict[str, set[str]] = {}
    for g in grants:
        user_tables.setdefault(g["user_name"], set()).add(g["table_name"])

    changed = False
    for user_name in users:
        role_name = f"dga_{user_name}"
        policy_name = f"dga_{user_name}_tables"
        desired_tables = sorted(user_tables.get(user_name, set()))

        current_tables = _get_current_rls_tables(conn, policy_name, role_name)

        if desired_tables != current_tables:
            changed = True

    if changed:
        sync_rls_policies(conn, grants, users)

    return changed


def _get_current_rls_tables(
    conn: psycopg.Connection,
    policy_name: str,
    role_name: str,
) -> list[str]:
    row = conn.execute(
        "SELECT qual FROM pg_policies "
        "WHERE policyname = %s AND tablename = 'ducklake_table'",
        [policy_name],
    ).fetchone()
    if row is None:
        return []
    qual = row[0]
    if "ANY" in qual and "{" in qual:
        arr_str = qual.split("{")[1].split("}")[0]
        return sorted(arr_str.split(","))
    if "=" in qual and "'" in qual:
        parts = qual.split("'")
        for i, p in enumerate(parts):
            if "text" in p and i > 0:
                return [parts[i - 1]]
    return []
