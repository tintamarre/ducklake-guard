from __future__ import annotations

from unittest.mock import MagicMock

from ducklake_guard.sync import _get_current_rls_tables


class TestGetCurrentRlsTables:
    def test_parses_array_format(self):
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = (
            "(table_name = ANY ('{customers,orders}'::text[]))",
        )

        assert _get_current_rls_tables(conn, "dga_alice_tables", "dga_alice") == [
            "customers",
            "orders",
        ]

    def test_parses_single_value_format(self):
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = (
            "((table_name)::text = 'customers'::text)",
        )

        assert _get_current_rls_tables(conn, "dga_alice_tables", "dga_alice") == [
            "customers"
        ]

    def test_returns_empty_when_no_policy(self):
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = None

        assert _get_current_rls_tables(conn, "dga_alice_tables", "dga_alice") == []
