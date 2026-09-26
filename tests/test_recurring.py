"""
Tests for the recurring transactions Flask blueprint and db helpers.

Auth tests use no DB.
API route tests mock db.get_connection() to avoid requiring a real DB.
generate_recurring_entries tests mock the connection directly.
"""

import os
from datetime import date as _date
from decimal import Decimal
from unittest.mock import MagicMock, call, patch

import pytest
from flask import Flask

from recurring import recurring_bp

_TEMPLATES = os.path.join(os.path.dirname(__file__), "..", "templates")


@pytest.fixture
def app():
    a = Flask(__name__, template_folder=_TEMPLATES)
    a.register_blueprint(recurring_bp)
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
    def test_no_token_env_allows_page(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn(fetchall=[])
        with patch("db.get_connection", return_value=mock_conn):
            resp = client.get("/api/recurring")
        assert resp.status_code == 200

    def test_token_env_blocks_page_without_token(self, client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "secret")
        resp = client.get("/api/recurring")
        assert resp.status_code == 401

    def test_correct_query_param_grants_page(self, client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "secret")
        mock_conn, _ = _make_mock_conn(fetchall=[])
        with patch("db.get_connection", return_value=mock_conn):
            resp = client.get("/api/recurring?token=secret")
        assert resp.status_code == 200

    def test_correct_bearer_header_grants_page(self, client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "secret")
        mock_conn, _ = _make_mock_conn(fetchall=[])
        with patch("db.get_connection", return_value=mock_conn):
            resp = client.get("/api/recurring", headers={"Authorization": "Bearer secret"})
        assert resp.status_code == 200

    def test_api_list_requires_token(self, client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "tok")
        assert client.get("/api/recurring").status_code == 401

    def test_api_create_requires_token(self, client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "tok")
        assert client.post("/api/recurring", json={}).status_code == 401

    def test_api_generate_requires_token(self, client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "tok")
        assert client.post("/api/recurring/generate").status_code == 401


# ---------------------------------------------------------------------------
# GET /api/recurring
# ---------------------------------------------------------------------------

class TestListRecurring:
    def test_returns_200_and_list(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        sample = [
            {"id": 1, "entry_text": "Groww SIP", "amount": 5000.0, "active": True},
            {"id": 2, "entry_text": "RD Transfer", "amount": 2000.0, "active": True},
        ]
        with patch("recurring.db.get_connection", return_value=mock_conn), \
             patch("recurring.db.get_recurring_transactions", return_value=sample):
            resp = client.get("/api/recurring")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)
        assert len(data) == 2

    def test_returns_empty_list(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        with patch("recurring.db.get_connection", return_value=mock_conn), \
             patch("recurring.db.get_recurring_transactions", return_value=[]):
            data = client.get("/api/recurring").get_json()
        assert data == []


# ---------------------------------------------------------------------------
# POST /api/recurring
# ---------------------------------------------------------------------------

class TestCreateRecurring:
    def test_creates_returns_201(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        with patch("recurring.db.get_connection", return_value=mock_conn), \
             patch("recurring.db.create_recurring_table"), \
             patch("recurring.db.upsert_recurring_transaction", return_value=7) as mock_upsert:
            resp = client.post("/api/recurring", json={"entry_text": "Groww SIP", "amount": 5000})
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["ok"] is True
        assert data["id"] == 7

    def test_rejects_missing_entry_text(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        resp = client.post("/api/recurring", json={"amount": 5000})
        assert resp.status_code == 400

    def test_rejects_missing_amount(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        resp = client.post("/api/recurring", json={"entry_text": "Groww SIP"})
        assert resp.status_code == 400

    def test_defaults_active_to_true(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        captured = {}
        def capture(conn, data, row_id=None):
            captured.update(data)
            return 1
        with patch("recurring.db.get_connection", return_value=mock_conn), \
             patch("recurring.db.create_recurring_table"), \
             patch("recurring.db.upsert_recurring_transaction", side_effect=capture):
            client.post("/api/recurring", json={"entry_text": "Test", "amount": 100})
        assert captured.get("active") is True

    def test_defaults_divide_by_to_1(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        captured = {}
        def capture(conn, data, row_id=None):
            captured.update(data)
            return 1
        with patch("recurring.db.get_connection", return_value=mock_conn), \
             patch("recurring.db.create_recurring_table"), \
             patch("recurring.db.upsert_recurring_transaction", side_effect=capture):
            client.post("/api/recurring", json={"entry_text": "Test", "amount": 100})
        assert captured.get("divide_by") == 1


# ---------------------------------------------------------------------------
# PUT /api/recurring/<id>
# ---------------------------------------------------------------------------

class TestUpdateRecurring:
    def test_returns_200_on_valid_update(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        with patch("recurring.db.get_connection", return_value=mock_conn), \
             patch("recurring.db.upsert_recurring_transaction", return_value=3):
            resp = client.put("/api/recurring/3", json={"entry_text": "Updated", "amount": 1000})
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

    def test_returns_404_when_not_found(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        with patch("recurring.db.get_connection", return_value=mock_conn), \
             patch("recurring.db.upsert_recurring_transaction", return_value=None):
            resp = client.put("/api/recurring/99", json={"entry_text": "X", "amount": 1})
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/recurring/<id>
# ---------------------------------------------------------------------------

class TestDeleteRecurring:
    def test_delete_returns_204(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        with patch("recurring.db.get_connection", return_value=mock_conn), \
             patch("recurring.db.delete_recurring_transaction", return_value=True):
            resp = client.delete("/api/recurring/1")
        assert resp.status_code == 204

    def test_delete_returns_404_when_not_found(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        with patch("recurring.db.get_connection", return_value=mock_conn), \
             patch("recurring.db.delete_recurring_transaction", return_value=False):
            resp = client.delete("/api/recurring/99")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/recurring/generate (endpoint)
# ---------------------------------------------------------------------------

class TestGenerateEndpoint:
    def test_returns_200_with_count(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        generated = [{"id": 1, "feed_id": 10, "entry_text": "Groww SIP"}]
        with patch("recurring.db.get_connection", return_value=mock_conn), \
             patch("recurring.db.create_recurring_table"), \
             patch("recurring.db.generate_recurring_entries", return_value=generated):
            resp = client.post("/api/recurring/generate")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["count"] == 1
        assert len(data["generated"]) == 1

    def test_returns_empty_when_nothing_due(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        with patch("recurring.db.get_connection", return_value=mock_conn), \
             patch("recurring.db.create_recurring_table"), \
             patch("recurring.db.generate_recurring_entries", return_value=[]):
            resp = client.post("/api/recurring/generate")
        assert resp.status_code == 200
        assert resp.get_json()["count"] == 0

    def test_custom_date_param_forwarded(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        captured = {}
        def capture(conn, today=None):
            captured["today"] = today
            return []
        with patch("recurring.db.get_connection", return_value=mock_conn), \
             patch("recurring.db.create_recurring_table"), \
             patch("recurring.db.generate_recurring_entries", side_effect=capture):
            client.post("/api/recurring/generate?date=2026-01-01")
        assert captured["today"] == _date(2026, 1, 1)

    def test_invalid_date_param_returns_400(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        resp = client.post("/api/recurring/generate?date=not-a-date")
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# db.generate_recurring_entries â€” unit tests (no Flask, no real DB)
# ---------------------------------------------------------------------------

class TestGenerateRecurringEntries:
    """Direct tests of the db function using a mocked connection."""

    def _make_conn_with_rows(self, rows):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = rows
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        return mock_conn, mock_cursor

    def test_no_active_rows_returns_empty_list(self):
        import db
        mock_conn, _ = self._make_conn_with_rows([])
        result = db.generate_recurring_entries(mock_conn, today=_date(2026, 6, 1))
        assert result == []

    def test_generates_one_row_calls_insert(self):
        import db
        row = (1, "Groww SIP", "Groww", Decimal("5000.00"),
               "Investment", "SIP", "Investment", "O", 1, "N", Decimal("1.0"), 1, "Akhil")
        mock_conn, _ = self._make_conn_with_rows([row])
        with patch.object(db, "insert_data_feed_row", return_value=42) as mock_insert:
            result = db.generate_recurring_entries(mock_conn, today=_date(2026, 6, 1))
        assert len(result) == 1
        assert result[0]["id"] == 1
        assert result[0]["feed_id"] == 42
        assert result[0]["entry_text"] == "Groww SIP"
        mock_insert.assert_called_once()

    def test_entry_date_is_first_of_month(self):
        import db
        row = (1, "SIP", "Groww", Decimal("5000.00"),
               "Investment", "SIP", "Investment", "O", 1, "N", Decimal("1.0"), 1, "Akhil")
        mock_conn, _ = self._make_conn_with_rows([row])
        captured = {}
        def capture(conn, entry_date, *args, **kwargs):
            captured["entry_date"] = entry_date
            return 1
        with patch.object(db, "insert_data_feed_row", side_effect=capture):
            db.generate_recurring_entries(mock_conn, today=_date(2026, 6, 15))
        assert captured["entry_date"] == _date(2026, 6, 1)

    def test_time_period_matches_first_of_month(self):
        import db
        row = (1, "SIP", None, Decimal("1000.00"), None, None, None, "O", 1, "N", Decimal("1.0"), 1, "Akhil")
        mock_conn, _ = self._make_conn_with_rows([row])
        captured = {}
        def capture(conn, entry_date, *args, **kwargs):
            captured["time_period"] = kwargs.get("time_period")
            return 1
        with patch.object(db, "insert_data_feed_row", side_effect=capture):
            db.generate_recurring_entries(mock_conn, today=_date(2026, 6, 3))
        assert captured["time_period"] == "Jun-2026"

    def test_exclude_from_training_is_true(self):
        import db
        row = (1, "SIP", None, Decimal("1000.00"), None, None, None, "O", 1, "N", Decimal("1.0"), 1, "Akhil")
        mock_conn, _ = self._make_conn_with_rows([row])
        captured = {}
        def capture(conn, *args, **kwargs):
            captured["exclude"] = kwargs.get("exclude_from_training")
            return 1
        with patch.object(db, "insert_data_feed_row", side_effect=capture):
            db.generate_recurring_entries(mock_conn, today=_date(2026, 6, 1))
        assert captured["exclude"] is True

    def test_computes_monthly_and_final_amount(self):
        import db
        row = (1, "Annual Plan", None, Decimal("12000.00"),
               "Expense", "Subscription", "Expense", "A", 12, "N", Decimal("0.5"), 1, "Akhil")
        mock_conn, _ = self._make_conn_with_rows([row])
        captured = {}
        def capture(conn, *args, **kwargs):
            captured["monthly_amount"] = kwargs.get("monthly_amount")
            captured["final_amount"] = kwargs.get("final_amount")
            return 1
        with patch.object(db, "insert_data_feed_row", side_effect=capture):
            db.generate_recurring_entries(mock_conn, today=_date(2026, 6, 1))
        assert captured["monthly_amount"] == 1000.0
        assert captured["final_amount"] == 500.0

    def test_last_generated_updated_after_insert(self):
        import db
        row = (7, "RD Transfer", None, Decimal("2000.00"),
               "Saving", "RD", "Saving", "O", 1, "N", Decimal("1.0"), 1, "Akhil")
        mock_conn, mock_cursor = self._make_conn_with_rows([row])
        with patch.object(db, "insert_data_feed_row", return_value=99):
            db.generate_recurring_entries(mock_conn, today=_date(2026, 6, 1))
        update_calls = [str(c) for c in mock_cursor.execute.call_args_list]
        assert any("last_generated" in c for c in update_calls)

    def test_idempotency_sql_uses_date_trunc(self):
        import db
        mock_conn, mock_cursor = self._make_conn_with_rows([])
        db.generate_recurring_entries(mock_conn, today=_date(2026, 6, 1))
        select_sql = mock_cursor.execute.call_args_list[0][0][0]
        assert "DATE_TRUNC" in select_sql
        assert "last_generated" in select_sql


class TestRecurringShareRatioZero:
    def _env(self, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        monkeypatch.delenv("INVITE_CODE", raising=False)

    def test_create_zero_ratio_kept(self, client, monkeypatch):
        self._env(monkeypatch)
        mock_conn, _ = _make_mock_conn()
        with patch("db.get_connection", return_value=mock_conn), \
             patch("db.create_recurring_table"), \
             patch("db.upsert_recurring_transaction", return_value=3) as up:
            resp = client.post("/api/recurring", json={"entry_text": "Maid", "amount": 5000, "share_ratio": 0})
        assert resp.status_code == 201
        assert up.call_args[0][1]["share_ratio"] == 0.0

    def test_update_out_of_range_ratio_rejected(self, client, monkeypatch):
        self._env(monkeypatch)
        resp = client.put("/api/recurring/3", json={"entry_text": "Maid", "amount": 5000, "share_ratio": 1.5})
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# BL-27 / nightly catch-up / paid_by / start month
# ---------------------------------------------------------------------------

def _rec_row(day=1, paid_by="Akhil", shared="N", ratio="1.0", rec_id=1):
    # SELECT order: id, entry_text, merchant, amount, category, sub_category, spend_type,
    #               cadence, divide_by, shared_expense, share_ratio, day_of_month, paid_by
    return (rec_id, "Item", "Merchant", Decimal("14000.00"), "Bills", "Car EMI", "Expense",
            "M", 1, shared, Decimal(ratio), day, paid_by)


class TestRecurringDebitDay:
    def _gen(self, rows, today):
        import db
        mock_conn, cur = _make_mock_conn(fetchall=rows)
        dates = []
        def capture(conn, entry_date, *a, **k):
            dates.append((entry_date, k.get("time_period")))
            return 1
        with patch.object(db, "insert_data_feed_row", side_effect=capture), \
             patch.object(db, "upsert_shared_transaction") as ups:
            result = db.generate_recurring_entries(mock_conn, today=today)
        return result, dates, ups, cur

    def test_not_generated_before_debit_day(self):
        result, dates, _, _ = self._gen([_rec_row(day=12)], _date(2026, 10, 5))
        assert result == [] and dates == []

    def test_generated_on_debit_day_dated_that_day(self):
        result, dates, _, _ = self._gen([_rec_row(day=12)], _date(2026, 10, 12))
        assert len(result) == 1
        assert dates == [(_date(2026, 10, 12), "Oct-2026")]

    def test_missed_night_caught_up_later_but_dated_debit_day(self):
        _, dates, _, _ = self._gen([_rec_row(day=12)], _date(2026, 10, 20))
        assert dates == [(_date(2026, 10, 12), "Oct-2026")]

    def test_day_31_falls_on_last_day_of_short_months(self):
        _, sep, _, _ = self._gen([_rec_row(day=31)], _date(2026, 9, 30))
        _, feb, _, _ = self._gen([_rec_row(day=31)], _date(2027, 2, 28))
        assert sep[0][0] == _date(2026, 9, 30)
        assert feb[0][0] == _date(2027, 2, 28)

    def test_effective_day_helper(self):
        import db
        assert db.recurring_effective_day(31, 2028, 2) == 29
        assert db.recurring_effective_day(None, 2026, 10) == 1
        assert db.recurring_effective_day(15, 2026, 10) == 15

    def test_select_filters_start_month_and_this_month(self):
        _, _, _, cur = self._gen([], _date(2026, 10, 20))
        sql, params = cur.execute.call_args_list[0][0]
        assert "start_month IS NULL OR start_month <=" in sql
        assert params == ("2026-10-01", "2026-10-20")

    def test_shared_row_uses_item_payer(self):
        _, _, ups, _ = self._gen([_rec_row(shared="Y", ratio="0.5", paid_by="Aditi")], _date(2026, 10, 1))
        assert ups.call_args.kwargs["paid_by"] == "Aditi"

    def test_default_today_is_ist(self, monkeypatch):
        import db
        monkeypatch.setattr(db, "today_ist", lambda: _date(2026, 10, 1))
        mock_conn, cur = _make_mock_conn(fetchall=[])
        db.generate_recurring_entries(mock_conn)
        assert cur.execute.call_args_list[0][0][1] == ("2026-10-01", "2026-10-01")


class TestUpsertSharedPaidBy:
    def test_aditi_paid_insert_sets_owed_by_and_balance(self):
        import db
        mock_conn, cur = _make_mock_conn()
        db.upsert_shared_transaction(mock_conn, 9, 14000.0, 14000.0, 0.5, _date(2026, 10, 1),
                                     "SAP", "Bills", "Car EMI", "Car Lease", paid_by="Aditi")
        params = cur.execute.call_args[0][1]
        assert params[6] == 7000.0              # balance = Akhil's share (Akhil owes Aditi)
        assert params[-2:] == ("Aditi", "Akhil")

    def test_default_payer_is_akhil(self):
        import db
        mock_conn, cur = _make_mock_conn()
        db.upsert_shared_transaction(mock_conn, 9, 1000.0, 1000.0, 0.7, _date(2026, 10, 1),
                                     None, None, None, None)
        params = cur.execute.call_args[0][1]
        assert params[6] == 300.0               # Aditi's share
        assert params[-2:] == ("Akhil", "Aditi")


class TestRecurringApiNewFields:
    def _env(self, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        monkeypatch.delenv("INVITE_CODE", raising=False)

    def _create(self, client, monkeypatch, body):
        self._env(monkeypatch)
        mock_conn, _ = _make_mock_conn()
        with patch("db.get_connection", return_value=mock_conn), \
             patch("db.create_recurring_table"), \
             patch("db.today_ist", return_value=_date(2026, 9, 26)), \
             patch("db.upsert_recurring_transaction", return_value=3) as up:
            resp = client.post("/api/recurring", json=body)
        return resp, up

    def test_new_item_starts_next_month_by_default(self, client, monkeypatch):
        resp, up = self._create(client, monkeypatch, {"entry_text": "SAP", "amount": 14000})
        assert resp.status_code == 201
        payload = up.call_args[0][1]
        assert payload["start_month"] == _date(2026, 10, 1)
        assert (payload["day_of_month"], payload["paid_by"]) == (1, "Akhil")

    def test_start_this_month(self, client, monkeypatch):
        resp, up = self._create(client, monkeypatch, {"entry_text": "SAP", "amount": 14000, "start_this_month": True})
        assert up.call_args[0][1]["start_month"] == _date(2026, 9, 1)

    def test_day_and_payer_saved(self, client, monkeypatch):
        resp, up = self._create(client, monkeypatch,
                                {"entry_text": "Term", "amount": 900, "day_of_month": 12, "paid_by": "Aditi"})
        assert resp.status_code == 201
        assert (up.call_args[0][1]["day_of_month"], up.call_args[0][1]["paid_by"]) == (12, "Aditi")

    @pytest.mark.parametrize("bad", [0, 32, 2.5, "x"])
    def test_invalid_day_rejected(self, client, monkeypatch, bad):
        resp, up = self._create(client, monkeypatch, {"entry_text": "T", "amount": 1, "day_of_month": bad})
        assert resp.status_code == 400
        up.assert_not_called()

    def test_invalid_payer_rejected(self, client, monkeypatch):
        resp, up = self._create(client, monkeypatch, {"entry_text": "T", "amount": 1, "paid_by": "Bob"})
        assert resp.status_code == 400

    def test_update_without_new_fields_keeps_them(self, client, monkeypatch):
        self._env(monkeypatch)
        mock_conn, _ = _make_mock_conn()
        with patch("db.get_connection", return_value=mock_conn), \
             patch("db.upsert_recurring_transaction", return_value=3) as up:
            resp = client.put("/api/recurring/3", json={"entry_text": "SAP", "amount": 14000})
        assert resp.status_code == 200
        payload = up.call_args[0][1]
        assert payload["day_of_month"] is None and payload["paid_by"] is None
        assert "start_month" not in payload

    def test_update_sql_coalesces_new_fields(self):
        import db
        mock_conn, cur = _make_mock_conn(fetchone=(3,))
        db.upsert_recurring_transaction(mock_conn, {"entry_text": "SAP", "amount": 1}, row_id=3)
        sql = cur.execute.call_args[0][0]
        assert "COALESCE(%s, day_of_month)" in sql and "COALESCE(%s, paid_by)" in sql

