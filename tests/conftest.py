import sys
import os

import pytest

# Tests must never reach the real database. app.py (and several blueprints) call load_dotenv(), which
# would pick up the production DATABASE_URL from .env; load_dotenv() never overrides a variable that
# is already set, so pin an unreachable one before anything is imported.
os.environ["DATABASE_URL"] = "postgresql://tests-have-no-db@127.0.0.1:1/none?connect_timeout=1"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "loader")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "categorizer")))


@pytest.fixture(autouse=True)
def _clear_auth_env(monkeypatch):
    """Remove auth env vars before every test to prevent load_dotenv() cross-contamination."""
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("INVITE_CODE", raising=False)
