"""
Tests for pure utility functions in categorizer/ingestion/database.py.

Covers: _normalize_database_frame, build_database_url.
No real database connections are made.
"""

import pandas as pd
import pytest

from ingestion.database import OUTPUT_COLUMNS, _normalize_database_frame, build_database_url


def _base_df(**overrides) -> pd.DataFrame:
    """Minimal valid DataFrame matching the expected DB query output schema."""
    data = {
        "id": [1],
        "date": ["2026-05-01"],
        "entry_raw": ["ZOMATO FOOD ORDER"],
        "amount": ["200.50"],
        "final_category": ["Food"],
        "final_subcategory": ["Eating Out"],
        "final_type": ["Expense"],
        "created_at": ["2026-05-01T10:00:00"],
        "db_merchant": ["ZOMATO"],
        "vpa": ["zomato@paytm"],
        "upi_ref": ["ref001"],
    }
    data.update(overrides)
    return pd.DataFrame(data)


class TestNormalizeDatabaseFrame:
    def test_output_has_expected_columns(self):
        result = _normalize_database_frame(_base_df())
        assert list(result.columns) == OUTPUT_COLUMNS

    def test_missing_column_raises_value_error(self):
        df = pd.DataFrame({"id": [1], "date": ["2026-05-01"]})  # missing most columns
        with pytest.raises(ValueError, match="Missing required database columns"):
            _normalize_database_frame(df)

    def test_amount_is_numeric(self):
        result = _normalize_database_frame(_base_df())
        assert pd.api.types.is_numeric_dtype(result["amount"])
        assert float(result["amount"].iloc[0]) == pytest.approx(200.50)

    def test_string_columns_are_stripped(self):
        result = _normalize_database_frame(_base_df(final_category=["  Food  "]))
        assert result["final_category"].iloc[0] == "Food"

    def test_null_entry_raw_filled_with_empty_string(self):
        result = _normalize_database_frame(_base_df(entry_raw=[None]))
        assert result["entry_raw"].iloc[0] == ""


class TestBuildDatabaseUrl:
    def test_uses_database_url_env_var_directly(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host/db")
        assert build_database_url() == "postgresql://user:pass@host/db"

    def test_builds_url_from_individual_vars(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("DB_HOST", "myhost")
        monkeypatch.setenv("DB_PORT", "5432")
        monkeypatch.setenv("DB_NAME", "mydb")
        monkeypatch.setenv("DB_USER", "myuser")
        monkeypatch.setenv("DB_PASSWORD", "mypassword")
        url = build_database_url()
        assert "myhost" in url
        assert "mydb" in url
        assert "myuser" in url

    def test_raises_when_required_vars_missing(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        for var in ("DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD"):
            monkeypatch.delenv(var, raising=False)
        with pytest.raises(ValueError, match="incomplete"):
            build_database_url()
