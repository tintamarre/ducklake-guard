from __future__ import annotations

import os
from dataclasses import dataclass

REQUIRED_ENV_VARS = [
    "S3_ENDPOINT",
    "S3_ACCESS_KEY",
    "S3_SECRET_KEY",
    "S3_BUCKET_NAME",
    "S3_DATA_PATH",
    "POSTGRES_HOST",
    "POSTGRES_DB_PASSWORD",
]


@dataclass(frozen=True)
class Config:
    s3_endpoint: str
    s3_access_key: str
    s3_secret_key: str
    s3_bucket_name: str
    s3_data_path: str
    s3_use_ssl: bool
    s3_region: str
    postgres_host: str
    postgres_db_password: str

    @classmethod
    def from_env(cls) -> Config:
        missing = [v for v in REQUIRED_ENV_VARS if v not in os.environ]
        if missing:
            import click

            raise click.ClickException(
                "Missing environment variables:\n"
                + "".join(f"  - {v}\n" for v in missing)
                + '\nRun "dga env" to generate a .env template.'
            )
        return cls(
            s3_endpoint=os.environ["S3_ENDPOINT"],
            s3_access_key=os.environ["S3_ACCESS_KEY"],
            s3_secret_key=os.environ["S3_SECRET_KEY"],
            s3_bucket_name=os.environ["S3_BUCKET_NAME"],
            s3_data_path=os.environ["S3_DATA_PATH"],
            s3_use_ssl=os.environ.get("S3_USE_SSL", "false").lower() == "true",
            s3_region=os.environ.get("S3_REGION", "nbg1"),
            postgres_host=os.environ["POSTGRES_HOST"],
            postgres_db_password=os.environ["POSTGRES_DB_PASSWORD"],
        )
