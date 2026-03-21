from __future__ import annotations

import contextlib
import json
import os

import psycopg
import pytest
from minio import Minio
from psycopg import sql
from psycopg.rows import dict_row

from ducklake_guard.adapter.hetzner import create_s3_client
from ducklake_guard.config import Config
from ducklake_guard.db import fetch_all_grants, fetch_all_users
from ducklake_guard.policy import build_policy

REQUIRED_ENV_VARS = [
    "S3_ENDPOINT",
    "S3_ACCESS_KEY",
    "S3_SECRET_KEY",
    "S3_BUCKET_NAME",
    "S3_DATA_PATH",
    "S3_USE_SSL",
    "S3_REGION",
    "POSTGRES_HOST",
    "POSTGRES_DB_PASSWORD",
    "HETZNER_EXT_PROJECT_ID",
    "TEST_USER_ACCESS_KEY",
    "TEST_USER_SECRET_KEY",
]

TEST_USER_NAME = "test-cli-user"
TEST_USER_ACCESS_KEY = os.environ.get("TEST_USER_ACCESS_KEY", "")
TEST_USER_SECRET_KEY = os.environ.get("TEST_USER_SECRET_KEY", "")


@pytest.fixture(scope="session")
def config() -> Config:
    missing = [v for v in REQUIRED_ENV_VARS if v not in os.environ]
    if missing:
        pytest.skip(f"Missing env vars: {', '.join(missing)}")
    return Config.from_env()


@pytest.fixture(scope="session")
def guard_conn(config: Config) -> psycopg.Connection:
    conn = psycopg.connect(
        host=config.postgres_host,
        dbname="ducklake_guard",
        user="ducklake",
        password=config.postgres_db_password,
        autocommit=True,
        row_factory=dict_row,
    )
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def catalog_conn(config: Config) -> psycopg.Connection:
    conn = psycopg.connect(
        host=config.postgres_host,
        dbname="ducklake_catalog",
        user="ducklake",
        password=config.postgres_db_password,
        autocommit=True,
    )
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def s3_client(config: Config) -> Minio:
    return create_s3_client(config)


@pytest.fixture(scope="session")
def ext_project_id() -> str:
    return os.environ["HETZNER_EXT_PROJECT_ID"]


@pytest.fixture
def clean_test_user(
    config: Config,
    guard_conn: psycopg.Connection,
    catalog_conn: psycopg.Connection,
    s3_client: Minio,
) -> str:
    _force_cleanup(config, guard_conn, catalog_conn, s3_client)
    yield TEST_USER_NAME
    _force_cleanup(config, guard_conn, catalog_conn, s3_client)


def _force_cleanup(
    config: Config,
    guard_conn: psycopg.Connection,
    catalog_conn: psycopg.Connection,
    s3_client: Minio,
) -> None:
    with guard_conn.transaction():
        cur = guard_conn.cursor()
        cur.execute(
            "DELETE FROM grants WHERE user_name = %s",
            [TEST_USER_NAME],
        )
        cur.execute("DELETE FROM users WHERE name = %s", [TEST_USER_NAME])

    role = f"dga_{TEST_USER_NAME}"
    policy = f"dga_{TEST_USER_NAME}_tables"
    for stmt in [
        sql.SQL("DROP POLICY IF EXISTS {} ON ducklake_table").format(
            sql.Identifier(policy)
        ),
        sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}").format(
            sql.Identifier(role)
        ),
        sql.SQL("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {}").format(
            sql.Identifier(role)
        ),
        sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)),
    ]:
        with contextlib.suppress(Exception):
            catalog_conn.execute(stmt)

    with contextlib.suppress(Exception):
        with guard_conn.transaction():
            cur = guard_conn.cursor()
            grants = fetch_all_grants(cur)
            users = fetch_all_users(cur)

        policy = build_policy(grants, users, config.s3_bucket_name)
        if policy["Statement"]:
            s3_client.set_bucket_policy(config.s3_bucket_name, json.dumps(policy))
        else:
            with contextlib.suppress(Exception):
                s3_client.delete_bucket_policy(config.s3_bucket_name)
