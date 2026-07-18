"""Tests for Rotator - key selection, rotation, 429 handling, cooldown strategies."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from llm_apipool.key_store import KeyStore
from llm_apipool.rotator import (
    Rotator,
    _next_utc_midnight,
    _next_first_of_month,
    _rolling,
    _FALLBACK_STRATEGIES,
)

PROVIDER_CONFIGS = {
    "groq": {
        "capabilities": ["general_purpose"],
        "base_url": "https://api.groq.com/openai/v1",
        "openai_compatible": True,
        "limits": {"rpm": 30, "rpd": 14400},
        "cooldown_fallback": {"strategy": "daily_utc_midnight"},
        "default_model": "llama-3.3-70b-versatile",
        "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"],
    },
    "mistral": {
        "capabilities": ["general_purpose"],
        "base_url": "https://api.mistral.ai/v1",
        "openai_compatible": True,
        "limits": {"rpm": 2},
        "cooldown_fallback": {"strategy": "rolling_65"},
        "default_model": "mistral-large-latest",
        "models": ["mistral-large-latest"],
    },
    "cohere": {
        "capabilities": ["general_purpose"],
        "base_url": "https://api.cohere.com/v2",
        "openai_compatible": False,
        "limits": {"rpm": 20},
        "cooldown_fallback": {"strategy": "first_of_calendar_month"},
        "default_model": "command-r-plus-08-2024",
        "models": ["command-r-plus-08-2024"],
    },
}


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "rotator_test.db"


@pytest.fixture
def store(db_path):
    return KeyStore(db_path=db_path)


@pytest.fixture
def rotator(store):
    return Rotator(store, PROVIDER_CONFIGS, rotate_every=3)


def _add_key(store, provider, api_key, category="general_purpose", model=None):
    store.register_key(provider, api_key, category, model, {})
    return store.get_active_keys(category)[-1]


# --- cooldown time helpers ---


def test_next_utc_midnight_is_tomorrow_midnight():
    result = _next_utc_midnight()
    parsed = datetime.fromisoformat(result)
    now = datetime.now(timezone.utc)
    assert parsed > now
    assert parsed.hour == 0
    assert parsed.minute == 0
    assert parsed.second == 0


def test_next_first_of_month_is_first():
    result = _next_first_of_month()
    parsed = datetime.fromisoformat(result)
    assert parsed.day == 1
    assert parsed.hour == 0


def test_rolling_60_is_about_60s_ahead():
    fn = _rolling(60)
    before = datetime.now(timezone.utc)
    result = fn()
    parsed = datetime.fromisoformat(result)
    delta = (parsed - before).total_seconds()
    assert 55 <= delta <= 65


def test_rolling_65_is_about_65s_ahead():
    fn = _rolling(65)
    before = datetime.now(timezone.utc)
    result = fn()
    parsed = datetime.fromisoformat(result)
    delta = (parsed - before).total_seconds()
    assert 60 <= delta <= 70


def test_fallback_strategies_all_present():
    expected = {
        "daily_utc_midnight",
        "first_of_calendar_month",
        "rolling_60",
        "rolling_65",
        "rolling_120",
    }
    assert expected.issubset(set(_FALLBACK_STRATEGIES.keys()))


# --- get_best_key ---


def test_get_best_key_no_keys(rotator):
    assert rotator.get_best_key("general_purpose") is None


def test_get_best_key_single_key(store, rotator):
    _add_key(store, "groq", "key1")
    key = rotator.get_best_key("general_purpose")
    assert key is not None
    assert key["provider"] == "groq"
    assert key["api_key"] == "key1"
    assert key["base_url"] == PROVIDER_CONFIGS["groq"]["base_url"]


def test_get_best_key_returns_explicit_model(store, rotator):
    store.register_key("groq", "key1", "general_purpose", "llama-3.1-8b-instant", {})
    key = rotator.get_best_key("general_purpose")
    assert key["model"] == "llama-3.1-8b-instant"


def test_get_best_key_uses_provider_default_when_no_model(store, rotator):
    store.register_key("groq", "key1", "general_purpose", None, {})
    key = rotator.get_best_key("general_purpose")
    assert key["model"] == "llama-3.3-70b-versatile"


def test_get_best_key_skips_inactive(store, rotator):
    _add_key(store, "groq", "key1")
    _add_key(store, "mistral", "key2")
    keys = store.get_all_keys()
    store.deactivate_key(keys[0]["id"])

    key = rotator.get_best_key("general_purpose")
    assert key["provider"] == "mistral"


def test_get_best_key_skips_cooled_down(store, rotator):
    _add_key(store, "groq", "key1")
    _add_key(store, "mistral", "key2")
    groq_key = store.get_active_keys("general_purpose")[0]
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    store.record_usage(groq_key["id"], tokens=0, was_429=True, cooldown_until=future)

    key = rotator.get_best_key("general_purpose")
    assert key["provider"] == "mistral"


def test_get_best_key_all_cooled_down_returns_none(store, rotator):
    _add_key(store, "groq", "key1")
    groq = store.get_active_keys("general_purpose")[0]
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    store.record_usage(groq["id"], tokens=0, was_429=True, cooldown_until=future)

    assert rotator.get_best_key("general_purpose") is None


# --- rotation ---


def test_rotates_after_rotate_every_slots(store):
    rot = Rotator(store, PROVIDER_CONFIGS, rotate_every=2)
    _add_key(store, "groq", "key1")
    _add_key(store, "mistral", "key2")

    providers = []
    for _ in range(6):
        k = rot.get_best_key("general_purpose")
        rot.handle_success(k["key_id"], tokens_used=10)
        providers.append(k["provider"])

    assert len(set(providers)) == 2


def test_rotation_uses_both_keys(store):
    rot = Rotator(store, PROVIDER_CONFIGS, rotate_every=1)
    _add_key(store, "groq", "key1")
    _add_key(store, "mistral", "key2")

    seen = set()
    for _ in range(4):
        k = rot.get_best_key("general_purpose")
        rot.handle_success(k["key_id"], tokens_used=10)
        seen.add(k["provider"])

    assert "groq" in seen
    assert "mistral" in seen


# --- 429 handling ---


def test_handle_429_sets_cooldown_on_key(store, rotator):
    _add_key(store, "groq", "key1")
    key = rotator.get_best_key("general_purpose")
    cooldown_until = rotator.handle_429(key["key_id"], "groq")

    assert cooldown_until is not None
    fetched = store.get_key_by_id(key["key_id"])
    assert fetched["cooldown_until"] == cooldown_until


def test_handle_429_key_excluded_from_pool(store, rotator):
    _add_key(store, "groq", "key1")
    key = rotator.get_best_key("general_purpose")
    rotator.handle_429(key["key_id"], "groq")

    # Key should now be in cooldown - get_active_keys excludes it
    active = store.get_active_keys("general_purpose")
    assert len(active) == 0


def test_handle_429_groq_cooldown_is_midnight(store, rotator):
    _add_key(store, "groq", "key1")
    key = rotator.get_best_key("general_purpose")
    cooldown = rotator.handle_429(key["key_id"], "groq")
    parsed = datetime.fromisoformat(cooldown)
    assert parsed.hour == 0


def test_handle_429_cohere_cooldown_is_first_of_month(store, rotator):
    _add_key(store, "cohere", "key1")
    key = rotator.get_best_key("general_purpose")
    cooldown = rotator.handle_429(key["key_id"], "cohere")
    parsed = datetime.fromisoformat(cooldown)
    assert parsed.day == 1


def test_handle_429_mistral_cooldown_is_rolling(store, rotator):
    _add_key(store, "mistral", "key1")
    key = rotator.get_best_key("general_purpose")
    before = datetime.now(timezone.utc)
    cooldown = rotator.handle_429(key["key_id"], "mistral")
    parsed = datetime.fromisoformat(cooldown)
    delta = (parsed - before).total_seconds()
    assert 55 <= delta <= 75


def test_handle_success_increments_usage(store, rotator):
    _add_key(store, "groq", "key1")
    key = rotator.get_best_key("general_purpose")
    rotator.handle_success(key["key_id"], tokens_used=150)

    fetched = store.get_key_by_id(key["key_id"])
    assert fetched["requests_today"] == 1
    assert fetched["tokens_used_today"] == 150


# --- get_earliest_retry ---


def test_get_earliest_retry_no_keys(rotator):
    assert rotator.get_earliest_retry("general_purpose") is None


def test_get_earliest_retry_no_cooldowns(store, rotator):
    _add_key(store, "groq", "key1")
    # Fresh key with no cooldown - store.get_active_keys returns it,
    # but cooldown_until is None so get_earliest_retry returns None
    assert rotator.get_earliest_retry("general_purpose") is None


def test_get_earliest_retry_returns_min_cooldown(store, rotator):
    _add_key(store, "groq", "key1")
    _add_key(store, "mistral", "key2")
    keys = store.get_active_keys("general_purpose")

    t1 = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    t2 = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    store.record_usage(keys[0]["id"], tokens=0, was_429=True, cooldown_until=t1)
    store.record_usage(keys[1]["id"], tokens=0, was_429=True, cooldown_until=t2)

    earliest = rotator.get_earliest_retry("general_purpose")
    assert earliest == t2


# --- rotation state persistence ---


def test_rotation_state_persisted(store):
    rot = Rotator(store, PROVIDER_CONFIGS, rotate_every=2)
    _add_key(store, "groq", "key1")

    key = rot.get_best_key("general_purpose")
    rot.handle_success(key["key_id"], tokens_used=10)

    cursor, slot_counts = store.load_rotation_state("general_purpose")
    assert cursor >= 0
    assert isinstance(slot_counts, dict)
