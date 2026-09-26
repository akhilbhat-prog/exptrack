"""
Tests for the history Flask blueprint.

Auth tests use no DB.
API route tests mock db.get_connection() to avoid requiring a real DB.
"""

import os
from datetime import date as _date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from history import history_bp

_TEMPLATES = os.path.join(os.path.dirname(__file__), "..", "templates")


@pytest.fixture
def app():
    a = Flask(__name__, template_folder=_TEMPLATES)
    a.register_blueprint(history_bp)
    a.config["TESTING"] = True
    return a


@pytest.fixture
def client(app):
    return app.test_client()


def _make_mock_conn(fetchone=None, fetchall=None, rowcount=1):
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = fetchone
    mock_cursor.fetchall.return_value = fetchall or []
    mock_cursor.rowcount = rowcount
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=False)
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    return mock_conn, mock_cursor


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class TestRequireToken:
    def test_no_token_env_allows_access(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn(fetchall=[])
        with patch("db.get_connection", return_value=mock_conn):
            resp = client.get("/api/history/periods")
        assert resp.status_code == 200

    def test_token_env_set_blocks_without_token(self, client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "secret")
        resp = client.get("/api/history/periods")
        assert resp.status_code == 401

    def test_correct_query_param_grants_access(self, client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "secret")
        mock_conn, _ = _make_mock_conn(fetchall=[])
        with patch("db.get_connection", return_value=mock_conn):
            resp = client.get("/api/history/periods?token=secret")
        assert resp.status_code == 200

    def test_correct_bearer_header_grants_access(self, client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "secret")
        mock_conn, _ = _make_mock_conn(fetchall=[])
        with patch("db.get_connection", return_value=mock_conn):
            resp = client.get("/api/history/periods", headers={"Authorization": "Bearer secret"})
        assert resp.status_code == 200

    def test_api_periods_requires_token(self, client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "tok")
        resp = client.get("/api/history/periods")
        assert resp.status_code == 401

    def test_api_history_requires_token(self, client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "tok")
        resp = client.get("/api/history?period=May-2026")
        assert resp.status_code == 401

    def test_api_patch_requires_token(self, client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "tok")
        resp = client.patch("/api/history/1", json={})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/history/periods
# ---------------------------------------------------------------------------

class TestListPeriods:
    def test_returns_200(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, mock_cursor = _make_mock_conn(fetchall=[("May-2026", 45), ("Apr-2026", 30)])
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.get_history_periods", return_value=[
                 {"period": "May-2026", "count": 45},
                 {"period": "Apr-2026", "count": 30},
             ]):
            resp = client.get("/api/history/periods")
        assert resp.status_code == 200

    def test_returns_list_of_period_dicts(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.get_history_periods", return_value=[
                 {"period": "May-2026", "count": 10},
             ]):
            data = client.get("/api/history/periods").get_json()
        assert isinstance(data, list)
        assert data[0]["period"] == "May-2026"
        assert data[0]["count"] == 10

    def test_returns_empty_list_when_no_history(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.get_history_periods", return_value=[]):
            data = client.get("/api/history/periods").get_json()
        assert data == []


# ---------------------------------------------------------------------------
# GET /api/history
# ---------------------------------------------------------------------------

class TestListHistory:
    def test_missing_period_returns_empty(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        resp = client.get("/api/history")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_returns_paginated_shape(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        page_result = {
            "items": [{"id": 1, "time_period": "May-2026", "amount": 100.0}],
            "total": 1, "page": 1, "pages": 1,
        }
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.get_history_page", return_value=page_result):
            data = client.get("/api/history?period=May-2026").get_json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "pages" in data

    def test_page_defaults_to_1(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        captured = {}
        def fake_page(conn, period, page, page_size=25):
            captured["page"] = page
            return {"items": [], "total": 0, "page": page, "pages": 1}
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.get_history_page", side_effect=fake_page):
            client.get("/api/history?period=May-2026")
        assert captured["page"] == 1

    def test_page_param_is_forwarded(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        captured = {}
        def fake_page(conn, period, page, page_size=25):
            captured["page"] = page
            return {"items": [], "total": 0, "page": page, "pages": 3}
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.get_history_page", side_effect=fake_page):
            client.get("/api/history?period=May-2026&page=2")
        assert captured["page"] == 2


# ---------------------------------------------------------------------------
# PATCH /api/history/<id>
# ---------------------------------------------------------------------------

class TestUpdateHistory:
    _payload = {
        "time_period": "May-2026",
        "category": "Food",
        "sub_category": "Eating Out",
        "spend_type": "Expense",
        "cadence": "O",
        "divide_by": 1,
        "shared_expense": "N",
        "share_ratio": 1.0,
    }

    def test_returns_200_with_computed_amounts(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.update_history_row",
                   return_value={
                       "amount": 100.0, "monthly_amount": 100.0, "final_amount": 100.0,
                       "category": "Food", "sub_category": "Eating Out", "spend_type": "Expense",
                       "cadence": "O", "divide_by": 1, "shared_expense": "N", "share_ratio": 1.0,
                   }):
            resp = client.patch("/api/history/1", json=self._payload)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert "monthly_amount" in data
        assert "final_amount" in data

    def test_returns_404_when_row_not_found(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.update_history_row", return_value=None):
            resp = client.patch("/api/history/999", json=self._payload)
        assert resp.status_code == 404

    def test_divide_by_clamped_to_1(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        captured = {}
        def fake_update(conn, row_id, fields):
            captured["fields"] = fields
            return {
                "amount": 100.0, "monthly_amount": 100.0, "final_amount": 100.0,
                "category": "Food", "sub_category": "Eating Out", "spend_type": "Expense",
                "cadence": "O", "divide_by": 1, "shared_expense": "N", "share_ratio": 1.0,
            }
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.update_history_row", side_effect=fake_update):
            client.patch("/api/history/1", json={**self._payload, "divide_by": 0})
        assert captured["fields"]["divide_by"] >= 1

    def test_shared_expense_uppercased(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        captured = {}
        def fake_update(conn, row_id, fields):
            captured["fields"] = fields
            return {
                "amount": 50.0, "monthly_amount": 50.0, "final_amount": 25.0,
                "category": "Food", "sub_category": "Eating Out", "spend_type": "Expense",
                "cadence": "O", "divide_by": 1, "shared_expense": "Y", "share_ratio": 0.5,
            }
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.update_history_row", side_effect=fake_update):
            client.patch("/api/history/1", json={**self._payload, "shared_expense": "y"})
        assert captured["fields"]["shared_expense"] == "Y"

    def test_sequential_partial_patches_preserve_untouched_fields_end_to_end(self, client, monkeypatch):
        """Regression test for the real bug: PATCHing category then spend_type through the
        real db.update_history_row (not mocked) must not blank out sub_category/spend_type/category
        along the way, mirroring the actual View-page save-one-field-at-a-time flow."""
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        state = {
            "amount": Decimal("100.00"), "time_period": "May-2026",
            "category": "Food", "sub_category": "Eating Out", "spend_type": "Expense",
            "cadence": "O", "divide_by": 1, "shared_expense": "N", "share_ratio": Decimal("1.0"),
        }

        def fetchone_side_effect():
            return (
                state["amount"], state["time_period"], state["category"], state["sub_category"],
                state["spend_type"], state["cadence"], state["divide_by"], state["shared_expense"],
                state["share_ratio"],
            )

        mock_cursor = MagicMock()
        mock_cursor.fetchone.side_effect = lambda: fetchone_side_effect()
        mock_cursor.rowcount = 1
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        def fake_execute(sql, params=None):
            if sql.strip().startswith("UPDATE data_feed_history"):
                (state["amount"], state["time_period"], state["category"], state["sub_category"],
                 state["spend_type"], state["cadence"], state["divide_by"], state["shared_expense"],
                 state["share_ratio"], _monthly, _final, _row_id) = params
        mock_cursor.execute.side_effect = fake_execute

        with patch("history.db.get_connection", return_value=mock_conn):
            client.patch("/api/history/1", json={"category": "Travel"})
            resp = client.patch("/api/history/1", json={"spend_type": "Investment"})

        assert resp.status_code == 200
        assert state["category"] == "Travel"
        assert state["sub_category"] == "Eating Out"
        assert state["spend_type"] == "Investment"


# ---------------------------------------------------------------------------
# DELETE /api/history/<id>
# ---------------------------------------------------------------------------

class TestDeleteHistory:
    def test_delete_returns_204(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.delete_history_row", return_value=True):
            resp = client.delete("/api/history/1")
        assert resp.status_code == 204

    def test_delete_returns_404_when_not_found(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.delete_history_row", return_value=False):
            resp = client.delete("/api/history/999")
        assert resp.status_code == 404

    def test_delete_requires_token(self, client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "tok")
        resp = client.delete("/api/history/1")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/history
# ---------------------------------------------------------------------------

class TestCreateHistoryRow:
    _payload = {
        "entry_date": "2026-05-20",
        "entry_text": "Cash payment at pharmacy",
        "amount": 350.0,
        "merchant": "Apollo Pharmacy",
        "category": "Health",
        "sub_category": "Medicine",
        "spend_type": "Expense",
    }

    def test_creates_row_returns_201(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.create_data_feed_table"), \
             patch("history.db.insert_data_feed_row", return_value=42):
            resp = client.post("/api/history", json=self._payload)
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["ok"] is True
        assert data["id"] == 42

    def test_rejects_missing_entry_date(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        payload = {**self._payload, "entry_date": ""}
        resp = client.post("/api/history", json=payload)
        assert resp.status_code == 400

    def test_rejects_missing_entry_text(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        payload = {k: v for k, v in self._payload.items() if k != "entry_text"}
        resp = client.post("/api/history", json=payload)
        assert resp.status_code == 400

    def test_rejects_missing_amount(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        payload = {k: v for k, v in self._payload.items() if k != "amount"}
        resp = client.post("/api/history", json=payload)
        assert resp.status_code == 400

    def test_passes_exclude_from_training_true(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        captured = {}
        def fake_insert(conn, *args, **kwargs):
            captured["kwargs"] = kwargs
            return 99
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.create_data_feed_table"), \
             patch("history.db.insert_data_feed_row", side_effect=fake_insert):
            client.post("/api/history", json=self._payload)
        assert captured["kwargs"].get("exclude_from_training") is True

    def test_requires_token_when_set(self, client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "tok")
        resp = client.post("/api/history", json=self._payload)
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/history â€” cadence A multi-period insert
# ---------------------------------------------------------------------------

class TestCreateHistoryRowCadenceA:
    _base = {
        "entry_date": "2026-05-20",
        "entry_text": "Annual subscription",
        "amount": 12000.0,
        "cadence": "A",
        "divide_by": 12,
    }

    def test_cadence_A_creates_N_rows(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        mock_insert = MagicMock(side_effect=list(range(1, 13)))
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.create_data_feed_table"), \
             patch("history.db.insert_data_feed_row", mock_insert):
            resp = client.post("/api/history", json=self._base)
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["ok"] is True
        assert data["count"] == 12
        assert len(data["ids"]) == 12
        assert mock_insert.call_count == 12

    def test_cadence_A_divide_by_3_creates_3_rows(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        mock_insert = MagicMock(side_effect=[10, 11, 12])
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.create_data_feed_table"), \
             patch("history.db.insert_data_feed_row", mock_insert):
            resp = client.post("/api/history", json={**self._base, "divide_by": 3})
        assert resp.status_code == 201
        assert resp.get_json()["count"] == 3
        assert mock_insert.call_count == 3

    def test_cadence_A_divide_by_1_uses_single_path(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        mock_insert = MagicMock(return_value=5)
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.create_data_feed_table"), \
             patch("history.db.insert_data_feed_row", mock_insert):
            resp = client.post("/api/history", json={**self._base, "divide_by": 1})
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["count"] == 1
        assert "id" in data
        assert mock_insert.call_count == 1

    def test_cadence_O_divide_by_3_uses_single_path(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        mock_insert = MagicMock(return_value=7)
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.create_data_feed_table"), \
             patch("history.db.insert_data_feed_row", mock_insert):
            resp = client.post("/api/history", json={
                "entry_date": "2026-05-20", "entry_text": "One-off", "amount": 300.0,
                "cadence": "O", "divide_by": 3,
            })
        assert resp.status_code == 201
        assert resp.get_json()["count"] == 1
        assert mock_insert.call_count == 1

    def test_cadence_A_stores_full_amount_not_divided_amount(self, client, monkeypatch):
        """Regression test: every row created for a cadence='A' entry must store the
        full lump-sum amount (constant across the series) in the amount column -
        monthly_amount is the derived, divided figure, computed separately."""
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        mock_insert = MagicMock(side_effect=list(range(1, 13)))
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.create_data_feed_table"), \
             patch("history.db.insert_data_feed_row", mock_insert):
            resp = client.post("/api/history", json=self._base)
        assert resp.status_code == 201
        for call in mock_insert.call_args_list:
            amount_arg = call.args[6]
            assert amount_arg == 12000.0
            assert call.kwargs["monthly_amount"] == 1000.0

    def test_cadence_A_entry_dates_and_time_periods(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        calls_data = []
        def capture(conn, entry_date, entry_text, *args, **kwargs):
            calls_data.append({"entry_date": entry_date, "time_period": kwargs.get("time_period")})
            return len(calls_data)
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.create_data_feed_table"), \
             patch("history.db.insert_data_feed_row", side_effect=capture):
            client.post("/api/history", json=self._base)
        assert len(calls_data) == 12
        assert calls_data[0]["entry_date"] == _date(2026, 5, 20)
        assert calls_data[0]["time_period"] == "May-2026"
        assert calls_data[1]["entry_date"] == _date(2026, 6, 1)
        assert calls_data[1]["time_period"] == "Jun-2026"
        assert calls_data[11]["entry_date"] == _date(2027, 4, 1)
        assert calls_data[11]["time_period"] == "Apr-2027"

    def test_cadence_A_year_wrap(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        calls_data = []
        def capture(conn, entry_date, *args, **kwargs):
            calls_data.append({"entry_date": entry_date, "time_period": kwargs.get("time_period")})
            return len(calls_data)
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.create_data_feed_table"), \
             patch("history.db.insert_data_feed_row", side_effect=capture):
            client.post("/api/history", json={
                "entry_date": "2026-12-15", "entry_text": "Annual fee",
                "amount": 12000.0, "cadence": "A", "divide_by": 12,
            })
        assert calls_data[0]["entry_date"] == _date(2026, 12, 15)
        assert calls_data[0]["time_period"] == "Dec-2026"
        assert calls_data[1]["entry_date"] == _date(2027, 1, 1)
        assert calls_data[1]["time_period"] == "Jan-2027"
        assert calls_data[11]["entry_date"] == _date(2027, 11, 1)
        assert calls_data[11]["time_period"] == "Nov-2027"


# ---------------------------------------------------------------------------
# PATCH /api/history/<id> â€” cadence A expansion on update
# ---------------------------------------------------------------------------

class TestUpdateHistoryCadenceA:
    _existing = {
        "id": 1,
        "entry_text": "Annual subscription",
        "entry_date": _date(2026, 5, 1),
        "time_period": "May-2026",
        "merchant": "Acme Corp",
    }
    _patch_payload = {
        "amount": 3000.0,
        "cadence": "A",
        "divide_by": 3,
        "time_period": "May-2026",
        "category": "Expense",
        "sub_category": "Subscription",
        "spend_type": "Expense",
        "shared_expense": "N",
        "share_ratio": 1.0,
    }

    def test_annual_cadence_creates_future_rows(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, mock_cursor = _make_mock_conn()
        insert_calls = []
        def fake_insert(conn, entry_date, *args, **kwargs):
            insert_calls.append({"entry_date": entry_date, "time_period": kwargs.get("time_period")})
            return len(insert_calls) + 10
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.update_history_row",
                   return_value={
                       "amount": 1000.0, "monthly_amount": 1000.0, "final_amount": 1000.0,
                       "category": "Expense", "sub_category": "Subscription", "spend_type": "Expense",
                       "cadence": "A", "divide_by": 3, "shared_expense": "N", "share_ratio": 1.0,
                   }), \
             patch("history.db.get_history_row", return_value=self._existing), \
             patch("history.db.insert_data_feed_row", side_effect=fake_insert):
            resp = client.patch("/api/history/1", json=self._patch_payload)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["rows_created"] == 2
        assert len(insert_calls) == 2

    def test_future_rows_store_full_amount_not_monthly_amount(self, client, monkeypatch):
        """Regression test: auto-generated future-month rows must store the full
        lump-sum amount (constant across the series), not the divided monthly_amount,
        in their amount column - this was a real bug that corrupted real data."""
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        insert_calls = []
        def fake_insert(conn, entry_date, entry_text, sub_category, category, spend_type, amount, **kwargs):
            insert_calls.append({"amount": amount, "monthly_amount": kwargs.get("monthly_amount")})
            return len(insert_calls) + 10
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.update_history_row",
                   return_value={
                       "amount": 66000.0, "monthly_amount": 22000.0, "final_amount": 22000.0,
                       "category": "Bills", "sub_category": "School Fees", "spend_type": "Expense",
                       "cadence": "A", "divide_by": 3, "shared_expense": "N", "share_ratio": 1.0,
                   }), \
             patch("history.db.get_history_row", return_value=self._existing), \
             patch("history.db.insert_data_feed_row", side_effect=fake_insert):
            resp = client.patch("/api/history/1", json=self._patch_payload)
        assert resp.status_code == 200
        assert len(insert_calls) == 2
        for call in insert_calls:
            assert call["amount"] == 66000.0
            assert call["monthly_amount"] == 22000.0

    def test_delete_scoped_to_merchant_and_category_not_just_entry_text(self, client, monkeypatch):
        """Regression test: the future-rows cleanup must not delete sibling recurring
        items that happen to share the same entry_text (e.g. multiple subscriptions
        all filed under "Online Learning") - it must also match merchant/category/
        sub_category. This is the bug that let fixing one subscription silently wipe
        out another's future rows with no replacement."""
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, mock_cursor = _make_mock_conn()
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.update_history_row",
                   return_value={
                       "amount": 1000.0, "monthly_amount": 1000.0, "final_amount": 1000.0,
                       "category": "Expense", "sub_category": "Subscription", "spend_type": "Expense",
                       "cadence": "A", "divide_by": 3, "shared_expense": "N", "share_ratio": 1.0,
                   }), \
             patch("history.db.get_history_row", return_value=self._existing), \
             patch("history.db.insert_data_feed_row", return_value=99) as mock_insert:
            client.patch("/api/history/1", json=self._patch_payload)
        delete_calls = [c for c in mock_cursor.execute.call_args_list if "DELETE FROM data_feed_history" in c[0][0]]
        assert len(delete_calls) == 1
        delete_sql, delete_params = delete_calls[0][0]
        assert "merchant IS NOT DISTINCT FROM" in delete_sql
        assert "category IS NOT DISTINCT FROM" in delete_sql
        assert "sub_category IS NOT DISTINCT FROM" in delete_sql
        assert self._existing["merchant"] in delete_params
        # merchant must also be carried through to the recreated rows
        assert mock_insert.call_args.kwargs["merchant"] == self._existing["merchant"]

    def test_future_row_entry_dates_are_first_of_month(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        insert_calls = []
        def fake_insert(conn, entry_date, *args, **kwargs):
            insert_calls.append({"entry_date": entry_date, "time_period": kwargs.get("time_period")})
            return len(insert_calls)
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.update_history_row",
                   return_value={
                       "amount": 1000.0, "monthly_amount": 1000.0, "final_amount": 1000.0,
                       "category": "Expense", "sub_category": "Subscription", "spend_type": "Expense",
                       "cadence": "A", "divide_by": 3, "shared_expense": "N", "share_ratio": 1.0,
                   }), \
             patch("history.db.get_history_row", return_value=self._existing), \
             patch("history.db.insert_data_feed_row", side_effect=fake_insert):
            client.patch("/api/history/1", json=self._patch_payload)
        assert insert_calls[0]["entry_date"] == _date(2026, 6, 1)
        assert insert_calls[0]["time_period"] == "Jun-2026"
        assert insert_calls[1]["entry_date"] == _date(2026, 7, 1)
        assert insert_calls[1]["time_period"] == "Jul-2026"

    def test_future_rows_not_in_base_period(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        insert_calls = []
        def fake_insert(conn, entry_date, *args, **kwargs):
            insert_calls.append(kwargs.get("time_period"))
            return len(insert_calls)
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.update_history_row",
                   return_value={
                       "amount": 1000.0, "monthly_amount": 1000.0, "final_amount": 1000.0,
                       "category": "Expense", "sub_category": "Subscription", "spend_type": "Expense",
                       "cadence": "A", "divide_by": 3, "shared_expense": "N", "share_ratio": 1.0,
                   }), \
             patch("history.db.get_history_row", return_value=self._existing), \
             patch("history.db.insert_data_feed_row", side_effect=fake_insert):
            client.patch("/api/history/1", json=self._patch_payload)
        assert "May-2026" not in insert_calls

    def test_annual_cadence_divide_by_1_no_expansion(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.update_history_row",
                   return_value={
                       "amount": 3000.0, "monthly_amount": 3000.0, "final_amount": 3000.0,
                       "category": "Expense", "sub_category": "Subscription", "spend_type": "Expense",
                       "cadence": "A", "divide_by": 1, "shared_expense": "N", "share_ratio": 1.0,
                   }), \
             patch("history.db.get_history_row", return_value=self._existing), \
             patch("history.db.insert_data_feed_row") as mock_insert:
            resp = client.patch("/api/history/1", json={**self._patch_payload, "divide_by": 1})
        assert resp.status_code == 200
        mock_insert.assert_not_called()
        assert resp.get_json()["rows_created"] == 0

    def test_non_annual_cadence_no_expansion(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.update_history_row",
                   return_value={
                       "amount": 1000.0, "monthly_amount": 1000.0, "final_amount": 1000.0,
                       "category": "Expense", "sub_category": "Subscription", "spend_type": "Expense",
                       "cadence": "M", "divide_by": 3, "shared_expense": "N", "share_ratio": 1.0,
                   }), \
             patch("history.db.get_history_row", return_value=self._existing), \
             patch("history.db.insert_data_feed_row") as mock_insert:
            resp = client.patch("/api/history/1", json={**self._patch_payload, "cadence": "M"})
        assert resp.status_code == 200
        mock_insert.assert_not_called()
        assert resp.get_json()["rows_created"] == 0

    def test_unrelated_field_edit_does_not_trigger_expansion(self, client, monkeypatch):
        """Regression test: PATCHing sub_category on a row that already has cadence='A',
        divide_by>1 must NOT delete/regenerate future months' rows. This is the exact
        incident where fixing a miscategorized recurring row destroyed 9 months of
        correct data and replaced it with wrongly-divided amounts."""
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.update_history_row",
                   return_value={
                       "amount": 21000.0, "monthly_amount": 1750.0, "final_amount": 1750.0,
                       "category": "Bills", "sub_category": "Tax", "spend_type": "Expense",
                       "cadence": "A", "divide_by": 12, "shared_expense": "N", "share_ratio": 1.0,
                   }), \
             patch("history.db.get_history_row") as mock_get_row, \
             patch("history.db.insert_data_feed_row") as mock_insert:
            resp = client.patch("/api/history/1", json={"sub_category": "Tax"})
        assert resp.status_code == 200
        assert resp.get_json()["rows_created"] == 0
        mock_get_row.assert_not_called()
        mock_insert.assert_not_called()

    def test_year_wrap_creates_correct_periods(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        dec_existing = {
            "id": 5, "entry_text": "Annual fee",
            "entry_date": _date(2026, 12, 1), "time_period": "Dec-2026",
            "merchant": "Acme Corp",
        }
        insert_calls = []
        def fake_insert(conn, entry_date, *args, **kwargs):
            insert_calls.append({"entry_date": entry_date, "time_period": kwargs.get("time_period")})
            return len(insert_calls)
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.update_history_row",
                   return_value={
                       "amount": 1000.0, "monthly_amount": 1000.0, "final_amount": 1000.0,
                       "category": "Expense", "sub_category": "Subscription", "spend_type": "Expense",
                       "cadence": "A", "divide_by": 3, "shared_expense": "N", "share_ratio": 1.0,
                   }), \
             patch("history.db.get_history_row", return_value=dec_existing), \
             patch("history.db.insert_data_feed_row", side_effect=fake_insert):
            client.patch("/api/history/5", json={**self._patch_payload, "divide_by": 3})
        assert insert_calls[0]["entry_date"] == _date(2027, 1, 1)
        assert insert_calls[0]["time_period"] == "Jan-2027"
        assert insert_calls[1]["entry_date"] == _date(2027, 2, 1)
        assert insert_calls[1]["time_period"] == "Feb-2027"


# ---------------------------------------------------------------------------
# GET /api/settings + PATCH /api/settings
# ---------------------------------------------------------------------------

class TestSettings:
    def test_get_returns_defaults(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        defaults = {"default_share_ratio": 0.7, "default_annual_divisor": 12}
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.get_settings", return_value=defaults):
            resp = client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["default_share_ratio"] == 0.7
        assert data["default_annual_divisor"] == 12

    def test_get_requires_token(self, client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "tok")
        assert client.get("/api/settings").status_code == 401

    def test_patch_updates_share_ratio(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        updated = {"default_share_ratio": 0.5, "default_annual_divisor": 12}
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.update_setting") as mock_update, \
             patch("history.db.get_settings", return_value=updated):
            resp = client.patch("/api/settings", json={"default_share_ratio": 0.5})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["default_share_ratio"] == 0.5
        mock_update.assert_called_once_with(mock_conn, "default_share_ratio", "0.5")

    def test_patch_updates_annual_divisor(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        updated = {"default_share_ratio": 0.7, "default_annual_divisor": 4}
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.update_setting") as mock_update, \
             patch("history.db.get_settings", return_value=updated):
            resp = client.patch("/api/settings", json={"default_annual_divisor": 4})
        assert resp.status_code == 200
        mock_update.assert_called_once_with(mock_conn, "default_annual_divisor", "4")

    def test_patch_rejects_invalid_share_ratio(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        resp = client.patch("/api/settings", json={"default_share_ratio": 1.5})
        assert resp.status_code == 400

    def test_patch_rejects_zero_divisor(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        resp = client.patch("/api/settings", json={"default_annual_divisor": 0})
        assert resp.status_code == 400

    def test_patch_rejects_unknown_keys(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        resp = client.patch("/api/settings", json={"unknown_key": "value"})
        assert resp.status_code == 400

    def test_patch_updates_shared_backfill_floor(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        updated = {"default_share_ratio": 0.7, "default_annual_divisor": 12, "shared_backfill_floor": "2026-10-01"}
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.update_setting") as mock_update, \
             patch("history.db.get_settings", return_value=updated):
            resp = client.patch("/api/settings", json={"shared_backfill_floor": "2026-10-01"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["shared_backfill_floor"] == "2026-10-01"
        mock_update.assert_called_once_with(mock_conn, "shared_backfill_floor", "2026-10-01")

    def test_patch_rejects_invalid_shared_backfill_floor_format(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        resp = client.patch("/api/settings", json={"shared_backfill_floor": "not-a-date"})
        assert resp.status_code == 400

    def test_patch_rejects_shared_backfill_floor_before_scope_start(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        resp = client.patch("/api/settings", json={"shared_backfill_floor": "2026-01-01"})
        assert resp.status_code == 400

    def test_patch_requires_token(self, client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "tok")
        assert client.patch("/api/settings", json={"default_share_ratio": 0.5}).status_code == 401


# ---------------------------------------------------------------------------
# GET /api/history/summary
# ---------------------------------------------------------------------------

class TestHistorySummary:
    def _summary(self, **overrides):
        base = {
            "top_categories": [
                {"category": "Food", "total": 5000.0, "count": 10},
                {"category": "Transport", "total": 3000.0, "count": 5},
            ],
            "period_total": 8000.0,
        }
        return {**base, **overrides}

    def test_returns_200_and_shape(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.get_history_summary", return_value=self._summary()):
            resp = client.get("/api/history/summary?period=May-2026")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "top_categories" in data
        assert "period_total" in data
        assert data["period_total"] == 8000.0
        assert len(data["top_categories"]) == 2

    def test_missing_period_returns_empty(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        resp = client.get("/api/history/summary")
        assert resp.status_code == 200
        assert resp.get_json()["top_categories"] == []

    def test_forwards_prev_period_param(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        captured = {}
        def fake_summary(conn, period, prev_period=None):
            captured["prev_period"] = prev_period
            return self._summary()
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.get_history_summary", side_effect=fake_summary):
            client.get("/api/history/summary?period=May-2026&prev_period=Apr-2026")
        assert captured["prev_period"] == "Apr-2026"

    def test_requires_token(self, client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "tok")
        assert client.get("/api/history/summary?period=May-2026").status_code == 401

    def test_omitted_prev_period_passes_none(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        captured = {}
        def fake_summary(conn, period, prev_period=None):
            captured["prev_period"] = prev_period
            return self._summary()
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.get_history_summary", side_effect=fake_summary):
            client.get("/api/history/summary?period=May-2026")
        assert captured["prev_period"] is None


# ---------------------------------------------------------------------------
# Cadence-A series: confirmed deletes, series-aware re-spread
# ---------------------------------------------------------------------------

class TestDeleteSeries:
    _info = {"series_id": "s1", "count": 12, "is_first": False}

    def test_series_row_without_confirm_returns_409_and_deletes_nothing(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.get_series_info", return_value=self._info), \
             patch("history.db.delete_history_row") as delete_row, \
             patch("history.db.delete_series") as delete_series:
            resp = client.delete("/api/history/5")
        assert resp.status_code == 409
        body = resp.get_json()
        assert body["requires_confirmation"] is True
        assert body["series_count"] == 12 and body["is_first"] is False
        delete_row.assert_not_called()
        delete_series.assert_not_called()

    def test_confirmed_first_entry_deletes_whole_series(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.get_series_info", return_value={**self._info, "is_first": True}), \
             patch("history.db.delete_series", return_value=12) as delete_series:
            resp = client.delete("/api/history/5?confirm=1")
        assert resp.status_code == 200
        delete_series.assert_called_once_with(mock_conn, "s1")
        assert resp.get_json()["deleted"] == 12

    def test_confirmed_later_entry_recalculates_remaining(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.get_series_info", return_value=self._info), \
             patch("history.db.remove_series_row_and_recalc", return_value=11) as remove:
            resp = client.delete("/api/history/5?confirm=1")
        assert resp.status_code == 200
        remove.assert_called_once_with(mock_conn, 5, "s1")
        assert resp.get_json()["series_remaining"] == 11


class TestSeriesRespread:
    _existing = {"id": 1, "entry_text": "Ins", "entry_date": _date(2026, 5, 1),
                 "time_period": "May-2026", "merchant": "Acme"}
    _result = {"amount": 1400.0, "monthly_amount": 100.0, "final_amount": 100.0,
               "category": "Bills", "sub_category": "Ins", "spend_type": "Expense",
               "cadence": "A", "divide_by": 14, "shared_expense": "Y", "share_ratio": 1.0}

    def test_known_series_is_respread_with_merchant_and_no_text_match_delete(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, mock_cursor = _make_mock_conn()
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.update_history_row", return_value=self._result), \
             patch("history.db.get_history_row", return_value=self._existing), \
             patch("history.db.get_series_id", return_value="s1"), \
             patch("history.db.respread_series", return_value={"created": [9, 10], "deleted": []}) as respread:
            resp = client.patch("/api/history/1", json={"divide_by": 14})
        assert resp.status_code == 200
        assert resp.get_json()["rows_created"] == 2
        args = respread.call_args[0]
        assert args[1:4] == ("s1", 1400.0, 14)
        assert args[4]["merchant"] == "Acme" and args[4]["keep_id"] == 1
        assert not [c for c in mock_cursor.execute.call_args_list if "DELETE FROM data_feed_history" in c[0][0]]

    def test_shrink_past_own_position_is_rejected(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.update_history_row", return_value=self._result), \
             patch("history.db.get_history_row", return_value=self._existing), \
             patch("history.db.get_series_id", return_value="s1"), \
             patch("history.db.respread_series", side_effect=ValueError("too small")):
            resp = client.patch("/api/history/1", json={"divide_by": 2})
        assert resp.status_code == 400

    def test_legacy_row_starts_a_series_and_creates_stamped_rows_with_shared_merchant(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        result = {**self._result, "divide_by": 3}
        inserts = []
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.update_history_row", return_value=result), \
             patch("history.db.get_history_row", return_value=self._existing), \
             patch("history.db.get_series_id", return_value=None), \
             patch("history.db.set_series_id") as set_sid, \
             patch("history.db.insert_data_feed_row", side_effect=lambda *a, **k: inserts.append(k) or 50 + len(inserts)), \
             patch("history.db.upsert_shared_transaction") as upsert:
            resp = client.patch("/api/history/1", json={"divide_by": 3})
        assert resp.status_code == 200
        sid = set_sid.call_args[0][2]
        assert sid and all(k["series_id"] == sid for k in inserts) and len(inserts) == 2
        # merchant (previously None) reaches the shared mirror of each new month
        new_month_upserts = [c for c in upsert.call_args_list if c[0][1] in (51, 52)]
        assert len(new_month_upserts) == 2 and all(c[0][6] == "Acme" for c in new_month_upserts)

    def test_create_stamps_one_series_id_on_all_rows(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        inserts = []
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.create_data_feed_table"), \
             patch("history.db.insert_data_feed_row", side_effect=lambda *a, **k: inserts.append(k) or len(inserts)):
            resp = client.post("/api/history", json={
                "entry_date": "2026-05-10", "entry_text": "Ins", "amount": 1400, "cadence": "A", "divide_by": 14})
        assert resp.status_code == 201 and len(inserts) == 14
        assert len({k["series_id"] for k in inserts}) == 1 and inserts[0]["series_id"]
