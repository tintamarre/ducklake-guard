from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ducklake_guard.transaction import apply_with_policy_sync


class TestPolicySizeLimit:
    @patch("ducklake_guard.transaction.insert_policy_log")
    @patch("ducklake_guard.transaction.sync_rls_policies")
    @patch("ducklake_guard.transaction.build_policy")
    @patch("ducklake_guard.transaction.fetch_all_users", return_value={})
    @patch("ducklake_guard.transaction.fetch_all_grants", return_value=[])
    def test_raises_when_policy_exceeds_1mb(
        self, _grants, _users, mock_policy, _rls, _log
    ):
        mock_policy.return_value = {
            "Version": "2012-10-17",
            "Statement": [{"Sid": "x" * 1_100_000}],
        }

        guard = MagicMock()
        guard.transaction.return_value.__enter__ = MagicMock()
        guard.transaction.return_value.__exit__ = MagicMock(return_value=False)
        guard.cursor.return_value = MagicMock()

        mutate = MagicMock(return_value={"action": "allow", "user_name": "a"})

        with pytest.raises(ValueError, match="exceeds 1 MB"):
            apply_with_policy_sync(guard, MagicMock(), MagicMock(), "bucket", mutate)
