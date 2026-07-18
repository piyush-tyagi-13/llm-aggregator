"""Tests for bulk import endpoints (auto-import + commit-import).

Endpoints under test
--------------------
* ``POST /api/keys/auto-import`` — analyse key text, probe ambiguous keys
* ``POST /api/keys/commit-import`` — persist analysed keys
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from llm_apipool.api.app import make_app

# A minimal provider config containing both unique-prefix providers and
# OpenAI-compatible providers (to trigger probing).
_MOCK_CONFIGS: dict[str, dict] = {
    "groq": {
        "models": ["llama-3.3-70b-versatile"],
        "default_model": "llama-3.3-70b-versatile",
        "openai_compatible": True,
    },
    "cerebras": {
        "models": ["claude-3-haiku"],
        "default_model": "claude-3-haiku",
        "openai_compatible": True,
    },
    "openai": {
        "models": ["gpt-4o"],
        "default_model": "gpt-4o",
        "openai_compatible": True,
    },
}


# ── Auto-import analysis tests ──────────────────────────────────────


@pytest.fixture
def app():
    return make_app(_configs=_MOCK_CONFIGS)


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture(autouse=True)
def _patch_bulk_probing():
    """Prevent real HTTP calls during key probing.

    By default, probe calls return *all candidates as failing*, so every
    ``sk-*`` key comes back as ``"unknown"`` unless we explicitly set
    probe results.
    """
    with patch(
        "llm_apipool.api.routes.bulk_import.check_key_against_provider",
        new_callable=AsyncMock,
    ) as mock_check:
        mock_check.return_value = ("provider", False, "mocked-fail")
        yield mock_check


def test_auto_import_empty_text(client):
    """Empty text returns empty results."""
    resp = client.post("/api/keys/auto-import", json={"text": ""})
    assert resp.status_code == 200
    data = resp.json()
    assert data["summary"]["total"] == 0
    assert all(len(v) == 0 for v in data["keys"].values())


def test_auto_import_blank_lines(client):
    """Blank and comment lines are skipped."""
    text = "\n\n  \n# comment\n// another\n"
    resp = client.post("/api/keys/auto-import", json={"text": text})
    assert resp.status_code == 200
    assert resp.json()["summary"]["total"] == 0


def test_auto_import_unique_prefix_key(client):
    """Keys with unique prefixes are classified as 'auto' without probing."""
    text = "gsk_abc123def456\nhf_validtoken789\n"
    resp = client.post("/api/keys/auto-import", json={"text": text})
    assert resp.status_code == 200
    data = resp.json()
    auto_keys = data["keys"]["auto"]
    assert len(auto_keys) == 2
    providers = {k["candidates"][0] for k in auto_keys}
    assert "groq" in providers
    assert "huggingface_router" in providers


def test_auto_import_sk_probe_key_all_fail(client):
    """sk-* keys with no passing probe come back as 'unknown' in probed list.

    Note: ``sk-proj-*`` keys map to ``openai`` via unique prefix and are
    classified as ``auto``.  Generic ``sk-*`` keys (no unique-prefix match)
    that are long enough to match the regex are sent to probing.
    """
    text = "sk-abcdefghijklmnopqrstuvwxyz123\n"
    resp = client.post("/api/keys/auto-import", json={"text": text})
    assert resp.status_code == 200
    data = resp.json()
    probed = data["keys"]["probed"]
    assert len(probed) == 1
    assert probed[0]["status"] == "unknown"
    assert probed[0]["detected_provider"] is None


def test_auto_import_probe_success(client, _patch_bulk_probing):
    """When exactly one probe passes, the key is 'confirmed'."""
    mock_check = _patch_bulk_probing

    async def _side_effect(provider, key, timeout, configs):
        if provider == "groq" and "test-probe" in key:
            return (provider, True, "mocked-ok")
        return (provider, False, "mocked-fail")

    mock_check.side_effect = _side_effect

    text = "sk-test-probe-key-abcdefghijklm\n"
    resp = client.post("/api/keys/auto-import", json={"text": text})
    assert resp.status_code == 200
    data = resp.json()
    probed = data["keys"]["probed"]
    assert len(probed) == 1
    assert probed[0]["status"] == "confirmed"
    assert probed[0]["detected_provider"] == "groq"


def test_auto_import_probe_ambiguous(client, _patch_bulk_probing):
    """When multiple probes pass, the key is 'ambiguous'."""
    mock_check = _patch_bulk_probing

    async def _side_effect(provider, key, timeout, configs):
        if "ambig" in key:
            return (provider, True, "mocked-ok")
        return (provider, False, "mocked-fail")

    mock_check.side_effect = _side_effect

    text = "sk-ambig-key-abcdefghijklmnop\n"
    resp = client.post("/api/keys/auto-import", json={"text": text})
    assert resp.status_code == 200
    data = resp.json()
    probed = data["keys"]["probed"]
    assert len(probed) == 1
    assert probed[0]["status"] == "ambiguous"
    assert probed[0]["detected_provider"] is None


def test_auto_import_mixed_keys(client):
    """A mix of auto, probe, and unknown keys is correctly separated."""
    text = (
        "gsk_unique123456\n"  # auto → groq
        "sk-abcdefghijklmnopqrstuvwxyz\n"  # probe → unknown (all fail)
        "badkey\n"  # unknown
    )
    resp = client.post("/api/keys/auto-import", json={"text": text})
    assert resp.status_code == 200
    data = resp.json()
    keys = data["keys"]
    assert len(keys["auto"]) == 1
    assert len(keys["probed"]) == 1
    assert len(keys["unknown"]) == 1
    assert data["summary"]["total"] == 3


def test_auto_import_duplicates_skipped(client):
    """Duplicate keys are included only once."""
    text = "gsk_abc123\ngsk_abc123\n"
    resp = client.post("/api/keys/auto-import", json={"text": text})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["keys"]["auto"]) == 1
    assert data["summary"]["total"] == 1


def test_auto_import_masked_key(client):
    """Keys ending with *** are sanitised before classification."""
    text = "gsk_abc123def***\n"
    resp = client.post("/api/keys/auto-import", json={"text": text})
    assert resp.status_code == 200
    data = resp.json()
    auto = data["keys"]["auto"]
    assert len(auto) == 1
    # The key should not include the trailing ***
    assert not auto[0]["key"].endswith("*")


def test_auto_import_summary_counts(client):
    """Summary counts match the actual classified keys."""
    text = (
        "gsk_a\n"  # auto
        "sk-abcdefghijklmnopqrstuvwxyz\n"  # probe → unknown
        "??unknown??\n"  # unknown
    )
    resp = client.post("/api/keys/auto-import", json={"text": text})
    data = resp.json()
    s = data["summary"]
    assert s["total"] == 3
    assert s["auto"] == 1
    assert s["unknown"] >= 1  # probe-fail + format-unknown


# ── Commit-import tests ─────────────────────────────────────────────


def test_commit_import_valid_keys(client, app):
    """Valid key entries are persisted."""
    keys = [
        {"key": "gsk_valid001", "provider": "groq"},
        {"key": "sk-abcdefghijklmnopqrvalid", "provider": "openai"},
    ]
    resp = client.post("/api/keys/commit-import", json={"keys": keys})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["imported"] == 2
    assert len(data["errors"]) == 0


def test_commit_import_missing_fields(client):
    """Entries missing key or provider are rejected with errors."""
    keys = [
        {"key": "", "provider": "groq"},
        {"key": "gsk_valid", "provider": ""},
        {"key": "", "provider": ""},
    ]
    resp = client.post("/api/keys/commit-import", json={"keys": keys})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert data["imported"] == 0
    assert len(data["errors"]) == 3


def test_commit_import_partial_errors(client):
    """Some valid, some invalid — valid ones are imported, errors reported."""
    keys = [
        {"key": "gsk_good", "provider": "groq"},
        {"key": "", "provider": "groq"},
        {"key": "sk-abcdefghijklmnop-also-good", "provider": "openai"},
    ]
    resp = client.post("/api/keys/commit-import", json={"keys": keys})
    data = resp.json()
    assert data["imported"] == 2
    assert len(data["errors"]) == 1


def test_commit_import_empty_list(client):
    """Empty key list imports nothing."""
    resp = client.post("/api/keys/commit-import", json={"keys": []})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["imported"] == 0


def test_commit_import_with_optional_fields(client):
    """Optional fields (capabilities, model, base_url_override) are accepted."""
    keys = [
        {
            "key": "gsk_opt001",
            "provider": "groq",
            "model": "llama-3.3-70b-versatile",
            "capabilities": ["general_purpose", "fast"],
            "base_url_override": "https://api.groq.com/openai/v1",
        },
    ]
    resp = client.post("/api/keys/commit-import", json={"keys": keys})
    assert resp.status_code == 200
    data = resp.json()
    assert data["imported"] == 1
    assert data["success"] is True


def test_commit_import_duplicate_keys(client):
    """Duplicate keys are still imported (DB handles duplicates)."""
    keys = [
        {"key": "gsk_dup001", "provider": "groq"},
        {"key": "gsk_dup001", "provider": "groq"},
    ]
    resp = client.post("/api/keys/commit-import", json={"keys": keys})
    data = resp.json()
    assert data["imported"] == 2  # DB allows multiple entries with same key


def test_commit_import_key_trimming(client):
    """Keys with surrounding whitespace are trimmed before import."""
    keys = [
        {"key": "  gsk_trimmed  ", "provider": "groq"},
    ]
    resp = client.post("/api/keys/commit-import", json={"keys": keys})
    data = resp.json()
    assert data["imported"] == 1
