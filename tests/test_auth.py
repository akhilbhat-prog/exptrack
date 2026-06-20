"""Tests for auth_routes Blueprint: /login, /logout, /register."""

import os
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.security import generate_password_hash

from auth_routes import auth_bp
from shared import shared_bp

_TEMPLATES = os.path.join(os.path.dirname(__file__), "..", "templates")


@pytest.fixture
def app():
    a = Flask(__name__, template_folder=_TEMPLATES)
    a.register_blueprint(auth_bp)
    a.register_blueprint(shared_bp)
    a.config["TESTING"] = True
    a.secret_key = "test-secret"
    return a


@pytest.fixture
def client(app):
    return app.test_client()


def _make_mock_conn():
    mock_cursor = MagicMock()
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=False)
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    return mock_conn


def _user(username="aditi", password="password123"):
    return {
        "id": 1,
        "username": username,
        "password_hash": generate_password_hash(password),
        "role": "user",
    }


# ---------------------------------------------------------------------------
# GET /login
# ---------------------------------------------------------------------------

class TestLoginGet:
    def test_returns_200(self, client):
        resp = client.get("/login")
        assert resp.status_code == 200

    def test_renders_sign_in_heading(self, client):
        resp = client.get("/login")
        assert b"Sign in" in resp.data


# ---------------------------------------------------------------------------
# POST /login
# ---------------------------------------------------------------------------

class TestLoginPost:
    def test_valid_credentials_redirects_to_shared(self, client):
        user = _user()
        with patch("auth_routes.db.get_connection", return_value=_make_mock_conn()), \
             patch("auth_routes.db.get_user_by_username", return_value=user):
            resp = client.post("/login",
                               data={"username": "aditi", "password": "password123"},
                               follow_redirects=False)
        assert resp.status_code == 302
        assert "/shared" in resp.headers["Location"]

    def test_valid_credentials_sets_session_role(self, client):
        user = _user()
        with patch("auth_routes.db.get_connection", return_value=_make_mock_conn()), \
             patch("auth_routes.db.get_user_by_username", return_value=user):
            client.post("/login", data={"username": "aditi", "password": "password123"})
            with client.session_transaction() as sess:
                assert sess["role"] == "user"
                assert sess["username"] == "aditi"
                assert sess["user_id"] == 1

    def test_wrong_password_returns_401(self, client):
        user = _user()
        with patch("auth_routes.db.get_connection", return_value=_make_mock_conn()), \
             patch("auth_routes.db.get_user_by_username", return_value=user):
            resp = client.post("/login",
                               data={"username": "aditi", "password": "wrongpass"})
        assert resp.status_code == 401

    def test_unknown_user_returns_401(self, client):
        with patch("auth_routes.db.get_connection", return_value=_make_mock_conn()), \
             patch("auth_routes.db.get_user_by_username", return_value=None):
            resp = client.post("/login",
                               data={"username": "nobody", "password": "pass"})
        assert resp.status_code == 401

    def test_missing_password_returns_400(self, client):
        resp = client.post("/login", data={"username": "aditi"})
        assert resp.status_code == 400

    def test_missing_username_returns_400(self, client):
        resp = client.post("/login", data={"password": "pass123"})
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /logout
# ---------------------------------------------------------------------------

class TestLogout:
    def test_clears_session_and_redirects_to_login(self, client):
        user = _user()
        with patch("auth_routes.db.get_connection", return_value=_make_mock_conn()), \
             patch("auth_routes.db.get_user_by_username", return_value=user):
            client.post("/login", data={"username": "aditi", "password": "password123"})
        resp = client.get("/logout", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_session_is_empty_after_logout(self, client):
        user = _user()
        with patch("auth_routes.db.get_connection", return_value=_make_mock_conn()), \
             patch("auth_routes.db.get_user_by_username", return_value=user):
            client.post("/login", data={"username": "aditi", "password": "password123"})
        client.get("/logout")
        with client.session_transaction() as sess:
            assert "role" not in sess
            assert "user_id" not in sess


# ---------------------------------------------------------------------------
# GET /register
# ---------------------------------------------------------------------------

class TestRegisterGet:
    def test_returns_200(self, client):
        resp = client.get("/register")
        assert resp.status_code == 200

    def test_renders_create_account_heading(self, client):
        resp = client.get("/register")
        assert b"Create account" in resp.data


# ---------------------------------------------------------------------------
# POST /register
# ---------------------------------------------------------------------------

class TestRegisterPost:
    def test_valid_registration_redirects_to_login(self, client, monkeypatch):
        monkeypatch.setenv("INVITE_CODE", "secret-invite")
        with patch("auth_routes.db.get_connection", return_value=_make_mock_conn()), \
             patch("auth_routes.db.username_exists", return_value=False), \
             patch("auth_routes.db.create_user", return_value=1):
            resp = client.post("/register",
                               data={"username": "aditi",
                                     "password": "strongpass",
                                     "invite_code": "secret-invite"},
                               follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_wrong_invite_code_returns_400(self, client, monkeypatch):
        monkeypatch.setenv("INVITE_CODE", "secret-invite")
        resp = client.post("/register",
                           data={"username": "aditi",
                                 "password": "strongpass",
                                 "invite_code": "wrong-code"})
        assert resp.status_code == 400

    def test_no_invite_code_env_returns_400(self, client, monkeypatch):
        monkeypatch.delenv("INVITE_CODE", raising=False)
        resp = client.post("/register",
                           data={"username": "aditi",
                                 "password": "strongpass",
                                 "invite_code": "anything"})
        assert resp.status_code == 400

    def test_short_password_returns_400(self, client, monkeypatch):
        monkeypatch.setenv("INVITE_CODE", "secret-invite")
        resp = client.post("/register",
                           data={"username": "aditi",
                                 "password": "short",
                                 "invite_code": "secret-invite"})
        assert resp.status_code == 400

    def test_duplicate_username_returns_400(self, client, monkeypatch):
        monkeypatch.setenv("INVITE_CODE", "secret-invite")
        with patch("auth_routes.db.get_connection", return_value=_make_mock_conn()), \
             patch("auth_routes.db.username_exists", return_value=True):
            resp = client.post("/register",
                               data={"username": "aditi",
                                     "password": "strongpass",
                                     "invite_code": "secret-invite"})
        assert resp.status_code == 400

    def test_missing_fields_returns_400(self, client, monkeypatch):
        monkeypatch.setenv("INVITE_CODE", "secret-invite")
        resp = client.post("/register", data={"username": "aditi"})
        assert resp.status_code == 400
