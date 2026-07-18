"""Tests for KeyStore - CRUD, cooldown, usage tracking, migration."""

from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime, timezone, timedelta

import pytest

from llm_apipool.key_store import KeyStore


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test_keys.db"


@pytest.fixture
def store(db_path):
    return KeyStore(db_path=db_path)


# --- registration ---


def test_register_key_success(store):
    result = store.register_key(
        "groq", "gsk_test123", "general_purpose", "llama-3.3-70b-versatile", {}
    )
    assert result["success"] is True
    assert "groq" in result["message"]


def test_register_duplicate_fails(store):
    store.register_key("groq", "gsk_test123", "general_purpose", None, {})
    result = store.register_key("groq", "gsk_test123", "general_purpose", None, {})
    assert result["success"] is False
    assert "already" in result["message"].lower()


def test_register_multiple_providers(store):
    store.register_key("groq", "key_groq", "general_purpose", None, {})
    store.register_key("mistral", "key_mistral", "general_purpose", None, {})
    keys = store.get_all_keys()
    providers = {k["provider"] for k in keys}
    assert providers == {"groq", "mistral"}


# --- retrieval ---


def test_get_all_keys_empty(store):
    assert store.get_all_keys() == []


def test_get_active_keys_returns_only_active(store):
    store.register_key("groq", "key1", "general_purpose", None, {})
    store.register_key("mistral", "key2", "general_purpose", None, {})
    keys = store.get_all_keys()
    store.deactivate_key(keys[0]["id"])

    active = store.get_active_keys("general_purpose")
    assert len(active) == 1
    assert active[0]["provider"] == "mistral"


def test_get_active_keys_excludes_cooldown(store):
    store.register_key("groq", "key1", "general_purpose", None, {})
    key = store.get_all_keys()[0]
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    store.record_usage(key["id"], tokens=0, was_429=True, cooldown_until=future)

    active = store.get_active_keys("general_purpose")
    assert len(active) == 0


def test_get_active_keys_includes_expired_cooldown(store):
    store.register_key("groq", "key1", "general_purpose", None, {})
    key = store.get_all_keys()[0]
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    store.record_usage(key["id"], tokens=0, was_429=True, cooldown_until=past)

    active = store.get_active_keys("general_purpose")
    assert len(active) == 1


def test_get_key_by_id(store):
    store.register_key("groq", "key_abc", "general_purpose", "llama-3.3-70b", {})
    key = store.get_all_keys()[0]
    fetched = store.get_key_by_id(key["id"])
    assert fetched is not None
    assert fetched["provider"] == "groq"
    assert fetched["api_key"] == "key_abc"


def test_get_key_by_id_missing(store):
    assert store.get_key_by_id(9999) is None


# --- deactivation ---


def test_deactivate_key(store):
    store.register_key("groq", "key1", "general_purpose", None, {})
    key = store.get_all_keys()[0]
    store.deactivate_key(key["id"])
    fetched = store.get_key_by_id(key["id"])
    assert fetched["is_active"] == 0


# --- cooldown ---


def test_clear_cooldown(store):
    store.register_key("groq", "key1", "general_purpose", None, {})
    key = store.get_all_keys()[0]
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    store.record_usage(key["id"], tokens=0, was_429=True, cooldown_until=future)

    store.clear_cooldown(key["id"])
    fetched = store.get_key_by_id(key["id"])
    assert fetched["cooldown_until"] is None


# --- usage tracking ---


def test_record_usage_increments_counters(store):
    store.register_key("groq", "key1", "general_purpose", None, {})
    key = store.get_all_keys()[0]

    store.record_usage(key["id"], tokens=100, was_429=False)
    store.record_usage(key["id"], tokens=200, was_429=False)

    fetched = store.get_key_by_id(key["id"])
    assert fetched["requests_today"] == 2
    assert fetched["tokens_used_today"] == 300


def test_record_usage_429_sets_cooldown(store):
    store.register_key("groq", "key1", "general_purpose", None, {})
    key = store.get_all_keys()[0]
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

    store.record_usage(key["id"], tokens=0, was_429=True, cooldown_until=future)
    fetched = store.get_key_by_id(key["id"])
    assert fetched["cooldown_until"] is not None
    assert fetched["last_429_at"] is not None


# --- update ---


def test_update_key_model(store):
    store.register_key("groq", "key1", "general_purpose", "old-model", {})
    key = store.get_all_keys()[0]
    store.update_key(key["id"], model="new-model")
    fetched = store.get_key_by_id(key["id"])
    assert fetched["model"] == "new-model"


def test_update_key_api_key(store):
    store.register_key("groq", "old_key", "general_purpose", None, {})
    key = store.get_all_keys()[0]
    store.update_key(key["id"], api_key="new_key")
    fetched = store.get_key_by_id(key["id"])
    assert fetched["api_key"] == "new_key"


# --- category filtering ---


def test_active_keys_category_filter(store):
    store.register_key("groq", "key1", "general_purpose", None, {})
    store.register_key("mistral", "key2", "general_purpose", None, {})

    gp = store.get_active_keys("general_purpose")
    assert len(gp) == 2
    providers = {k["provider"] for k in gp}
    assert providers == {"groq", "mistral"}


# --- rotation state ---


def test_save_and_load_rotation_state(store):
    store.register_key("groq", "key1", "general_purpose", None, {})
    key = store.get_all_keys()[0]

    store.save_rotation_state("general_purpose", cursor=2, slot_counts={key["id"]: 3})
    cursor, slot_counts = store.load_rotation_state("general_purpose")

    assert cursor == 2
    assert slot_counts[key["id"]] == 3


def test_load_rotation_state_empty(store):
    cursor, slot_counts = store.load_rotation_state("general_purpose")
    assert cursor == 0
    assert slot_counts == {}


# --- DB migration ---


def test_db_migration_from_old_path(tmp_path):
    """Old ~/.llm-aggregator/keys.db auto-migrated to new path."""
    old_db = tmp_path / "old" / "keys.db"
    new_db = tmp_path / "new" / "keys.db"
    old_db.parent.mkdir()

    # Create populated old DB
    conn = sqlite3.connect(str(old_db))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT NOT NULL,
            api_key TEXT NOT NULL,
            category TEXT NOT NULL,
            model TEXT,
            extra_params TEXT NOT NULL DEFAULT '{}',
            is_active INTEGER NOT NULL DEFAULT 1,
            tokens_used_today INTEGER NOT NULL DEFAULT 0,
            tokens_used_month INTEGER NOT NULL DEFAULT 0,
            requests_today INTEGER NOT NULL DEFAULT 0,
            requests_month INTEGER NOT NULL DEFAULT 0,
            last_429_at TEXT,
            cooldown_until TEXT,
            daily_reset_date TEXT,
            monthly_reset_month TEXT,
            added_at TEXT NOT NULL DEFAULT (datetime('now')),
            last_used_at TEXT
        );
        INSERT INTO api_keys (provider, api_key, category) VALUES ('groq', 'migrated_key', 'general_purpose');
    """)
    conn.close()

    # Simulate migration
    if not new_db.exists() and old_db.exists():
        new_db.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(old_db, new_db)

    assert new_db.exists()
    conn2 = sqlite3.connect(str(new_db))
    rows = conn2.execute("SELECT api_key FROM api_keys").fetchall()
    conn2.close()
    assert rows[0][0] == "migrated_key"
