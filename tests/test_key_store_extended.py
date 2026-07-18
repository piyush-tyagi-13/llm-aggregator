"""Extended tests for KeyStore - uncovered edge cases."""

from __future__ import annotations

import logging
import sqlite3
from unittest.mock import patch

import pytest

from llm_apipool.key_store import KeyStore, _mask_key, _resolve_db_path


# ===================================================================
# _mask_key edge cases (lines 21-23)
# ===================================================================


class TestMaskKey:
    """_mask_key — safe API-key masking for logging."""

    def test_normal_length(self):
        """Len > 8: show first 4 + **** + last 4."""
        assert _mask_key("sk-abcdefghijklmnop") == "sk-a****mnop"

    def test_short_but_above_4(self):
        """4 < len <= 8: show **** + last 4."""
        assert _mask_key("12345678") == "****5678"

    def test_five_chars(self):
        """len=5: show **** + last 4."""
        assert _mask_key("12345") == "****2345"

    def test_exactly_four(self):
        """len=4: return ****."""
        assert _mask_key("1234") == "****"

    def test_three_chars(self):
        """len=3: return ****."""
        assert _mask_key("abc") == "****"

    def test_empty_string(self):
        """empty string: return ****."""
        assert _mask_key("") == "****"


# ===================================================================
# _resolve_db_path edge cases (lines 34-42)
# ===================================================================


def test_resolve_db_path_both_exist(tmp_path, monkeypatch):
    """When both old and new DB paths exist, a warning is logged (lines 34-38)."""
    # Clear env vars so _resolve_db_path uses module defaults
    monkeypatch.delenv("LLM_APIPOOL_DB", raising=False)
    monkeypatch.delenv("LLM_APIPOOL_DB_LEGACY", raising=False)

    import llm_apipool.key_store as ks

    new_db_dir = tmp_path / ".llm-apipool"
    old_db_dir = tmp_path / ".llm-aggregator"
    new_db_dir.mkdir(parents=True)
    old_db_dir.mkdir(parents=True)
    (new_db_dir / "keys.db").touch()
    (old_db_dir / "keys.db").touch()

    monkeypatch.setattr(ks, "_NEW_DB_DEFAULT", new_db_dir / "keys.db")
    monkeypatch.setattr(ks, "_OLD_DB_DEFAULT", old_db_dir / "keys.db")

    with patch.object(
        logging.getLogger("llm_apipool.key_store"), "warning"
    ) as mock_warn:
        path = ks._resolve_db_path()
        mock_warn.assert_called_once()
        assert "Both" in mock_warn.call_args[0][0]
    assert path == new_db_dir / "keys.db"


def test_resolve_db_path_migration_from_old(tmp_path, monkeypatch):
    """When only old DB exists, it is copied to new path (lines 39-42)."""
    # Clear env vars so _resolve_db_path uses module defaults
    monkeypatch.delenv("LLM_APIPOOL_DB", raising=False)
    monkeypatch.delenv("LLM_APIPOOL_DB_LEGACY", raising=False)

    import llm_apipool.key_store as ks

    new_db_dir = tmp_path / ".llm-apipool"
    old_db_dir = tmp_path / ".llm-aggregator"
    old_db_dir.mkdir(parents=True)

    conn = sqlite3.connect(str(old_db_dir / "keys.db"))
    conn.execute(
        "CREATE TABLE api_keys (id INTEGER PRIMARY KEY, provider TEXT, api_key TEXT)"
    )
    conn.execute(
        "INSERT INTO api_keys (provider, api_key) VALUES ('groq', 'migrated_key')"
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(ks, "_NEW_DB_DEFAULT", new_db_dir / "keys.db")
    monkeypatch.setattr(ks, "_OLD_DB_DEFAULT", old_db_dir / "keys.db")

    # Verify old DB exists with data before calling _resolve_db_path
    assert old_db_dir.exists()
    assert (old_db_dir / "keys.db").exists()
    assert new_db_dir.exists() is False  # new dir doesn't exist yet

    # Verify old DB content is queryable
    conn_check = sqlite3.connect(str(old_db_dir / "keys.db"))
    old_rows = conn_check.execute("SELECT api_key FROM api_keys").fetchall()
    conn_check.close()
    assert len(old_rows) == 1, f"Old DB has {len(old_rows)} rows, expected 1"
    assert old_rows[0][0] == "migrated_key"

    path = ks._resolve_db_path()

    assert path == new_db_dir / "keys.db"
    assert path.exists()

    conn2 = sqlite3.connect(str(path))
    rows = conn2.execute("SELECT api_key FROM api_keys").fetchall()
    conn2.close()
    assert len(rows) == 1
    assert rows[0][0] == "migrated_key"


def test_resolve_db_path_env_var(tmp_path, monkeypatch):
    """LLM_APIPOOL_DB env var overrides default path (lines 32-33)."""
    custom_db = tmp_path / "custom" / "my.db"
    monkeypatch.setenv("LLM_APIPOOL_DB", str(custom_db))
    path = _resolve_db_path()
    assert path == custom_db


# ===================================================================
# parse_capabilities edge cases (lines 167-169)
# ===================================================================


def test_parse_capabilities_invalid_json(store):
    """Invalid JSON in capabilities column falls back to string (lines 167-168)."""
    store.register_key("groq", "key1", "general_purpose", None, {})
    key = store.get_all_keys()[0]

    # Directly inject invalid JSON
    conn = sqlite3.connect(str(store._db_path))
    conn.execute(
        "UPDATE api_keys SET capabilities = '{invalid_json' WHERE id = ?", (key["id"],)
    )
    conn.commit()
    conn.close()

    key2 = store.get_key_by_id(key["id"])
    caps = store.parse_capabilities(key2)
    assert caps == ["{invalid_json"]


def test_parse_capabilities_json_returns_non_list(tmp_path):
    """When JSON parses but is not a list, fall back to general_purpose."""
    from llm_apipool.key_store import KeyStore

    store = KeyStore(db_path=tmp_path / "type_err.db")
    store.register_key("groq", "key1", "general_purpose", None, {})

    # Inject JSON that parses to a non-list value (string)
    conn = sqlite3.connect(str(store._db_path))
    conn.execute("UPDATE api_keys SET capabilities = '\"just_a_string\"' WHERE id = 1")
    conn.commit()
    conn.close()

    key = store.get_key_by_id(1)
    caps = store.parse_capabilities(key)
    assert caps == ["general_purpose"]


# ===================================================================
# register_key with None capabilities (line 184)
# ===================================================================


def test_register_key_with_none_capabilities(store):
    """register_key with capabilities=None defaults to general_purpose."""
    result = store.register_key("groq", "test_key_none", None, None, {})
    assert result["success"]
    key = store.get_all_keys()[0]
    caps = store.parse_capabilities(key)
    assert caps == ["general_purpose"]


# ===================================================================
# record_usage with missing key (line 255)
# ===================================================================


def test_record_usage_missing_key_silent(store):
    """record_usage on non-existent key returns silently (line 255)."""
    # Should not raise any exception
    store.record_usage(9999, tokens=100, was_429=False)
    store.record_usage(
        9999, tokens=100, was_429=True, cooldown_until="2099-01-01T00:00:00"
    )


# ===================================================================
# update_key with no changes (line 289)
# ===================================================================


def test_update_key_no_changes(store):
    """update_key with no params returns False (line 289)."""
    store.register_key("groq", "test_key_update", "general_purpose", "model1", {})
    key = store.get_all_keys()[0]
    result = store.update_key(key["id"])
    assert result is False

    # Key should remain unchanged
    fetched = store.get_key_by_id(key["id"])
    assert fetched["model"] == "model1"


# ===================================================================
# get_audit_log with subscriber filter (lines 339-351)
# ===================================================================


def test_get_audit_log_with_subscriber(store):
    """get_audit_log with subscriber_id filters results (lines 341-345)."""
    store.register_key("groq", "key_aud1", "general_purpose", None, {})
    store.register_key("mistral", "key_aud2", "general_purpose", None, {})

    # Log entries for two subscribers
    store.log_audit("sub_alpha", 1, "groq", "model-a", tokens_in=10, tokens_out=20)
    store.log_audit("sub_beta", 2, "mistral", "model-b", tokens_in=5, tokens_out=10)
    store.log_audit("sub_alpha", 1, "groq", "model-a", tokens_in=15, tokens_out=25)

    all_logs = store.get_audit_log(days=30)
    assert len(all_logs) == 3

    alpha_logs = store.get_audit_log(subscriber_id="sub_alpha", days=30)
    assert len(alpha_logs) == 2
    assert all(log["subscriber_id"] == "sub_alpha" for log in alpha_logs)

    beta_logs = store.get_audit_log(subscriber_id="sub_beta", days=30)
    assert len(beta_logs) == 1
    assert beta_logs[0]["subscriber_id"] == "sub_beta"

    nonexistent_logs = store.get_audit_log(subscriber_id="sub_nonexistent", days=30)
    assert len(nonexistent_logs) == 0


def test_get_audit_log_no_subscriber(store):
    """get_audit_log without subscriber returns all entries (lines 346-350)."""
    store.register_key("groq", "key_aud3", "general_purpose", None, {})
    store.log_audit("sub1", 1, "groq", "model-x")
    store.log_audit("sub2", 1, "groq", "model-y")

    logs = store.get_audit_log(days=30)
    assert len(logs) == 2


# ===================================================================
# Fixture for tests that need a store
# ===================================================================


@pytest.fixture
def store(tmp_path):
    return KeyStore(db_path=tmp_path / "ext_test.db")
