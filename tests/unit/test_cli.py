from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from ducklake_guard.cli import cli


def _make_config():
    cfg = MagicMock()
    cfg.postgres_host = "localhost"
    cfg.postgres_db_password = "secret"
    cfg.s3_bucket_name = "test-bucket"
    return cfg


@pytest.fixture
def infra():
    with (
        patch("ducklake_guard.cli.Config.from_env", return_value=_make_config()),
        patch("ducklake_guard.cli._guard_conn") as guard,
        patch("ducklake_guard.cli._catalog_conn") as catalog,
        patch("ducklake_guard.cli.create_s3_client"),
    ):
        yield guard, catalog


class TestHelp:
    def test_dga_help(self):
        result = CliRunner().invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Usage" in result.output


class TestInit:
    @patch("ducklake_guard.cli.subprocess.run")
    def test_init_success(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="CREATE TABLE\nGRANT", stderr=""
        )

        result = CliRunner().invoke(cli, ["init", "--ssh-host", "testhost"])
        assert result.exit_code == 0
        assert "Init complete" in result.output

    @patch("ducklake_guard.cli.subprocess.run")
    def test_init_ssh_failure(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="Connection refused"
        )

        result = CliRunner().invoke(cli, ["init", "--ssh-host", "badhost"])
        assert result.exit_code != 0
        assert "Connection refused" in result.output


class TestUserCreate:
    def test_creates_user_and_shows_password(self, infra):
        with (
            patch(
                "ducklake_guard.cli.create_catalog_role", return_value="gen-pass-123"
            ),
            patch("ducklake_guard.cli.apply_with_policy_sync"),
        ):
            result = CliRunner().invoke(
                cli,
                [
                    "user",
                    "create",
                    "alice",
                    "--access-key",
                    "AK123",
                    "--project-id",
                    "P1",
                ],
            )
            assert result.exit_code == 0
            assert "alice" in result.output
            assert "gen-pass-123" in result.output
            assert "Save this password now" in result.output

            init_file = Path("init-alice.sql")
            assert init_file.exists()
            content = init_file.read_text()
            assert "getenv('S3_ACCESS_KEY')" in content
            assert "getenv('DGA_CATALOG_PASSWORD')" in content
            assert "dga_alice" in content
            init_file.unlink()

    def test_missing_access_key(self):
        result = CliRunner().invoke(cli, ["user", "create", "alice"])
        assert result.exit_code != 0


class TestUserDelete:
    def test_user_not_found(self, infra):
        guard, _catalog = infra
        mock_conn = guard.return_value
        mock_conn.transaction.return_value.__enter__ = MagicMock()
        mock_conn.transaction.return_value.__exit__ = MagicMock(return_value=False)
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = None
        mock_conn.cursor.return_value = mock_cur

        with patch("ducklake_guard.cli.get_user", return_value=None):
            result = CliRunner().invoke(cli, ["user", "delete", "nonexistent"])
            assert result.exit_code != 0
            assert "not found" in result.output


class TestAllow:
    def test_missing_permission_flag(self, infra):
        result = CliRunner().invoke(cli, ["allow", "alice", "--table", "orders"])
        assert result.exit_code != 0
        assert "read-only" in result.output or "read-write" in result.output
