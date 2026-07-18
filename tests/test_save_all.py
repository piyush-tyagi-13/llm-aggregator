"""Tests for the settings save-all endpoint (``POST /api/settings/save-all``).

This endpoint applies every provided setting to in-memory state and persists
to the SQLite DB.  We verify correctness by writing settings and reading them
back via the corresponding ``GET`` endpoints.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from llm_apipool.api.app import make_app

_MOCK_CONFIGS: dict[str, dict] = {
    "groq": {
        "models": ["llama-3.3-70b-versatile"],
        "default_model": "llama-3.3-70b-versatile",
    },
}


@pytest.fixture
def app():
    return make_app(_configs=_MOCK_CONFIGS)


@pytest.fixture
def client(app):
    return TestClient(app)


# ── Individual settings ─────────────────────────────────────────────


def test_save_all_strategy(client):
    """Save-all with just strategy updates the routing strategy."""
    resp = client.post("/api/settings/save-all", json={"strategy": "balanced"})
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    get_resp = client.get("/api/settings/routing-strategy")
    assert get_resp.json()["strategy"] == "balanced"


def test_save_all_strategy_priority(client):
    """Save-all with priority strategy."""
    resp = client.post("/api/settings/save-all", json={"strategy": "priority"})
    assert resp.status_code == 200

    get_resp = client.get("/api/settings/routing-strategy")
    assert get_resp.json()["strategy"] == "priority"


def test_save_all_sticky_enabled(client):
    """Save-all with sticky_enabled updates in-memory state."""
    # First set it to False
    client.post("/api/settings/save-all", json={"sticky_enabled": False})
    # Then verify
    resp = client.get("/api/settings/sticky")
    assert resp.json()["sticky_enabled"] is False


def test_save_all_sticky_ttl_ms(client):
    """Save-all with sticky_ttl_ms updates TTL."""
    resp = client.post("/api/settings/save-all", json={"sticky_ttl_ms": 60000})
    assert resp.status_code == 200

    get_resp = client.get("/api/settings/sticky")
    assert get_resp.json()["sticky_ttl_ms"] == 60000


def test_save_all_max_sticky_entries(client):
    """Save-all with max_sticky_entries updates max entries."""
    resp = client.post("/api/settings/save-all", json={"max_sticky_entries": 50})
    assert resp.status_code == 200

    get_resp = client.get("/api/settings/sticky")
    assert get_resp.json()["max_sticky_entries"] == 50


def test_save_all_handoff_mode_on_model_switch(client):
    """Save-all with handoff_mode set to 'on_model_switch'."""
    resp = client.post(
        "/api/settings/save-all", json={"handoff_mode": "on_model_switch"}
    )
    assert resp.status_code == 200

    get_resp = client.get("/api/settings/handoff")
    assert get_resp.json()["mode"] == "on_model_switch"


def test_save_all_handoff_mode_off(client):
    """Save-all with handoff_mode set to 'off'."""
    resp = client.post("/api/settings/save-all", json={"handoff_mode": "off"})
    assert resp.status_code == 200

    get_resp = client.get("/api/settings/handoff")
    assert get_resp.json()["mode"] == "off"


def test_save_all_tier_fallback_enabled(client):
    """Save-all with tier_fallback_enabled updates fallback state."""
    # First disable to ensure we toggle
    client.post("/api/settings/save-all", json={"tier_fallback_enabled": False})
    resp = client.post("/api/settings/save-all", json={"tier_fallback_enabled": True})
    assert resp.status_code == 200

    get_resp = client.get("/api/settings/tier-fallback")
    assert get_resp.json()["tier_fallback_enabled"] is True


def test_save_all_affinity_enabled(client):
    """Save-all with affinity_enabled updates affinity state."""
    resp = client.post("/api/settings/save-all", json={"affinity_enabled": True})
    assert resp.status_code == 200

    get_resp = client.get("/api/settings/affinity")
    assert get_resp.json()["affinity_enabled"] is True


def test_save_all_quality_tier(client):
    """Save-all with quality_tier updates rotator tier."""
    resp = client.post("/api/settings/save-all", json={"quality_tier": 2})
    assert resp.status_code == 200

    get_resp = client.get("/api/settings/tier-settings")
    assert get_resp.json()["quality_tier"] == 2


def test_save_all_max_fallback_tier(client):
    """Save-all with max_fallback_tier updates rotator fallback tier."""
    resp = client.post("/api/settings/save-all", json={"max_fallback_tier": 3})
    assert resp.status_code == 200

    get_resp = client.get("/api/settings/tier-settings")
    assert get_resp.json()["max_fallback_tier"] == 3


def test_save_all_fallback_config(client):
    """Save-all with fallback dict updates fallback settings."""
    fb = {
        "max_attempts_same_key": 3,
        "max_attempts_same_provider": 5,
        "max_attempts_all_providers": 10,
        "cooldown_on_failure_ms": 2000,
    }
    resp = client.post("/api/settings/save-all", json={"fallback": fb})
    assert resp.status_code == 200

    get_resp = client.get("/api/settings/fallback")
    data = get_resp.json()
    assert data["max_attempts_same_key"] == 3
    assert data["max_attempts_same_provider"] == 5
    assert data["max_attempts_all_providers"] == 10
    assert data["cooldown_on_failure_ms"] == 2000


def test_save_all_forced_models(client):
    """Save-all with forced_models sets routing overrides."""
    resp = client.post(
        "/api/settings/save-all", json={"forced_models": ["gpt-4o", "claude-3"]}
    )
    assert resp.status_code == 200

    get_resp = client.get("/api/settings/routing-override")
    data = get_resp.json()
    assert data["override_active"] is True
    assert "gpt-4o" in data["models"]
    assert "claude-3" in data["models"]


def test_save_all_clear_forced_models(client):
    """Save-all with empty forced_models clears routing overrides."""
    # First set some models
    client.post("/api/settings/save-all", json={"forced_models": ["gpt-4o"]})
    # Then clear them
    resp = client.post("/api/settings/save-all", json={"forced_models": []})
    assert resp.status_code == 200

    get_resp = client.get("/api/settings/routing-override")
    assert get_resp.json()["override_active"] is False


# ── All-at-once ─────────────────────────────────────────────────────


def test_save_all_all_fields(client):
    """All fields can be saved in a single request."""
    payload = {
        "strategy": "priority",
        "sticky_enabled": True,
        "sticky_ttl_ms": 120000,
        "max_sticky_entries": 100,
        "handoff_mode": "on_model_switch",
        "quality_tier": 1,
        "max_fallback_tier": 4,
        "tier_fallback_enabled": True,
        "affinity_enabled": False,
        "fallback": {
            "max_attempts_same_key": 2,
            "max_attempts_same_provider": 4,
            "max_attempts_all_providers": 8,
            "cooldown_on_failure_ms": 1500,
        },
        "forced_models": ["llama-3.3-70b-versatile"],
    }
    resp = client.post("/api/settings/save-all", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert len(data["errors"]) == 0

    # Verify each setting
    assert client.get("/api/settings/routing-strategy").json()["strategy"] == "priority"
    sticky = client.get("/api/settings/sticky").json()
    assert sticky["sticky_enabled"] is True
    assert sticky["sticky_ttl_ms"] == 120000
    assert sticky["max_sticky_entries"] == 100
    assert client.get("/api/settings/handoff").json()["mode"] == "on_model_switch"
    assert (
        client.get("/api/settings/tier-fallback").json()["tier_fallback_enabled"]
        is True
    )
    assert client.get("/api/settings/affinity").json()["affinity_enabled"] is False
    assert client.get("/api/settings/tier-settings").json()["quality_tier"] == 1
    assert (
        client.get("/api/settings/routing-override").json()["override_active"] is True
    )


# ── Partial updates ─────────────────────────────────────────────────


def test_save_all_partial_no_change_to_omitted(client):
    """Settings not included in the payload keep their previous values."""
    # Set initial values
    client.post(
        "/api/settings/save-all",
        json={
            "strategy": "balanced",
            "sticky_enabled": True,
            "handoff_mode": "on_model_switch",
        },
    )

    # Send a partial update
    resp = client.post("/api/settings/save-all", json={"strategy": "priority"})
    assert resp.status_code == 200

    # strategy changed
    assert client.get("/api/settings/routing-strategy").json()["strategy"] == "priority"
    # sticky should still be True (not affected by omission)
    assert client.get("/api/settings/sticky").json()["sticky_enabled"] is True
    # handoff should still be "on_model_switch"
    assert client.get("/api/settings/handoff").json()["mode"] == "on_model_switch"


def test_save_all_partial_null_field_is_ignored(client):
    """A field explicitly set to null is omitted (not applied)."""
    # First set sticky to True
    client.post("/api/settings/save-all", json={"sticky_enabled": True})
    # Then send a payload with sticky_enabled explicitly null
    resp = client.post("/api/settings/save-all", json={"sticky_enabled": None})
    assert resp.status_code == 200

    # The existing value should remain True
    assert client.get("/api/settings/sticky").json()["sticky_enabled"] is True


# ── Error handling ──────────────────────────────────────────────────


def test_save_all_invalid_strategy(client):
    """Invalid strategy name returns an error entry instead of 500."""
    resp = client.post("/api/settings/save-all", json={"strategy": "nonexistent"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert len(data["errors"]) == 1
    assert "strategy" in data["errors"][0]


def test_save_all_invalid_sticky_ttl(client):
    """Negative sticky_ttl_ms returns an error entry."""
    resp = client.post("/api/settings/save-all", json={"sticky_ttl_ms": -1})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True  # overall success (errors collected)
    assert len(data["errors"]) == 1
    assert "sticky_ttl_ms" in data["errors"][0]


def test_save_all_invalid_max_sticky_entries(client):
    """Negative max_sticky_entries returns an error entry."""
    resp = client.post("/api/settings/save-all", json={"max_sticky_entries": -10})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["errors"]) == 1
    assert "max_sticky_entries" in data["errors"][0]


def test_save_all_invalid_handoff_mode(client):
    """Invalid handoff mode returns an error entry."""
    resp = client.post("/api/settings/save-all", json={"handoff_mode": "bogus"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["errors"]) >= 1
    assert any("handoff_mode" in e for e in data["errors"])


def test_save_all_invalid_quality_tier(client):
    """Quality tier outside 1-4 range returns an error entry."""
    resp = client.post("/api/settings/save-all", json={"quality_tier": 99})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["errors"]) == 1
    assert "quality_tier" in data["errors"][0]


def test_save_all_invalid_max_fallback_tier(client):
    """Fallback tier outside 1-4 range returns an error entry."""
    resp = client.post("/api/settings/save-all", json={"max_fallback_tier": 0})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["errors"]) == 1
    assert "max_fallback_tier" in data["errors"][0]


def test_save_all_multiple_errors(client):
    """Multiple invalid fields produce multiple error entries."""
    resp = client.post(
        "/api/settings/save-all",
        json={
            "quality_tier": 99,
            "sticky_ttl_ms": -5,
            "handoff_mode": "bogus",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["errors"]) == 3  # all three fields are invalid
    assert data["success"] is True  # errors collected but overall call succeeds


# ── Empty / no-op ───────────────────────────────────────────────────


def test_save_all_empty_payload(client):
    """Empty payload is a no-op success."""
    resp = client.post("/api/settings/save-all", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert len(data["errors"]) == 0


def test_save_all_affinity_disables_sticky(client):
    """Enabling affinity automatically disables sticky."""
    # First enable sticky
    client.post("/api/settings/save-all", json={"sticky_enabled": True})
    # Then enable affinity
    client.post("/api/settings/save-all", json={"affinity_enabled": True})

    # Verify: affinity should be on, sticky should be off
    assert client.get("/api/settings/affinity").json()["affinity_enabled"] is True
    assert client.get("/api/settings/sticky").json()["sticky_enabled"] is False


def test_save_all_quality_tier_greater_than_max_fallback_returns_error(client):
    """Setting quality_tier > max_fallback_tier must return a validation error."""
    resp = client.post(
        "/api/settings/save-all",
        json={
            "quality_tier": 3,
            "max_fallback_tier": 1,
        },
    )
    data = resp.json()
    assert resp.status_code == 200
    assert any("quality_tier" in e for e in data.get("errors", [])) or any(
        "max_fallback_tier" in e for e in data.get("errors", [])
    ), f"Expected error about quality_tier/max_fallback_tier, got: {data}"
