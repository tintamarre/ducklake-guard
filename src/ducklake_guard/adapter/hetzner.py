from __future__ import annotations

from minio import Minio

from ducklake_guard.config import Config


def create_s3_client(config: Config) -> Minio:
    return Minio(
        config.s3_endpoint,
        access_key=config.s3_access_key,
        secret_key=config.s3_secret_key,
        secure=config.s3_use_ssl,
        region=config.s3_region,
    )
