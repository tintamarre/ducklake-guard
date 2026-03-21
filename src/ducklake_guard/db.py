from __future__ import annotations

from typing import Any

import psycopg
from psycopg.types.json import Jsonb


def create_user(
    cur: psycopg.Cursor,
    name: str,
    access_key: str,
    project_id: str,
    created_by: str | None = None,
) -> None:
    cur.execute(
        "INSERT INTO users (name, access_key, project_id, created_by) "
        "VALUES (%s, %s, %s, %s)",
        [name, access_key, project_id, created_by],
    )


def delete_user(cur: psycopg.Cursor, name: str) -> None:
    cur.execute("DELETE FROM users WHERE name = %s", [name])


def get_user(cur: psycopg.Cursor[dict[str, Any]], name: str) -> dict[str, Any] | None:
    cur.execute(
        "SELECT name, access_key, project_id, principal_arn FROM users WHERE name = %s",
        [name],
    )
    return cur.fetchone()


def upsert_grant(
    cur: psycopg.Cursor,
    user_name: str,
    table_name: str,
    permission: str,
    granted_by: str | None = None,
) -> None:
    cur.execute(
        "INSERT INTO grants (user_name, table_name, permission, granted_by) "
        "VALUES (%s, %s, %s, %s) "
        "ON CONFLICT (user_name, table_name) "
        "DO UPDATE SET permission = EXCLUDED.permission, "
        "granted_at = now(), granted_by = EXCLUDED.granted_by",
        [user_name, table_name, permission, granted_by],
    )


def delete_grant(cur: psycopg.Cursor, user_name: str, table_name: str) -> int:
    cur.execute(
        "DELETE FROM grants WHERE user_name = %s AND table_name = %s",
        [user_name, table_name],
    )
    return cur.rowcount


def fetch_all_grants(cur: psycopg.Cursor[dict[str, Any]]) -> list[dict[str, Any]]:
    cur.execute(
        "SELECT user_name, table_name, permission "
        "FROM grants ORDER BY user_name, table_name"
    )
    return cur.fetchall()


def fetch_all_users(cur: psycopg.Cursor[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    cur.execute(
        "SELECT name, access_key, project_id, principal_arn FROM users ORDER BY name"
    )
    return {row["name"]: row for row in cur.fetchall()}


def insert_policy_log(
    cur: psycopg.Cursor,
    user_name: str | None,
    action: str,
    detail: dict | None = None,
) -> None:
    cur.execute(
        "INSERT INTO policy_log (user_name, action, detail) VALUES (%s, %s, %s)",
        [user_name, action, Jsonb(detail)],
    )
