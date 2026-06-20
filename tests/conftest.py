import sys
import os

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "loader")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "categorizer")))


@pytest.fixture(autouse=True)
def _clear_auth_env(monkeypatch):
    """Remove auth env vars before every test to prevent load_dotenv() cross-contamination."""
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("INVITE_CODE", raising=False)
