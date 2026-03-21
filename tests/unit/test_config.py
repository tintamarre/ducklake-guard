from __future__ import annotations

import pytest

from ducklake_guard.config import Config

REQUIRED_ENV = {
    "S3_ENDPOINT": "https://s3.example.com",
    "S3_ACCESS_KEY": "AKID",
    "S3_SECRET_KEY": "secret",
    "S3_BUCKET_NAME": "my-bucket",
    "S3_DATA_PATH": "/data",
    "POSTGRES_HOST": "db.example.com",
    "POSTGRES_DB_PASSWORD": "pgpass",
}


class TestFromEnv:
    def test_all_vars_set(self, monkeypatch):
        for k, v in REQUIRED_ENV.items():
            monkeypatch.setenv(k, v)
        monkeypatch.setenv("S3_USE_SSL", "true")
        monkeypatch.setenv("S3_REGION", "us-east-1")

        cfg = Config.from_env()

        assert cfg.s3_endpoint == "https://s3.example.com"
        assert cfg.s3_access_key == "AKID"
        assert cfg.s3_secret_key == "secret"
        assert cfg.s3_bucket_name == "my-bucket"
        assert cfg.s3_data_path == "/data"
        assert cfg.s3_use_ssl is True
        assert cfg.s3_region == "us-east-1"
        assert cfg.postgres_host == "db.example.com"
        assert cfg.postgres_db_password == "pgpass"

    def test_missing_required_var_raises_key_error(self, monkeypatch):
        for k, v in REQUIRED_ENV.items():
            monkeypatch.setenv(k, v)
        monkeypatch.delenv("S3_ENDPOINT")

        with pytest.raises(KeyError):
            Config.from_env()


class TestS3UseSslDefault:
    def test_defaults_to_false(self, monkeypatch):
        for k, v in REQUIRED_ENV.items():
            monkeypatch.setenv(k, v)
        monkeypatch.delenv("S3_USE_SSL", raising=False)

        cfg = Config.from_env()
        assert cfg.s3_use_ssl is False

    @pytest.mark.parametrize("value", ["true", "True", "TRUE"])
    def test_parses_true_variants(self, monkeypatch, value):
        for k, v in REQUIRED_ENV.items():
            monkeypatch.setenv(k, v)
        monkeypatch.setenv("S3_USE_SSL", value)

        cfg = Config.from_env()
        assert cfg.s3_use_ssl is True

    def test_non_true_string_is_false(self, monkeypatch):
        for k, v in REQUIRED_ENV.items():
            monkeypatch.setenv(k, v)
        monkeypatch.setenv("S3_USE_SSL", "yes")

        cfg = Config.from_env()
        assert cfg.s3_use_ssl is False


class TestS3RegionDefault:
    def test_defaults_to_nbg1(self, monkeypatch):
        for k, v in REQUIRED_ENV.items():
            monkeypatch.setenv(k, v)
        monkeypatch.delenv("S3_REGION", raising=False)

        cfg = Config.from_env()
        assert cfg.s3_region == "nbg1"

    def test_custom_region(self, monkeypatch):
        for k, v in REQUIRED_ENV.items():
            monkeypatch.setenv(k, v)
        monkeypatch.setenv("S3_REGION", "eu-central-1")

        cfg = Config.from_env()
        assert cfg.s3_region == "eu-central-1"
