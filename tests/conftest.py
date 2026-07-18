from __future__ import annotations
import tempfile
from pathlib import Path
from typing import Any
import pytest


@pytest.fixture(autouse=True)
def _reset_effort_state():
    """Reset effort module state between tests."""
    from llm_apipool.core import model_effort
    model_effort._cache = None
    # Reset any module-level state
    yield


@pytest.fixture
def db_path():
    """Create a temporary SQLite database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = Path(f.name)
    yield path
    if path.exists():
        path.unlink()


@pytest.fixture
def store(db_path):
    """Create a KeyStore with a temp database."""
    from llm_apipool.key_store import KeyStore
    ks = KeyStore(db_path=str(db_path))
    ks._init_db()
    return ks


@pytest.fixture
def sample_key_data() -> dict[str, Any]:
    return {
        "id": 1,
        "api_key": "sk-test-key-12345",
        "provider": "openai",
        "model": "gpt-4o",
        "is_active": True,
        "capabilities": '["general_purpose"]',
        "base_url": "https://api.openai.com/v1",
    }
