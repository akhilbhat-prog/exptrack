"""
Tests for the history Flask blueprint.

Auth tests use no DB.
API route tests mock db.get_connection() to avoid requiring a real DB.
"""

import os
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
        monkeypatch.delenv("REVIEW_TOKEN", raising=False)
        resp = client.get("/view")
        assert resp.status_code == 200

    def test_token_env_set_blocks_without_token(self, client, monkeypatch):
        monkeypatch.setenv("REVIEW_TOKEN", "secret")
        resp = client.get("/view")
        assert resp.status_code == 401

    def test_correct_query_param_grants_access(self, client, monkeypatch):
        monkeypatch.setenv("REVIEW_TOKEN", "secret")
        resp = client.get("/view?token=secret")
        assert resp.status_code == 200

    def test_correct_bearer_header_grants_access(self, client, monkeypatch):
        monkeypatch.setenv("REVIEW_TOKEN", "secret")
        resp = client.get("/view", headers={"Authorization": "Bearer secret"})
        assert resp.status_code == 200

    def test_api_periods_requires_token(self, client, monkeypatch):
        monkeypatch.setenv("REVIEW_TOKEN", "tok")
        resp = client.get("/api/history/periods")
        assert resp.status_code == 401

    def test_api_history_requires_token(self, client, monkeypatch):
        monkeypatch.setenv("REVIEW_TOKEN", "tok")
        resp = client.get("/api/history?period=May-2026")
        assert resp.status_code == 401

    def test_api_patch_requires_token(self, client, monkeypatch):
        monkeypatch.setenv("REVIEW_TOKEN", "tok")
        resp = client.patch("/api/history/1", json={})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/history/periods
# ---------------------------------------------------------------------------

class TestListPeriods:
    def test_returns_200(self, client, monkeypatch):
        monkeypatch.delenv("REVIEW_TOKEN", raising=False)
        mock_conn, mock_cursor = _make_mock_conn(fetchall=[("May-2026", 45), ("Apr-2026", 30)])
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.get_history_periods", return_value=[
                 {"period": "May-2026", "count": 45},
                 {"period": "Apr-2026", "count": 30},
             ]):
            resp = client.get("/api/history/periods")
        assert resp.status_code == 200

    def test_returns_list_of_period_dicts(self, client, monkeypatch):
        monkeypatch.delenv("REVIEW_TOKEN", raising=False)
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
        monkeypatch.delenv("REVIEW_TOKEN", raising=False)
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
        monkeypatch.delenv("REVIEW_TOKEN", raising=False)
        resp = client.get("/api/history")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_returns_paginated_shape(self, client, monkeypatch):
        monkeypatch.delenv("REVIEW_TOKEN", raising=False)
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
        monkeypatch.delenv("REVIEW_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        captured = {}
        def fake_page(conn, period, page, page_size=50):
            captured["page"] = page
            return {"items": [], "total": 0, "page": page, "pages": 1}
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.get_history_page", side_effect=fake_page):
            client.get("/api/history?period=May-2026")
        assert captured["page"] == 1

    def test_page_param_is_forwarded(self, client, monkeypatch):
        monkeypatch.delenv("REVIEW_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        captured = {}
        def fake_page(conn, period, page, page_size=50):
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
        monkeypatch.delenv("REVIEW_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.update_history_row",
                   return_value={"monthly_amount": 100.0, "final_amount": 100.0}):
            resp = client.patch("/api/history/1", json=self._payload)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert "monthly_amount" in data
        assert "final_amount" in data

    def test_returns_404_when_row_not_found(self, client, monkeypatch):
        monkeypatch.delenv("REVIEW_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.update_history_row", return_value=None):
            resp = client.patch("/api/history/999", json=self._payload)
        assert resp.status_code == 404

    def test_divide_by_clamped_to_1(self, client, monkeypatch):
        monkeypatch.delenv("REVIEW_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        captured = {}
        def fake_update(conn, row_id, fields):
            captured["fields"] = fields
            return {"monthly_amount": 100.0, "final_amount": 100.0}
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.update_history_row", side_effect=fake_update):
            client.patch("/api/history/1", json={**self._payload, "divide_by": 0})
        assert captured["fields"]["divide_by"] >= 1

    def test_shared_expense_uppercased(self, client, monkeypatch):
        monkeypatch.delenv("REVIEW_TOKEN", raising=False)
        mock_conn, _ = _make_mock_conn()
        captured = {}
        def fake_update(conn, row_id, fields):
            captured["fields"] = fields
            return {"monthly_amount": 50.0, "final_amount": 25.0}
        with patch("history.db.get_connection", return_value=mock_conn), \
             patch("history.db.update_history_row", side_effect=fake_update):
            client.patch("/api/history/1", json={**self._payload, "shared_expense": "y"})
        assert captured["fields"]["shared_expense"] == "Y"
