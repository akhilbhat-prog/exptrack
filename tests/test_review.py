"""
Tests for the review Flask blueprint.

DB-dependent routes (batches, complete, etc.) are deferred — they require a
real PostgreSQL instance. These tests cover auth logic and the categories
endpoint, which gracefully degrades to rules.json when no DB is available.
"""

import os
import pytest
from flask import Flask

from review import review_bp

_TEMPLATES = os.path.join(os.path.dirname(__file__), "..", "templates")
_RULES_PATH = os.path.join(os.path.dirname(__file__), "..", "categorizer", "config", "rules.json")


@pytest.fixture
def app():
    app = Flask(__name__, template_folder=_TEMPLATES)
    app.register_blueprint(review_bp)
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


class TestRequireToken:
    def test_no_token_env_allows_access(self, client, monkeypatch):
        monkeypatch.delenv("REVIEW_TOKEN", raising=False)
        resp = client.get("/review")
        assert resp.status_code == 200

    def test_token_env_set_blocks_without_token(self, client, monkeypatch):
        monkeypatch.setenv("REVIEW_TOKEN", "secret")
        resp = client.get("/review")
        assert resp.status_code == 401

    def test_token_env_set_blocks_wrong_token(self, client, monkeypatch):
        monkeypatch.setenv("REVIEW_TOKEN", "secret")
        resp = client.get("/review?token=wrong")
        assert resp.status_code == 401

    def test_correct_query_param_grants_access(self, client, monkeypatch):
        monkeypatch.setenv("REVIEW_TOKEN", "secret")
        resp = client.get("/review?token=secret")
        assert resp.status_code == 200

    def test_correct_bearer_header_grants_access(self, client, monkeypatch):
        monkeypatch.setenv("REVIEW_TOKEN", "secret")
        resp = client.get("/review", headers={"Authorization": "Bearer secret"})
        assert resp.status_code == 200

    def test_raw_token_in_auth_header_also_grants_access(self, client, monkeypatch):
        # removeprefix("Bearer ") is a no-op when prefix is absent, so the raw
        # token value in the Authorization header is accepted as well.
        monkeypatch.setenv("REVIEW_TOKEN", "secret")
        resp = client.get("/review", headers={"Authorization": "secret"})
        assert resp.status_code == 200


class TestGetCategories:
    """
    In CI there is no DATABASE_URL, so the DB enrichment step is skipped
    gracefully and categories are derived from rules.json alone.
    """

    def test_returns_200(self, client, monkeypatch):
        monkeypatch.delenv("REVIEW_TOKEN", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        resp = client.get("/api/categories")
        assert resp.status_code == 200

    def test_response_has_categories_and_types_keys(self, client, monkeypatch):
        monkeypatch.delenv("REVIEW_TOKEN", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        data = client.get("/api/categories").get_json()
        assert "categories" in data
        assert "types" in data

    def test_categories_is_dict_of_lists(self, client, monkeypatch):
        monkeypatch.delenv("REVIEW_TOKEN", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        data = client.get("/api/categories").get_json()
        assert isinstance(data["categories"], dict)
        for cat, subs in data["categories"].items():
            assert isinstance(cat, str)
            assert isinstance(subs, list)

    def test_categories_nonempty_from_rules_json(self, client, monkeypatch):
        monkeypatch.delenv("REVIEW_TOKEN", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        data = client.get("/api/categories").get_json()
        assert len(data["categories"]) > 0

    def test_types_fallback_when_no_db(self, client, monkeypatch):
        monkeypatch.delenv("REVIEW_TOKEN", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        data = client.get("/api/categories").get_json()
        assert isinstance(data["types"], list)
        assert len(data["types"]) > 0

    def test_categories_require_token_when_set(self, client, monkeypatch):
        monkeypatch.setenv("REVIEW_TOKEN", "tok")
        monkeypatch.delenv("DATABASE_URL", raising=False)
        resp = client.get("/api/categories")
        assert resp.status_code == 401

    def test_categories_accessible_with_token(self, client, monkeypatch):
        monkeypatch.setenv("REVIEW_TOKEN", "tok")
        monkeypatch.delenv("DATABASE_URL", raising=False)
        resp = client.get("/api/categories?token=tok")
        assert resp.status_code == 200
