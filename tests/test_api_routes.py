from __future__ import annotations


import pytest
from fastapi.testclient import TestClient

from llm_apipool.api.app import make_app
from llm_apipool.core.model_effort import (
    _reload_for_testing,
    clear_all_effort_configs,
    clear_global_effort_level,
    inject_effort_params,
    set_effort_config,
    set_global_effort_level,
)


@pytest.fixture
def app():
    return make_app(
        _configs={
            "groq": {
                "models": ["llama-3.3-70b-versatile"],
                "default_model": "llama-3.3-70b-versatile",
            },
        }
    )


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def authenticated_client(app):
    """Client with admin user logged in."""
    client = TestClient(app)
    # Create admin user (first user) and get session cookie
    client.post(
        "/api/auth/login", json={"email": "admin@test.com", "password": "testpass123"}
    )
    return client


@pytest.fixture(autouse=True)
def _reset_effort_state():
    """Reset ALL effort state (global + per-model) before each test."""
    _reload_for_testing()
    clear_all_effort_configs()
    yield


def test_root_endpoint(client):
    """Root serves the SPA (index.html) by default."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "text/html; charset=utf-8"
    assert "<!DOCTYPE html>" in resp.text


def test_settings_routing_strategy(authenticated_client):
    resp = authenticated_client.get("/api/settings/routing-strategy")
    assert resp.status_code == 200
    data = resp.json()
    assert "strategy" in data


def test_settings_sticky(authenticated_client):
    resp = authenticated_client.get("/api/settings/sticky")
    assert resp.status_code == 200
    data = resp.json()
    assert "sticky_enabled" in data


def test_settings_handoff(authenticated_client):
    resp = authenticated_client.get("/api/settings/handoff")
    assert resp.status_code == 200
    data = resp.json()
    assert "mode" in data


def test_analytics_overview(authenticated_client):
    resp = authenticated_client.get("/api/analytics/overview")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_keys" in data
    assert "active_keys" in data


def test_analytics_providers(authenticated_client):
    resp = authenticated_client.get("/api/analytics/providers")
    assert resp.status_code == 200
    data = resp.json()
    assert "penalties" in data


def test_models_list(client):
    resp = client.get("/v1/models")
    assert resp.status_code == 200
    data = resp.json()
    assert "data" in data
    assert "LLM-Apipool" in {m["id"] for m in data["data"]}


def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert data["status"] == "ok"


def test_audit_endpoint(client):
    resp = client.get("/audit")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


def test_list_providers(authenticated_client):
    resp = authenticated_client.get("/api/providers")
    assert resp.status_code == 200
    data = resp.json()
    assert "providers" in data


# ── Effort set-all tests ──────────────────────────────────────────────


def test_effort_presets_returned(client):
    """Effort presets endpoint returns preset definitions."""
    resp = client.get("/api/models/effort/presets")
    assert resp.status_code == 200
    data = resp.json()
    assert "openai" in data
    assert "anthropic" in data
    assert "deepseek" in data
    assert "google" in data
    # Check a known param shape
    openai_params = data["openai"]
    assert "default" in openai_params
    assert "reasoning_effort" in openai_params["default"]


def test_effort_set_all_low(client):
    """Set global effort to low level returns success."""
    resp = client.post("/api/models/effort/set-all", json={"level": "low"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["level"] == "low"


def test_effort_set_all_medium(client):
    """Set global effort to medium level returns success."""
    resp = client.post("/api/models/effort/set-all", json={"level": "medium"})
    assert resp.status_code == 200
    assert resp.json()["level"] == "medium"


def test_effort_set_all_high(client):
    """Set global effort to high level returns success."""
    resp = client.post("/api/models/effort/set-all", json={"level": "high"})
    assert resp.status_code == 200
    assert resp.json()["level"] == "high"


def test_effort_set_all_invalid_level(client):
    """Invalid effort level returns 400 error."""
    resp = client.post("/api/models/effort/set-all", json={"level": "extreme"})
    assert resp.status_code == 400
    data = resp.json()
    assert "error" in data
    assert data["error"]["type"] == "invalid_request_error"
    assert "extreme" in data["error"]["message"]


def test_effort_global_level_get_when_not_set(client):
    """Reading global effort before setting it returns None."""
    resp = client.get("/api/models/effort/global-level")
    assert resp.status_code == 200
    assert resp.json()["level"] is None


def test_effort_global_level_get_after_set(client):
    """Reading global effort after set-all returns the stored mapping."""
    client.post("/api/models/effort/set-all", json={"level": "high"})
    resp = client.get("/api/models/effort/global-level")
    assert resp.status_code == 200
    data = resp.json()
    assert data["level"] is not None
    assert data["level"]["openai"] == {"reasoning_effort": "high"}
    assert data["level"]["anthropic"] == {"thinking": True, "budget_tokens": 64_000}
    assert data["level"]["deepseek"] == {"thinking": True}


def test_effort_global_level_delete(client):
    """Deleting global effort clears it."""
    client.post("/api/models/effort/set-all", json={"level": "medium"})
    resp = client.delete("/api/models/effort/global-level")
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    # Verify it's gone
    resp = client.get("/api/models/effort/global-level")
    assert resp.json()["level"] is None


def test_effort_per_model_get(client):
    """Per-model effort config returns empty for unset models."""
    resp = client.get("/api/models/effort/openai:gpt-4o")
    assert resp.status_code == 200
    data = resp.json()
    assert data["model_key"] == "openai:gpt-4o"
    assert data["params"] == {}


def test_effort_per_model_set_and_get(client):
    """Setting per-model effort and reading it back works."""
    resp = client.put(
        "/api/models/effort",
        json={
            "model_key": "openai:gpt-4o",
            "params": {"reasoning_effort": "high"},
        },
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    resp = client.get("/api/models/effort/openai:gpt-4o")
    assert resp.status_code == 200
    data = resp.json()
    assert data["model_key"] == "openai:gpt-4o"
    assert data["params"] == {"reasoning_effort": "high"}


def test_effort_per_model_delete(client):
    """Deleting a per-model effort config works."""
    client.put(
        "/api/models/effort",
        json={
            "model_key": "openai:gpt-4o",
            "params": {"reasoning_effort": "high"},
        },
    )
    resp = client.request(
        "DELETE", "/api/models/effort", json={"model_key": "openai:gpt-4o"}
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    resp = client.get("/api/models/effort/openai:gpt-4o")
    assert resp.json()["params"] == {}


def test_effort_list_overrides(client):
    """Listing all effort overrides shows what's been set."""
    client.put(
        "/api/models/effort",
        json={
            "model_key": "openai:gpt-4o",
            "params": {"reasoning_effort": "high"},
        },
    )
    resp = client.get("/api/models/effort")
    assert resp.status_code == 200
    data = resp.json()
    overrides = data.get("overrides", {})
    assert "openai:gpt-4o" in overrides
    assert overrides["openai:gpt-4o"] == {"reasoning_effort": "high"}


# ── Unit-level injection behavior ─────────────────────────────────────


def test_inject_with_global_override():
    """Global override params are injected when no per-model override exists."""
    _reload_for_testing()
    clear_all_effort_configs()
    set_global_effort_level("high")

    kwargs: dict = {}
    result = inject_effort_params("openai", "gpt-4o", kwargs)
    assert "reasoning_effort" in result
    assert result["reasoning_effort"] == "high"


def test_inject_per_model_wins_over_global():
    """Per-model override takes priority over global level."""
    _reload_for_testing()
    clear_all_effort_configs()
    set_global_effort_level("low")
    set_effort_config("openai:gpt-4o", {"reasoning_effort": "high"})

    kwargs: dict = {}
    result = inject_effort_params("openai", "gpt-4o", kwargs)
    assert result["reasoning_effort"] == "high"


def test_inject_global_override_anthropic():
    """Global override correctly maps to Anthropic thinking params."""
    _reload_for_testing()
    clear_all_effort_configs()
    set_global_effort_level("medium")

    kwargs: dict = {}
    result = inject_effort_params("anthropic", "claude-sonnet-4-20250514", kwargs)
    assert isinstance(result.get("thinking"), dict)
    assert result["thinking"]["type"] == "enabled"
    assert result["thinking"].get("budget_tokens") == 16_000


def test_inject_global_override_deepseek():
    """Global override correctly maps to DeepSeek thinking params."""
    _reload_for_testing()
    clear_all_effort_configs()
    set_global_effort_level("high")

    kwargs: dict = {}
    result = inject_effort_params("deepseek", "deepseek-chat", kwargs)
    assert result.get("thinking") is True


def test_inject_unaffected_provider():
    """Providers not in the global mapping are unaffected."""
    _reload_for_testing()
    clear_all_effort_configs()
    set_global_effort_level("high")

    kwargs: dict = {}
    result = inject_effort_params("groq", "llama-3.3-70b-versatile", kwargs)
    # groq has no effort params in presets -> no change
    assert result == {}


def test_inject_global_cleared():
    """After clearing global level, injection falls back to preset defaults."""
    _reload_for_testing()
    clear_all_effort_configs()
    set_global_effort_level("high")
    clear_global_effort_level()

    kwargs: dict = {}
    result = inject_effort_params("openai", "gpt-4o", kwargs)
    # Default for openai reasoning_effort is "medium"
    assert result.get("reasoning_effort") == "medium"
