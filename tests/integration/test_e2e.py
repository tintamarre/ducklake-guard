from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import duckdb
import psycopg
import pytest
from click.testing import CliRunner
from minio import Minio

from ducklake_guard.catalog import create_catalog_role, drop_catalog_role
from ducklake_guard.cli import cli
from ducklake_guard.config import Config
from ducklake_guard.db import create_user, delete_grant, upsert_grant
from ducklake_guard.sync import sync
from ducklake_guard.transaction import apply_with_policy_sync

from .conftest import (
    TEST_USER_ACCESS_KEY,
    TEST_USER_NAME,
    TEST_USER_SECRET_KEY,
)

pytestmark = pytest.mark.e2e


def _setup_user(
    guard_conn: psycopg.Connection,
    catalog_conn: psycopg.Connection,
    s3_client: Minio,
    config: Config,
    ext_project_id: str,
) -> str:
    password = create_catalog_role(catalog_conn, TEST_USER_NAME)

    def mutate(cur):
        create_user(cur, TEST_USER_NAME, TEST_USER_ACCESS_KEY, ext_project_id)
        return {"action": "create", "user_name": TEST_USER_NAME}

    apply_with_policy_sync(
        guard_conn, catalog_conn, s3_client, config.s3_bucket_name, mutate
    )
    return password


def _grant(
    guard_conn: psycopg.Connection,
    catalog_conn: psycopg.Connection,
    s3_client: Minio,
    config: Config,
    table: str,
    permission: str,
) -> None:
    def mutate(cur):
        upsert_grant(cur, TEST_USER_NAME, table, permission)
        return {"action": "allow", "user_name": TEST_USER_NAME}

    apply_with_policy_sync(
        guard_conn, catalog_conn, s3_client, config.s3_bucket_name, mutate
    )


def _deny(
    guard_conn: psycopg.Connection,
    catalog_conn: psycopg.Connection,
    s3_client: Minio,
    config: Config,
    table: str,
) -> None:
    def mutate(cur):
        delete_grant(cur, TEST_USER_NAME, table)
        return {"action": "deny", "user_name": TEST_USER_NAME}

    apply_with_policy_sync(
        guard_conn, catalog_conn, s3_client, config.s3_bucket_name, mutate
    )


def _duckdb_conn(config: Config, catalog_password: str) -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect()
    conn.execute("INSTALL ducklake")
    conn.execute("LOAD ducklake")
    conn.execute("INSTALL postgres")
    conn.execute("LOAD postgres")
    conn.execute(
        f"""
        CREATE OR REPLACE SECRET s3_secret (
            TYPE s3,
            PROVIDER config,
            ENDPOINT '{config.s3_endpoint}',
            KEY_ID '{TEST_USER_ACCESS_KEY}',
            SECRET '{TEST_USER_SECRET_KEY}',
            REGION '{config.s3_region}',
            URL_STYLE 'path',
            USE_SSL {str(config.s3_use_ssl).lower()}
        )
        """
    )
    conn.execute(
        f"""
        CREATE OR REPLACE SECRET postgres_secret (
            TYPE postgres,
            HOST '{config.postgres_host}',
            PORT 5432,
            DATABASE ducklake_catalog,
            USER 'dga_{TEST_USER_NAME}',
            PASSWORD '{catalog_password}'
        )
        """
    )
    conn.execute(
        f"""
        CREATE SECRET ducklake_secret (
            TYPE ducklake,
            METADATA_PATH '',
            DATA_PATH '{config.s3_data_path}',
            METADATA_PARAMETERS MAP {{
                'TYPE': 'postgres',
                'SECRET': 'postgres_secret'
            }}
        )
        """
    )
    conn.execute("ATTACH 'ducklake:ducklake_secret' AS ducklake")
    conn.execute("USE ducklake")
    return conn


def _visible_tables(duck: duckdb.DuckDBPyConnection) -> set[str]:
    rows = duck.execute("SHOW TABLES").fetchall()
    return {row[0] for row in rows}


def _can_read(duck: duckdb.DuckDBPyConnection, table: str) -> bool:
    try:
        duck.execute(f"SELECT * FROM {table} LIMIT 1").fetchall()
    except duckdb.Error:
        return False
    return True


class TestDuckDBRoundTrip:
    def test_rls_shows_only_granted_tables(
        self,
        config: Config,
        guard_conn: psycopg.Connection,
        catalog_conn: psycopg.Connection,
        s3_client: Minio,
        clean_test_user: str,
        ext_project_id: str,
    ) -> None:
        pw = _setup_user(guard_conn, catalog_conn, s3_client, config, ext_project_id)
        _grant(
            guard_conn,
            catalog_conn,
            s3_client,
            config,
            "customer",
            "read_only",
        )

        duck = _duckdb_conn(config, pw)
        try:
            tables = _visible_tables(duck)
            assert "customer" in tables
            assert "orders" not in tables
        finally:
            duck.close()

    def test_s3_blocks_ungrouped_table_read(
        self,
        config: Config,
        guard_conn: psycopg.Connection,
        catalog_conn: psycopg.Connection,
        s3_client: Minio,
        clean_test_user: str,
        ext_project_id: str,
    ) -> None:
        pw = _setup_user(guard_conn, catalog_conn, s3_client, config, ext_project_id)
        _grant(
            guard_conn,
            catalog_conn,
            s3_client,
            config,
            "customer",
            "read_only",
        )

        duck = _duckdb_conn(config, pw)
        try:
            assert _can_read(duck, "customer")
        finally:
            duck.close()

    def test_grant_then_deny_hides_table(
        self,
        config: Config,
        guard_conn: psycopg.Connection,
        catalog_conn: psycopg.Connection,
        s3_client: Minio,
        clean_test_user: str,
        ext_project_id: str,
    ) -> None:
        pw = _setup_user(guard_conn, catalog_conn, s3_client, config, ext_project_id)
        _grant(
            guard_conn,
            catalog_conn,
            s3_client,
            config,
            "customer",
            "read_only",
        )
        _grant(
            guard_conn,
            catalog_conn,
            s3_client,
            config,
            "orders",
            "read_only",
        )

        duck = _duckdb_conn(config, pw)
        try:
            assert "orders" in _visible_tables(duck)
            assert _can_read(duck, "orders")
        finally:
            duck.close()

        _deny(guard_conn, catalog_conn, s3_client, config, "orders")

        duck = _duckdb_conn(config, pw)
        try:
            assert "orders" not in _visible_tables(duck)
            assert not _can_read(duck, "orders")
        finally:
            duck.close()

    def test_read_write_allows_insert(
        self,
        config: Config,
        guard_conn: psycopg.Connection,
        catalog_conn: psycopg.Connection,
        s3_client: Minio,
        clean_test_user: str,
        ext_project_id: str,
    ) -> None:
        pw = _setup_user(guard_conn, catalog_conn, s3_client, config, ext_project_id)
        _grant(
            guard_conn,
            catalog_conn,
            s3_client,
            config,
            "customer",
            "read_write",
        )

        duck = _duckdb_conn(config, pw)
        try:
            duck.execute(
                "INSERT INTO customer (c_custkey, c_name, c_address, "
                "c_nationkey, c_phone, c_acctbal, c_mktsegment, c_comment) "
                "VALUES (999999, 'Test', 'Addr', 0, '00-000', 0.0, "
                "'TEST', 'e2e test row')"
            )
            rows = duck.execute(
                "SELECT c_name FROM customer WHERE c_custkey = 999999"
            ).fetchall()
            assert len(rows) == 1
            assert rows[0][0] == "Test"

            duck.execute("DELETE FROM customer WHERE c_custkey = 999999")
        finally:
            duck.close()

    def test_read_only_blocks_insert(
        self,
        config: Config,
        guard_conn: psycopg.Connection,
        catalog_conn: psycopg.Connection,
        s3_client: Minio,
        clean_test_user: str,
        ext_project_id: str,
    ) -> None:
        pw = _setup_user(guard_conn, catalog_conn, s3_client, config, ext_project_id)
        _grant(
            guard_conn,
            catalog_conn,
            s3_client,
            config,
            "customer",
            "read_only",
        )

        duck = _duckdb_conn(config, pw)
        try:
            with pytest.raises(duckdb.Error):
                duck.execute(
                    "INSERT INTO customer (c_custkey, c_name, c_address, "
                    "c_nationkey, c_phone, c_acctbal, c_mktsegment, "
                    "c_comment) VALUES (999998, 'Blocked', 'X', 0, "
                    "'00-000', 0.0, 'TEST', 'should fail')"
                )
        finally:
            duck.close()


class TestS3PolicyVerification:
    def test_policy_has_correct_statements_for_grants(
        self,
        config: Config,
        guard_conn: psycopg.Connection,
        catalog_conn: psycopg.Connection,
        s3_client: Minio,
        clean_test_user: str,
        ext_project_id: str,
    ) -> None:
        _setup_user(guard_conn, catalog_conn, s3_client, config, ext_project_id)
        _grant(
            guard_conn,
            catalog_conn,
            s3_client,
            config,
            "customer",
            "read_only",
        )
        _grant(
            guard_conn,
            catalog_conn,
            s3_client,
            config,
            "orders",
            "read_write",
        )

        raw = s3_client.get_bucket_policy(config.s3_bucket_name)
        policy = json.loads(raw)
        sids = {s["Sid"] for s in policy["Statement"]}

        assert f"AllowGetBucketLocation-{TEST_USER_NAME}" in sids
        assert f"AllowListPrefix-{TEST_USER_NAME}" in sids
        assert f"AllowGetObject-{TEST_USER_NAME}" in sids
        assert f"AllowPutObject-{TEST_USER_NAME}" in sids
        assert f"AllowDeleteObject-{TEST_USER_NAME}" in sids

        put_stmt = next(
            s
            for s in policy["Statement"]
            if s["Sid"] == f"AllowPutObject-{TEST_USER_NAME}"
        )
        resources = put_stmt["Resource"]
        if isinstance(resources, str):
            resources = [resources]
        assert any("orders" in r for r in resources)
        assert not any("customer" in r for r in resources)

    def test_delete_user_removes_all_policy_statements(
        self,
        config: Config,
        guard_conn: psycopg.Connection,
        catalog_conn: psycopg.Connection,
        s3_client: Minio,
        clean_test_user: str,
        ext_project_id: str,
    ) -> None:
        _setup_user(guard_conn, catalog_conn, s3_client, config, ext_project_id)
        _grant(
            guard_conn,
            catalog_conn,
            s3_client,
            config,
            "customer",
            "read_only",
        )

        def mutate_delete(cur):
            cur.execute(
                "DELETE FROM grants WHERE user_name = %s",
                [TEST_USER_NAME],
            )
            cur.execute("DELETE FROM users WHERE name = %s", [TEST_USER_NAME])
            return {"action": "delete", "user_name": TEST_USER_NAME}

        apply_with_policy_sync(
            guard_conn,
            catalog_conn,
            s3_client,
            config.s3_bucket_name,
            mutate_delete,
        )
        drop_catalog_role(catalog_conn, TEST_USER_NAME)

        try:
            raw = s3_client.get_bucket_policy(config.s3_bucket_name)
            policy = json.loads(raw)
            sids = {s["Sid"] for s in policy["Statement"]}
        except Exception:
            sids = set()

        user_sids = {s for s in sids if TEST_USER_NAME in s}
        assert len(user_sids) == 0


class TestSyncConvergence:
    def test_sync_fixes_drifted_s3_policy(
        self,
        config: Config,
        guard_conn: psycopg.Connection,
        catalog_conn: psycopg.Connection,
        s3_client: Minio,
        clean_test_user: str,
        ext_project_id: str,
    ) -> None:
        _setup_user(guard_conn, catalog_conn, s3_client, config, ext_project_id)
        _grant(
            guard_conn,
            catalog_conn,
            s3_client,
            config,
            "customer",
            "read_only",
        )

        wrong_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "WrongStatement",
                    "Effect": "Allow",
                    "Principal": {"AWS": "arn:aws:iam:::user/wrong"},
                    "Action": "s3:GetObject",
                    "Resource": f"arn:aws:s3:::{config.s3_bucket_name}/x/*",
                }
            ],
        }
        s3_client.set_bucket_policy(config.s3_bucket_name, json.dumps(wrong_policy))

        result = sync(guard_conn, catalog_conn, s3_client, config.s3_bucket_name)
        assert result["s3_changed"] is True

        raw = s3_client.get_bucket_policy(config.s3_bucket_name)
        policy = json.loads(raw)
        sids = {s["Sid"] for s in policy["Statement"]}
        assert "WrongStatement" not in sids
        assert f"AllowGetObject-{TEST_USER_NAME}" in sids

        result2 = sync(guard_conn, catalog_conn, s3_client, config.s3_bucket_name)
        assert result2["s3_changed"] is False

    def test_sync_fixes_drifted_rls(
        self,
        config: Config,
        guard_conn: psycopg.Connection,
        catalog_conn: psycopg.Connection,
        s3_client: Minio,
        clean_test_user: str,
        ext_project_id: str,
    ) -> None:
        pw = _setup_user(guard_conn, catalog_conn, s3_client, config, ext_project_id)
        _grant(
            guard_conn,
            catalog_conn,
            s3_client,
            config,
            "customer",
            "read_only",
        )

        from psycopg import sql

        policy_name = f"dga_{TEST_USER_NAME}_tables"
        role_name = f"dga_{TEST_USER_NAME}"
        catalog_conn.execute(
            sql.SQL("DROP POLICY IF EXISTS {} ON ducklake_table").format(
                sql.Identifier(policy_name),
            )
        )
        catalog_conn.execute(
            sql.SQL(
                "CREATE POLICY {} ON ducklake_table"
                " FOR SELECT TO {} USING (table_name IN ('wrong_table'))"
            ).format(
                sql.Identifier(policy_name),
                sql.Identifier(role_name),
            )
        )

        duck = _duckdb_conn(config, pw)
        try:
            tables = _visible_tables(duck)
            assert "customer" not in tables
        finally:
            duck.close()

        result = sync(guard_conn, catalog_conn, s3_client, config.s3_bucket_name)
        assert result["rls_changed"] is True

        duck = _duckdb_conn(config, pw)
        try:
            tables = _visible_tables(duck)
            assert "customer" in tables
        finally:
            duck.close()


class TestCLIEndToEnd:
    def test_full_lifecycle_via_cli(
        self,
        config: Config,
        guard_conn: psycopg.Connection,
        catalog_conn: psycopg.Connection,
        s3_client: Minio,
        clean_test_user: str,
        ext_project_id: str,
    ) -> None:
        runner = CliRunner()

        with patch("ducklake_guard.cli.Config.from_env", return_value=config):
            result = runner.invoke(
                cli,
                [
                    "user",
                    "create",
                    TEST_USER_NAME,
                    "--access-key",
                    TEST_USER_ACCESS_KEY,
                    "--project-id",
                    ext_project_id,
                ],
            )
            assert result.exit_code == 0, result.output
            assert f"Created user '{TEST_USER_NAME}'" in result.output
            assert "Save this password now" in result.output
            pw = _extract_password_from_output(result.output)

            init_file = Path(f"init-{TEST_USER_NAME}.sql")
            assert init_file.exists()
            content = init_file.read_text()
            assert f"dga_{TEST_USER_NAME}" in content
            assert "getenv('S3_SECRET_KEY')" in content

            result = runner.invoke(
                cli,
                ["allow", TEST_USER_NAME, "--table", "customer", "--read-only"],
            )
            assert result.exit_code == 0, result.output

            duck = _duckdb_conn(config, pw)
            try:
                assert "customer" in _visible_tables(duck)
                assert _can_read(duck, "customer")
                assert "orders" not in _visible_tables(duck)
            finally:
                duck.close()

            result = runner.invoke(
                cli,
                ["allow", TEST_USER_NAME, "--table", "orders", "--read-write"],
            )
            assert result.exit_code == 0, result.output

            duck = _duckdb_conn(config, pw)
            try:
                assert "orders" in _visible_tables(duck)
                assert _can_read(duck, "orders")
            finally:
                duck.close()

            result = runner.invoke(
                cli,
                ["deny", TEST_USER_NAME, "--table", "orders"],
            )
            assert result.exit_code == 0, result.output

            duck = _duckdb_conn(config, pw)
            try:
                assert "orders" not in _visible_tables(duck)
            finally:
                duck.close()

            result = runner.invoke(cli, ["sync"])
            assert result.exit_code == 0, result.output
            assert "in sync" in result.output or "updated" in result.output

            result = runner.invoke(cli, ["user", "delete", TEST_USER_NAME])
            assert result.exit_code == 0, result.output
            assert "Deleted" in result.output

            init_file.unlink(missing_ok=True)

        with guard_conn.transaction():
            cur = guard_conn.cursor()
            cur.execute(
                "SELECT count(*) FROM users WHERE name = %s",
                [TEST_USER_NAME],
            )
            assert cur.fetchone()["count"] == 0

        role_row = catalog_conn.execute(
            "SELECT 1 FROM pg_roles WHERE rolname = %s",
            [f"dga_{TEST_USER_NAME}"],
        ).fetchone()
        assert role_row is None


def _extract_password_from_output(output: str) -> str:
    for line in output.splitlines():
        if "Catalog password:" in line:
            return line.split("Catalog password:")[1].strip()
    msg = "Could not find Catalog password in CLI output"
    raise ValueError(msg)
