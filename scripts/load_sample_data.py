"""Load sample data into the lakehouse.

To add a new data source, write a function that takes a DuckDB connection
(with the lakehouse already attached as `lake`) and creates tables in it.
See load_tpch() for an example.
"""

import logging
import os
from contextlib import contextmanager

import duckdb

logger = logging.getLogger(__name__)


TPCH_TABLES = [
    "nation",
    "region",
    "supplier",
    "customer",
    "part",
    "partsupp",
    "orders",
    "lineitem",
]


@contextmanager
def connect_to_lakehouse():
    """Connect to the lakehouse using environment variables.

    Expects the same env vars as init.sql: S3_ENDPOINT, S3_ACCESS_KEY,
    S3_SECRET_KEY, S3_REGION, S3_USE_SSL, S3_DATA_PATH, POSTGRES_HOST,
    and POSTGRES_DB_PASSWORD.

    Yields a DuckDB connection with the lakehouse attached as ``lake``.
    """
    conn = duckdb.connect()
    try:
        conn.execute("INSTALL ducklake; INSTALL postgres;")
        conn.execute("LOAD ducklake; LOAD postgres;")

        conn.execute(f"""
            CREATE OR REPLACE SECRET s3_secret (TYPE s3, PROVIDER config,
                ENDPOINT '{os.environ["S3_ENDPOINT"]}',
                KEY_ID '{os.environ["S3_ACCESS_KEY"]}',
                SECRET '{os.environ["S3_SECRET_KEY"]}',
                REGION '{os.environ["S3_REGION"]}',
                URL_STYLE 'path',
                USE_SSL {os.environ.get("S3_USE_SSL", "false")});
        """)
        conn.execute(f"""
            CREATE OR REPLACE SECRET pg_secret (TYPE postgres,
                HOST '{os.environ["POSTGRES_HOST"]}', PORT 5432,
                DATABASE 'ducklake_catalog', USER 'ducklake',
                PASSWORD '{os.environ["POSTGRES_DB_PASSWORD"]}');
        """)
        conn.execute(f"""
            CREATE SECRET ducklake_secret (TYPE ducklake, METADATA_PATH '',
                DATA_PATH '{os.environ["S3_DATA_PATH"]}',
                METADATA_PARAMETERS MAP {{'TYPE': 'postgres', 'SECRET': 'pg_secret'}});
        """)
        conn.execute("ATTACH 'ducklake:ducklake_secret' AS lake;")
        yield conn
    finally:
        conn.close()


def load_tpch(conn):
    """Generate TPC-H tables (sf=0.01) and copy them into the lakehouse."""
    conn.execute("INSTALL tpch; LOAD tpch;")
    conn.execute("CALL dbgen(sf=0.01);")
    for table in TPCH_TABLES:
        conn.execute(f"CREATE OR REPLACE TABLE lake.{table} AS SELECT * FROM {table};")
        conn.execute(f"DROP TABLE {table};")


def load_sample_data():
    """Load TPC-H sample data into the lakehouse."""
    with connect_to_lakehouse() as conn:
        load_tpch(conn)


if __name__ == "__main__":
    load_sample_data()
