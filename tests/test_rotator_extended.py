"""Extended tests for rotator.py - quality tier, peek_current_key, edge cases."""

from __future__ import annotations

import json

import pytest

from llm_apipool.key_store import KeyStore
from llm_apipool.rotator import (
    Rotator,
    _load_model_tiers,
    _resolve_model,
    _score_key,
    get_model_tier,
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
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "rotator_ext_test.db"


@pytest.fixture
def store(db_path):
    return KeyStore(db_path=db_path)


@pytest.fixture
def rotator(store):
    return Rotator(store, PROVIDER_CONFIGS, rotate_every=3)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _add_key(
    store, provider, api_key, category="general_purpose", model=None, **kwargs
):
    store.register_key(provider, api_key, category, model, **kwargs)
    return store.get_active_keys(category)[-1]


# ===================================================================
# _load_model_tiers
# ===================================================================


def test_load_model_tiers_file_not_exists(monkeypatch, tmp_path):
    """Returns {} when model_quality.json is absent."""
    fake = tmp_path / "model_quality.json"
    monkeypatch.setattr("llm_apipool.rotator._MODEL_TIER_PATH", fake)
    monkeypatch.setattr("llm_apipool.rotator._MODEL_TIER_MAP", None)
    assert _load_model_tiers() == {}


def test_load_model_tiers_empty_file(monkeypatch, tmp_path):
    """Returns {} when the file is empty (triggers JSONDecodeError)."""
    fake = tmp_path / "model_quality.json"
    fake.write_text("")
    monkeypatch.setattr("llm_apipool.rotator._MODEL_TIER_PATH", fake)
    monkeypatch.setattr("llm_apipool.rotator._MODEL_TIER_MAP", None)
    assert _load_model_tiers() == {}


def test_load_model_tiers_invalid_json(monkeypatch, tmp_path):
    """Returns {} when the file contains invalid JSON."""
    fake = tmp_path / "model_quality.json"
    fake.write_text("{invalid")
    monkeypatch.setattr("llm_apipool.rotator._MODEL_TIER_PATH", fake)
    monkeypatch.setattr("llm_apipool.rotator._MODEL_TIER_MAP", None)
    assert _load_model_tiers() == {}


def test_load_model_tiers_valid_file(monkeypatch, tmp_path):
    """Returns correct {model: tier} mapping with valid JSON."""
    data = {"tier1": ["gpt-4o"], "tier2": ["gpt-4o-mini"], "tier3": [], "tier4": []}
    fake = tmp_path / "model_quality.json"
    fake.write_text(json.dumps(data))
    monkeypatch.setattr("llm_apipool.rotator._MODEL_TIER_PATH", fake)
    monkeypatch.setattr("llm_apipool.rotator._MODEL_TIER_MAP", None)
    result = _load_model_tiers()
    assert result == {"gpt-4o": 1, "gpt-4o-mini": 2}


def test_load_model_tiers_caching(monkeypatch, tmp_path):
    """Second call returns cached result without re-reading the file."""
    fake = tmp_path / "model_quality.json"
    data = {"tier1": ["gpt-4o"], "tier2": [], "tier3": [], "tier4": []}
    fake.write_text(json.dumps(data))
    monkeypatch.setattr("llm_apipool.rotator._MODEL_TIER_PATH", fake)
    monkeypatch.setattr("llm_apipool.rotator._MODEL_TIER_MAP", None)

    # First call populates cache
    first = _load_model_tiers()
    assert first == {"gpt-4o": 1}

    # Modify the file behind the scenes — mtime-based cache sees the change
    fake.write_text(json.dumps({"tier1": [], "tier2": [], "tier3": [], "tier4": []}))

    # Second call re-reads because mtime changed
    second = _load_model_tiers()
    assert second == {}


# ===================================================================
# get_model_tier
# ===================================================================


def test_get_model_tier_known(monkeypatch):
    """Returns correct tier for a known model."""
    monkeypatch.setattr("llm_apipool.rotator._MODEL_TIER_MAP", {"gpt-4o": 1})
    assert get_model_tier("gpt-4o") == 1


def test_get_model_tier_unknown(monkeypatch):
    """Returns tier 4 (fallback) for an unknown model."""
    monkeypatch.setattr("llm_apipool.rotator._MODEL_TIER_MAP", {"gpt-4o": 1})
    assert get_model_tier("unknown-model") == 4


# ===================================================================
# _resolve_model
# ===================================================================


def test_resolve_model_returns_default():
    """Returns default_model when present."""
    cfg = {"default_model": "llama-3.3-70b"}
    assert _resolve_model(cfg, "general_purpose") == "llama-3.3-70b"


def test_resolve_model_no_default():
    """Returns '' when no default_model."""
    cfg = {}
    assert _resolve_model(cfg, "general_purpose") == ""


def test_resolve_model_ignores_models_key():
    """Ignores legacy models key; only uses default_model."""
    cfg = {"models": ["model-a", "model-b"], "default_model": "default"}
    assert _resolve_model(cfg, "general_purpose") == "default"
    # Even if models key is a dict with capability groups, ignore it
    cfg2 = {"models": {"general_purpose": ["gp-model"]}, "default_model": "my-model"}
    assert _resolve_model(cfg2, "general_purpose") == "my-model"


# ===================================================================
# _score_key
# ===================================================================


def test_score_key_with_rpd():
    """Score = rpd - requests_today when rpd is present."""
    key = {"requests_today": 10}
    cfg = {"limits": {"rpd": 100}}
    assert _score_key(key, cfg) == 90.0


def test_score_key_without_rpd():
    """Score = -requests_today when rpd is absent."""
    key = {"requests_today": 10}
    cfg = {}
    assert _score_key(key, cfg) == -10.0


# ===================================================================
# Rotator.__init__ validation
# ===================================================================


def test_init_quality_tier_too_low(store):
    with pytest.raises(ValueError, match="quality_tier"):
        Rotator(store, {}, quality_tier=0)


def test_init_quality_tier_too_high(store):
    with pytest.raises(ValueError, match="quality_tier"):
        Rotator(store, {}, quality_tier=5)


def test_init_max_fallback_tier_too_low(store):
    with pytest.raises(ValueError, match="max_fallback_tier"):
        Rotator(store, {}, max_fallback_tier=0)


def test_init_max_fallback_tier_too_high(store):
    with pytest.raises(ValueError, match="max_fallback_tier"):
        Rotator(store, {}, max_fallback_tier=5)


def test_init_quality_below_max_fallback(store):
    with pytest.raises(ValueError, match="quality"):
        Rotator(store, {}, quality_tier=3, max_fallback_tier=2)


# ===================================================================
# peek_current_key
# ===================================================================


def test_peek_current_key_no_keys(rotator):
    """Returns None when there are no active keys."""
    assert rotator.peek_current_key("general_purpose") is None


def test_peek_current_key_single_key(store, rotator):
    """Returns the correct key info with a single key."""
    _add_key(store, "groq", "key1", model="llama-3.3-70b-versatile")
    result = rotator.peek_current_key("general_purpose")
    assert result is not None
    assert result["key_id"] == 1
    assert result["provider"] == "groq"
    assert result["model"] == "llama-3.3-70b-versatile"
    assert result["cycle_position"] == 1
    assert result["rotate_every"] == 3
    # Ensure peek does NOT return api_key or base_url
    assert "api_key" not in result
    assert "base_url" not in result


def test_peek_current_key_multiple_keys(store, rotator):
    """Returns the first key when multiple keys exist."""
    _add_key(store, "groq", "key1", model="llama-3.3-70b-versatile")
    _add_key(store, "groq", "key2", model="llama-3.1-8b-instant")
    result = rotator.peek_current_key("general_purpose")
    assert result is not None
    # Both keys should be valid; just check structure
    assert "key_id" in result
    assert "provider" in result


def test_peek_current_key_str_capability(store, rotator):
    """Works when capabilities is a string instead of list."""
    _add_key(store, "groq", "key1", model="llama-3.3-70b-versatile")
    result = rotator.peek_current_key("general_purpose")
    assert result is not None
    assert result["key_id"] == 1


def test_peek_current_key_does_not_mutate_slot_count(store):
    """Peek does not modify slot_count (uses a copy)."""
    rot = Rotator(store, PROVIDER_CONFIGS, rotate_every=1)
    _add_key(store, "groq", "key1", model="llama-3.3-70b-versatile")

    # Use the key once so slot_count = 1
    k = rot.get_best_key("general_purpose")
    rot.handle_success(k["key_id"], tokens_used=10)

    # slot_count should be 1 now
    assert rot._slot_count.get(1, 0) == 1  # noqa: SLF001

    # Peek should return None (key is exhausted)
    peeked = rot.peek_current_key("general_purpose")
    assert peeked is None

    # slot_count should still be 1 (peek didn't mutate)
    assert rot._slot_count.get(1, 0) == 1  # noqa: SLF001


def test_peek_current_key_after_partial_usage(store):
    """Peek returns the next available key when the first is exhausted."""
    rot = Rotator(store, PROVIDER_CONFIGS, rotate_every=1)
    _add_key(store, "groq", "key1", model="llama-3.3-70b-versatile")
    _add_key(store, "groq", "key2", model="llama-3.1-8b-instant")

    # Use key1
    k1 = rot.get_best_key("general_purpose")
    rot.handle_success(k1["key_id"], tokens_used=10)

    # Peek should return key2 (key1 is exhausted with slot_count=1)
    peeked = rot.peek_current_key("general_purpose")
    assert peeked is not None
    assert peeked["key_id"] != k1["key_id"]

    # get_best_key should also return key2
    k2 = rot.get_best_key("general_purpose")
    assert k2 is not None
    assert k2["key_id"] == peeked["key_id"]


# ===================================================================
# get_best_key — quality tier filtering & edge cases
# ===================================================================


def test_get_best_key_filters_by_quality_tier(monkeypatch, store):
    """Only keys within [quality_tier, max_fallback_tier] are considered."""
    monkeypatch.setattr(
        "llm_apipool.rotator._MODEL_TIER_MAP",
        {"gpt-4o": 1, "llama-3.1-8b-instant": 3},
    )
    cfg = {
        "groq": {
            "capabilities": ["general_purpose"],
            "base_url": "https://api.groq.com/openai/v1",
            "openai_compatible": True,
            "limits": {"rpm": 30, "rpd": 14400},
            "default_model": "llama-3.3-70b-versatile",
            "models": [],
        },
    }
    rot = Rotator(store, cfg, rotate_every=3, quality_tier=1, max_fallback_tier=1)
    store.register_key("groq", "key1", "general_purpose", "gpt-4o")
    store.register_key("groq", "key2", "general_purpose", "llama-3.1-8b-instant")
    key = rot.get_best_key("general_purpose")
    assert key is not None
    assert key["model"] == "gpt-4o"


def test_get_best_key_falls_back_to_lower_tier(monkeypatch, store):
    """Falls back to lower tier when preferred tier keys are exhausted."""
    monkeypatch.setattr(
        "llm_apipool.rotator._MODEL_TIER_MAP",
        {"gpt-4o": 1, "llama-3.1-8b-instant": 3},
    )
    cfg = {
        "groq": {
            "capabilities": ["general_purpose"],
            "base_url": "https://api.groq.com/openai/v1",
            "openai_compatible": True,
            "limits": {"rpm": 30, "rpd": 14400},
            "default_model": "llama-3.3-70b-versatile",
            "models": [],
        },
    }
    rot = Rotator(store, cfg, rotate_every=1, quality_tier=1, max_fallback_tier=3)
    store.register_key("groq", "key1", "general_purpose", "gpt-4o")
    store.register_key("groq", "key2", "general_purpose", "llama-3.1-8b-instant")

    # Exhaust key1 (tier 1)
    k1 = rot.get_best_key("general_purpose")
    rot.handle_success(k1["key_id"], tokens_used=10)

    # Should fall back to key2 (tier 3)
    k2 = rot.get_best_key("general_purpose")
    assert k2 is not None
    assert k2["model"] == "llama-3.1-8b-instant"


def test_get_best_key_formats_account_id(store):
    """Base URL with {account_id} placeholder is correctly formatted."""
    cfg = {
        "groq": {
            "capabilities": ["general_purpose"],
            "base_url": "https://api.groq.com/openai/v1",
            "openai_compatible": True,
            "limits": {"rpm": 30, "rpd": 14400},
            "default_model": "llama-3.3-70b-versatile",
            "models": [],
        },
    }
    rot = Rotator(store, cfg, rotate_every=3)
    store.register_key(
        "groq",
        "key1",
        "general_purpose",
        "gpt-4o",
        base_url_override="https://api.groq.com/{account_id}/v1",
        extra_params={"account_id": "acct123"},
    )
    key = rot.get_best_key("general_purpose")
    assert key is not None
    assert key["base_url"] == "https://api.groq.com/acct123/v1"


def test_get_best_key_missing_account_id(store):
    """Base URL with {account_id} and missing extra_params produces empty."""
    cfg = {
        "groq": {
            "capabilities": ["general_purpose"],
            "base_url": "https://api.groq.com/{account_id}/v1",
            "openai_compatible": True,
            "limits": {"rpm": 30, "rpd": 14400},
            "default_model": "llama-3.3-70b-versatile",
            "models": [],
        },
    }
    rot = Rotator(store, cfg, rotate_every=3)
    store.register_key(
        "groq",
        "key1",
        "general_purpose",
        "gpt-4o",
    )
    key = rot.get_best_key("general_purpose")
    assert key is not None
    assert key["base_url"] == "https://api.groq.com//v1"


# ===================================================================
# _ensure_order edge cases
# ===================================================================


def test_ensure_order_skips_non_matching_capability(store, rotator):
    """Keys with capabilities that don't match are skipped (line 208)."""
    # Register a key with different capabilities
    store.register_key("groq", "key1", capabilities=["code"], model="gpt-4o")
    # Register a matching key so get_best_key doesn't return None
    store.register_key("groq", "key2", capabilities=["general_purpose"], model="gpt-4o")

    key = rotator.get_best_key("general_purpose")
    assert key is not None
    assert key["api_key"] == "key2"


def test_ensure_order_skips_non_matching_capability_str(store, rotator):
    """Capability matching works with string capabilities."""
    # Key with string capability (not list)
    store.register_key("groq", "key1", capabilities="code", model="gpt-4o")
    store.register_key("groq", "key2", capabilities="general_purpose", model="gpt-4o")

    key = rotator.get_best_key("general_purpose")
    assert key is not None
    assert key["api_key"] == "key2"


def test_get_best_key_returns_model_from_provider_config(store, rotator):
    """When key has no model, _resolve_model picks from config."""
    store.register_key("groq", "key1", "general_purpose", None)
    key = rotator.get_best_key("general_purpose")
    assert key is not None
    assert key["model"] == "llama-3.3-70b-versatile"


def test_get_best_key_str_capability(store, rotator):
    """get_best_key accepts a string capability."""
    store.register_key("groq", "key1", "general_purpose", "gpt-4o")
    key = rotator.get_best_key("general_purpose")
    assert key is not None
    assert key["model"] == "gpt-4o"


# ── quality_tier / max_fallback_tier invariant ────────────────────────────────


def test_set_quality_tier_enforces_invariant(store):
    """Setting quality_tier above max_fallback_tier should raise ValueError."""
    r = Rotator(store, PROVIDER_CONFIGS, quality_tier=2, max_fallback_tier=4)

    # Normal case: fine
    r.set_quality_tier(3)
    assert r.get_quality_tier() == 3

    # Lower max so we can test violation
    r.set_max_fallback_tier(3)

    # Raising quality_tier above max_fallback_tier should fail (both valid range)
    with pytest.raises(ValueError, match="must not exceed"):
        r.set_quality_tier(4)

    # quality_tier unchanged
    assert r.get_quality_tier() == 3


def test_set_max_fallback_tier_enforces_invariant(store):
    """Setting max_fallback_tier below quality_tier should raise ValueError."""
    r = Rotator(store, PROVIDER_CONFIGS, quality_tier=2, max_fallback_tier=4)

    # Normal case: fine
    r.set_max_fallback_tier(3)
    assert r.get_max_fallback_tier() == 3

    # Lowering max_fallback_tier below quality_tier should fail
    with pytest.raises(ValueError, match="must not be less"):
        r.set_max_fallback_tier(1)

    # max_fallback_tier unchanged
    assert r.get_max_fallback_tier() == 3


def test_config_change_invalidates_order_cache(tmp_path, store):
    """Changing quality_tier or max_fallback_tier must rebuild the order cache."""
    r = Rotator(store, PROVIDER_CONFIGS, quality_tier=1, max_fallback_tier=4)
    store.register_key(
        "groq",
        "test-key-1",
        capabilities="general_purpose",
        model="llama-3.3-70b-versatile",
    )  # tier 2

    # Normal: key at tier 2 is available (quality_tier=1 <= tier 2 <= max_fallback_tier=4)
    key = r.get_best_key("general_purpose")
    assert key is not None

    # Change quality_tier to 2 — tier 2 still within range (2 <= 2 <= 4)
    r.set_quality_tier(2)
    key = r.get_best_key("general_purpose")
    assert key is not None

    # Now set max_fallback_tier to 1 — only tier 1 keys
    r.set_quality_tier(1)
    r.set_max_fallback_tier(1)
    key = r.get_best_key("general_purpose")
    assert key is None, "Key in tier 2 should be filtered when max_fallback_tier=1"
