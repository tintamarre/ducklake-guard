from __future__ import annotations

import secrets

import psycopg
from psycopg import sql


def create_catalog_role(conn: psycopg.Connection, user_name: str) -> str:
    role_name = f"dga_{user_name}"
    password = secrets.token_urlsafe(24)
    with conn.pipeline():
        conn.execute(
            sql.SQL("CREATE USER {} WITH PASSWORD {}").format(
                sql.Identifier(role_name),
                sql.Literal(password),
            )
        )
        conn.execute(
            sql.SQL("GRANT ALL ON ALL TABLES IN SCHEMA public TO {}").format(
                sql.Identifier(role_name),
            )
        )
        conn.execute(
            sql.SQL(
                "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}"
            ).format(
                sql.Identifier(role_name),
            )
        )
    return password


def drop_catalog_role(conn: psycopg.Connection, user_name: str) -> None:
    role_name = f"dga_{user_name}"
    policy_name = f"dga_{user_name}_tables"
    with conn.pipeline():
        conn.execute(
            sql.SQL("DROP POLICY IF EXISTS {} ON ducklake_table").format(
                sql.Identifier(policy_name),
            )
        )
        conn.execute(
            sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}").format(
                sql.Identifier(role_name),
            )
        )
        conn.execute(
            sql.SQL("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {}").format(
                sql.Identifier(role_name),
            )
        )
        conn.execute(
            sql.SQL("DROP USER IF EXISTS {}").format(
                sql.Identifier(role_name),
            )
        )


def sync_rls_policies(
    conn: psycopg.Connection,
    grants: list[dict[str, str]],
    users: dict[str, dict[str, str]],
) -> None:
    user_tables: dict[str, list[str]] = {}
    for g in grants:
        user_tables.setdefault(g["user_name"], []).append(g["table_name"])

    with conn.pipeline():
        for user_name in users:
            role_name = f"dga_{user_name}"
            policy_name = f"dga_{user_name}_tables"

            conn.execute(
                sql.SQL("DROP POLICY IF EXISTS {} ON ducklake_table").format(
                    sql.Identifier(policy_name),
                )
            )

            tables = sorted(user_tables.get(user_name, []))
            if tables:
                table_list = sql.SQL(", ").join(sql.Literal(t) for t in tables)
                conn.execute(
                    sql.SQL(
                        "CREATE POLICY {} ON ducklake_table"
                        " FOR SELECT TO {} USING (table_name IN ({}))"
                    ).format(
                        sql.Identifier(policy_name),
                        sql.Identifier(role_name),
                        table_list,
                    )
                )
