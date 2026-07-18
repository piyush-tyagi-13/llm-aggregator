"""Tests for core model database, ingestion, and free detection."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from llm_apipool.core.free_detection import detect_free_model, reload_catalog
from llm_apipool.core.model_db import (
    get_model_by_id,
    get_models,
    get_models_for_key,
    get_sync_status,
    link_key_to_model,
    mark_sync_complete,
    mark_sync_failed,
    upsert_catalog_source,
    upsert_model,
)
from llm_apipool.core.model_ingestion import (
    fetch_provider_models,
    normalize_model,
    sync_provider_models,
)

# ── Helpers ────────────────────────────────────────────────────────────────────


@pytest.fixture
def empty_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Return a fresh KeyStore + connection for testing DB operations."""
    monkeypatch.setenv("LLM_APIPOOL_DB", str(tmp_path / "test_models.db"))
    from llm_apipool.key_store import KeyStore

    store = KeyStore(db_path=tmp_path / "test_models.db")
    # Ensure new columns exist for test DB
    with store._conn() as conn:
        for col in (
            "max_input_tokens",
            "max_output_tokens",
            "supports_streaming",
            "supports_function_calling",
            "is_free",
            "is_deprecated",
            "tier",
            "owner",
            "raw_metadata",
            "last_updated_at",
            "last_checked_at",
        ):
            try:
                conn.execute(f"ALTER TABLE models ADD COLUMN {col} TEXT")
            except sqlite3.OperationalError:
                pass
        # Create tables needed for model registry tests
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS key_model_access (
                key_id INTEGER NOT NULL REFERENCES api_keys(id),
                model_db_id INTEGER NOT NULL REFERENCES models(id),
                is_active INTEGER NOT NULL DEFAULT 1,
                priority INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(key_id, model_db_id)
            );
            CREATE TABLE IF NOT EXISTS provider_catalog_sources (
                provider TEXT PRIMARY KEY,
                models_endpoint TEXT,
                requires_api_key INTEGER NOT NULL DEFAULT 1,
                free_detection_method TEXT,
                last_sync_at TEXT,
                sync_status TEXT NOT NULL DEFAULT 'pending'
            );
        """)
    return store


@pytest.fixture
def conn(empty_store):
    with empty_store._conn() as c:
        yield c


# ═══════════════════════════════════════════════════════════════════════════════
# model_db.py
# ═══════════════════════════════════════════════════════════════════════════════


class TestUpsertModel:
    def test_insert_and_retrieve(self, conn):
        mid = upsert_model(
            conn,
            "groq",
            "llama-3.3-70b-versatile",
            display_name="Llama 3.3 70B",
            context_window=131072,
            is_free=True,
            tier=1,
        )
        assert mid > 0
        row = get_model_by_id(conn, mid)
        assert row is not None
        assert row["model_id"] == "llama-3.3-70b-versatile"
        assert row["platform"] == "groq"
        assert row["context_window"] == 131072
        assert row["is_free"] == 1
        assert row["tier"] == 1

    def test_upsert_updates_existing(self, conn):
        mid1 = upsert_model(
            conn, "groq", "llama-3.3-70b-versatile", context_window=8192, tier=3
        )
        mid2 = upsert_model(
            conn, "groq", "llama-3.3-70b-versatile", context_window=131072, tier=1
        )
        assert mid1 == mid2  # same row
        row = get_model_by_id(conn, mid1)
        assert row["context_window"] == 131072

    def test_unique_provider_model(self, conn):
        upsert_model(conn, "openai", "gpt-4o")
        upsert_model(conn, "groq", "gpt-4o")  # same model_id, different provider
        rows = conn.execute("SELECT * FROM models").fetchall()
        assert len(rows) == 2


class TestLinkKeyToModel:
    def test_link_and_query(self, empty_store):
        store = empty_store
        # register a key to get a key_id
        result = store.register_key("groq", "gsk_test", capabilities="general_purpose")
        assert result["success"]
        keys = store.get_all_keys()
        key_id = keys[-1]["id"]

        with store._conn() as conn:
            mid = upsert_model(conn, "groq", "llama-3.3-70b-versatile")
            link_key_to_model(conn, key_id, mid)
        models = get_models_for_key(store._conn(), key_id)
        assert len(models) == 1
        assert models[0]["model_id"] == "llama-3.3-70b-versatile"

    def test_link_multiple_keys(self, empty_store):
        store = empty_store
        store.register_key("groq", "gsk_a", capabilities="general_purpose")
        store.register_key("groq", "gsk_b", capabilities="general_purpose")
        keys = store.get_all_keys()
        key_a, key_b = keys[-2]["id"], keys[-1]["id"]

        with store._conn() as conn:
            mid = upsert_model(conn, "groq", "llama-3.3-70b-versatile")
            link_key_to_model(conn, key_a, mid)
            link_key_to_model(conn, key_b, mid)

        assert len(get_models_for_key(store._conn(), key_a)) == 1
        assert len(get_models_for_key(store._conn(), key_b)) == 1


class TestGetModels:
    def test_filter_by_provider(self, empty_store):
        store = empty_store
        with store._conn() as conn:
            store.register_key("groq", "gsk_test1", capabilities=["general_purpose"])
            store.register_key("google", "AIza_test", capabilities=["general_purpose"])
            upsert_model(conn, "groq", "m1")
            upsert_model(conn, "google", "m2")
            rows = get_models(conn, provider="groq")
            assert all(r["platform"] == "groq" for r in rows)

    def test_filter_free_only(self, empty_store):
        store = empty_store
        with store._conn() as conn:
            store.register_key("groq", "gsk_test1", capabilities=["general_purpose"])
            store.register_key("openai", "sk_test", capabilities=["general_purpose"])
            upsert_model(conn, "groq", "free-model", is_free=True)
            upsert_model(conn, "openai", "paid-model", is_free=False)
            rows = get_models(conn, free_only=True)
            assert all(r["is_free"] == 1 for r in rows)
            assert len(rows) == 1

    def test_filter_tier(self, empty_store):
        store = empty_store
        with store._conn() as conn:
            store.register_key("groq", "gsk_test1", capabilities=["general_purpose"])
            store.register_key("google", "AIza_test", capabilities=["general_purpose"])
            upsert_model(conn, "groq", "t1", tier=1)
            upsert_model(conn, "google", "t4", tier=4)
            rows = get_models(conn, tier=4)
            assert len(rows) == 1
            assert rows[0]["model_id"] == "t4"

    def test_filter_min_context(self, empty_store):
        store = empty_store
        with store._conn() as conn:
            store.register_key("groq", "gsk_test1", capabilities=["general_purpose"])
            store.register_key("google", "AIza_test", capabilities=["general_purpose"])
            upsert_model(conn, "groq", "small", context_window=4096)
            upsert_model(conn, "google", "large", context_window=128000)
            rows = get_models(conn, min_context=100000)
            assert len(rows) == 1
            assert rows[0]["model_id"] == "large"

    def test_filter_search(self, empty_store):
        store = empty_store
        with store._conn() as conn:
            store.register_key("groq", "gsk_test1", capabilities=["general_purpose"])
            upsert_model(conn, "groq", "llama-3.3-70b-versatile")
            upsert_model(conn, "groq", "mixtral-8x7b")
            rows = get_models(conn, search="llama")
            assert len(rows) == 1

    def test_filter_supports_tools(self, empty_store):
        store = empty_store
        with store._conn() as conn:
            store.register_key("groq", "gsk_test1", capabilities=["general_purpose"])
            upsert_model(conn, "groq", "with-tools", supports_tools=True)
            upsert_model(conn, "groq", "no-tools", supports_tools=False)
            rows = get_models(conn, supports_tools=True)
            assert len(rows) == 1
            assert rows[0]["model_id"] == "with-tools"


class TestCatalogSources:
    def test_upsert_and_status(self, conn):
        upsert_catalog_source(
            conn,
            "groq",
            models_endpoint="https://api.groq.com/openai/v1/models",
            requires_api_key=True,
            free_detection_method="auto",
        )
        status = get_sync_status(conn, "groq")
        assert len(status) == 1
        assert status[0]["sync_status"] == "pending"

    def test_mark_sync_complete(self, conn):
        upsert_catalog_source(conn, "groq")
        mark_sync_complete(conn, "groq")
        status = get_sync_status(conn, "groq")
        assert status[0]["sync_status"] == "success"
        assert status[0]["last_sync_at"] is not None

    def test_mark_sync_failed(self, conn):
        upsert_catalog_source(conn, "groq")
        mark_sync_failed(conn, "groq")
        status = get_sync_status(conn, "groq")
        assert status[0]["sync_status"] == "failed"


# ═══════════════════════════════════════════════════════════════════════════════
# free_detection.py
# ═══════════════════════════════════════════════════════════════════════════════


class TestDetectFreeModel:
    def test_explicit_free_flag(self):
        assert detect_free_model("openai", {"id": "gpt-4", "free": True})

    def test_explicit_free_tier(self):
        assert detect_free_model("openai", {"id": "gpt-4", "free_tier": True})

    def test_model_id_pattern(self):
        assert detect_free_model("openrouter", {"id": "model:free"})
        assert detect_free_model("openrouter", {"id": "model-free"})
        assert detect_free_model("mistral", {"id": "mistral-free-trial"})

    def test_openrouter_pricing(self):
        assert detect_free_model("openrouter", {"id": "m", "pricing": {"free": True}})
        assert not detect_free_model(
            "openrouter", {"id": "m", "pricing": {"free": False}}
        )

    def test_provider_rule_true(self):
        assert detect_free_model("groq", {"id": "llama-3.3-70b"})
        assert detect_free_model("cerebras", {"id": "llama-3.3-70b"})
        assert detect_free_model("google", {"id": "gemini-2.0-flash"})

    def test_provider_rule_false(self):
        assert not detect_free_model("openai", {"id": "gpt-4o"})
        assert not detect_free_model("anthropic", {"id": "claude-3-opus"})
        assert not detect_free_model("deepseek", {"id": "deepseek-chat"})

    def test_provider_rule_mixed(self):
        assert detect_free_model("mistral", {"id": "mistral-free-trial"})
        assert not detect_free_model(
            "openrouter", {"id": "claude-sonnet", "pricing": {"free": False}}
        )

    def test_catalog_fallback(self, monkeypatch):
        # Create a temporary catalog
        catalog_path = (
            Path(__file__).resolve().parent.parent
            / "llm_apipool"
            / "config"
            / "free_models_catalog.json"
        )
        original = catalog_path.read_text() if catalog_path.exists() else "{}"
        try:
            catalog_path.write_text(json.dumps({"free_models": ["my-free-model"]}))
            reload_catalog()
            assert detect_free_model("unknown_provider", {"id": "my-free-model"})
        finally:
            catalog_path.write_text(original)
            reload_catalog()

    def test_unknown_provider_default_false(self):
        assert not detect_free_model("nonexistent_provider", {"id": "some-model"})


# ═══════════════════════════════════════════════════════════════════════════════
# model_ingestion.py
# ═══════════════════════════════════════════════════════════════════════════════


class TestNormalizeModel:
    def test_openai_format(self):
        raw = {
            "id": "gpt-4o-mini",
            "owned_by": "openai",
            "context_window": 128000,
            "max_output_tokens": 16384,
        }
        n = normalize_model("openai", raw)
        assert n["model_id"] == "gpt-4o-mini"
        assert n["owner"] == "openai"
        assert n["context_window"] == 128000

    def test_openrouter_format(self):
        raw = {
            "id": "claude-sonnet-4-6",
            "context_length": 200000,
            "pricing": {"free": False},
            "supports_tools": True,
        }
        n = normalize_model("openrouter", raw)
        assert n["context_window"] == 200000
        assert n["supports_tools"] is True
        assert n["is_free"] is False

    def test_google_format(self):
        raw = {
            "name": "models/gemini-2.0-flash",
            "input_token_limit": 1048576,
            "output_token_limit": 8192,
        }
        n = normalize_model("google", {"id": raw["name"], **raw})
        assert n["model_id"] == "models/gemini-2.0-flash"
        assert n["is_free"] is True

    def test_groq_format(self):
        raw = {"id": "llama-3.3-70b-versatile", "context_window": 131072, "rpm": 30}
        n = normalize_model("groq", raw)
        assert n["is_free"] is True
        assert n["rpm_limit"] == 30

    def test_capabilities_dict(self):
        raw = {
            "id": "test-model",
            "capabilities": {"vision": True, "tools": True, "function_calling": True},
        }
        n = normalize_model("test", raw)
        assert n["supports_vision"] is True
        assert n["supports_tools"] is True
        assert n["supports_function_calling"] is True

    def test_capabilities_list(self):
        raw = {
            "id": "test-model",
            "capabilities": ["vision", "tools", "function_calling"],
        }
        n = normalize_model("test", raw)
        assert n["supports_vision"] is True
        assert n["supports_tools"] is True

    def test_deprecated_flag(self):
        raw = {"id": "old-model", "deprecated": True}
        n = normalize_model("test", raw)
        assert n["is_deprecated"] is True

    def test_tier_map(self):
        raw = {"id": "frontier-model"}
        n = normalize_model("test", raw, tier_map={"frontier-model": 1})
        assert n["tier"] == 1

    def test_default_tier(self):
        raw = {"id": "unknown-model"}
        n = normalize_model("test", raw)
        assert n["tier"] == 4


class TestFetchProviderModels:
    @pytest.mark.asyncio
    @patch("llm_apipool.core.model_ingestion.httpx.AsyncClient")
    async def test_openai_response(self, mock_client_cls):
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client_cls.return_value = mock_client
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [{"id": "gpt-4o"}, {"id": "gpt-4o-mini"}]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_resp

        models = await fetch_provider_models(
            "https://api.openai.com/v1", "sk-test", "openai"
        )
        assert len(models) == 2
        assert models[0]["id"] == "gpt-4o"

    @pytest.mark.asyncio
    @patch("llm_apipool.core.model_ingestion.httpx.AsyncClient")
    async def test_non_openai_response(self, mock_client_cls):
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client_cls.return_value = mock_client
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"models": [{"id": "gemini-2.0-flash"}]}
        mock_resp.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_resp

        models = await fetch_provider_models(
            "https://generativelanguage.googleapis.com/v1beta", None, "google"
        )
        assert len(models) == 1

    @pytest.mark.asyncio
    @patch("llm_apipool.core.model_ingestion.httpx.AsyncClient")
    async def test_request_failure(self, mock_client_cls):
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client_cls.return_value = mock_client
        mock_client.get.side_effect = Exception("timeout")

        models = await fetch_provider_models("https://bad.url", None, "fail")
        assert models == []

    @pytest.mark.asyncio
    @patch("llm_apipool.core.model_ingestion.httpx.AsyncClient")
    async def test_list_response(self, mock_client_cls):
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client_cls.return_value = mock_client
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [{"id": "model-a"}, {"id": "model-b"}]
        mock_resp.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_resp

        models = await fetch_provider_models(
            "https://pollinations.ai", None, "pollinations"
        )
        assert len(models) == 2


class TestSyncProviderModels:
    @pytest.mark.asyncio
    @patch(
        "llm_apipool.core.model_ingestion.fetch_provider_models", new_callable=AsyncMock
    )
    async def test_sync_creates_models(self, mock_fetch, empty_store):
        mock_fetch.return_value = [
            {"id": "llama-3.3-70b-versatile", "context_window": 131072},
            {"id": "mixtral-8x7b", "context_window": 32768},
        ]
        result = await sync_provider_models(
            empty_store,
            "groq",
            {"groq": {"base_url": "https://api.groq.com/openai/v1"}},
            key_id=None,
        )
        assert result["models_upserted"] == 2
        assert result["error"] is None

    @pytest.mark.asyncio
    @patch(
        "llm_apipool.core.model_ingestion.fetch_provider_models", new_callable=AsyncMock
    )
    async def test_sync_links_key(self, mock_fetch, empty_store):
        store = empty_store
        store.register_key("groq", "gsk_test", capabilities="general_purpose")
        keys = store.get_all_keys()
        key_id = keys[-1]["id"]

        mock_fetch.return_value = [
            {"id": "llama-3.3-70b-versatile"},
        ]
        result = await sync_provider_models(
            store,
            "groq",
            {"groq": {"base_url": "https://api.groq.com/openai/v1"}},
            key_id=key_id,
        )
        assert result["models_upserted"] == 1

        models = get_models_for_key(store._conn(), key_id)
        assert len(models) == 1

    @pytest.mark.asyncio
    @patch(
        "llm_apipool.core.model_ingestion.fetch_provider_models", new_callable=AsyncMock
    )
    async def test_sync_no_models(self, mock_fetch, empty_store):
        mock_fetch.return_value = []
        result = await sync_provider_models(
            empty_store,
            "groq",
            {"groq": {"base_url": "https://api.groq.com/openai/v1"}},
        )
        assert result["models_upserted"] == 0
        assert result["error"] == "no_models_returned"

    @pytest.mark.asyncio
    @patch(
        "llm_apipool.core.model_ingestion.fetch_provider_models", new_callable=AsyncMock
    )
    async def test_sync_updates_catalog_source(self, mock_fetch, empty_store):
        mock_fetch.return_value = [{"id": "test-model"}]
        await sync_provider_models(
            empty_store,
            "groq",
            {"groq": {"base_url": "https://api.groq.com/openai/v1"}},
        )
        status = get_sync_status(empty_store._conn(), "groq")
        assert len(status) > 0
        assert status[0]["sync_status"] == "success"


# ═══════════════════════════════════════════════════════════════════════════════
# /v1/models endpoint integration
# ═══════════════════════════════════════════════════════════════════════════════


class TestModelsEndpoint:
    @pytest.fixture
    def app_with_models(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("LLM_APIPOOL_DB", str(tmp_path / "proxy_models.db"))
        from llm_apipool.key_store import KeyStore

        store = KeyStore(db_path=tmp_path / "proxy_models.db")

        # Register keys for the providers we'll seed models for
        store.register_key("groq", "gsk_test1", capabilities=["general_purpose"])
        store.register_key("openai", "sk_test", capabilities=["general_purpose"])
        store.register_key("google", "AIza_test", capabilities=["general_purpose"])

        # Ensure new columns exist
        with store._conn() as conn:
            for col in (
                "max_input_tokens",
                "max_output_tokens",
                "supports_streaming",
                "supports_function_calling",
                "is_free",
                "is_deprecated",
                "tier",
                "owner",
                "raw_metadata",
                "last_updated_at",
                "last_checked_at",
            ):
                try:
                    conn.execute(f"ALTER TABLE models ADD COLUMN {col} TEXT")
                except sqlite3.OperationalError:
                    pass
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS key_model_access (
                    key_id INTEGER NOT NULL REFERENCES api_keys(id),
                    model_db_id INTEGER NOT NULL REFERENCES models(id),
                    is_active INTEGER NOT NULL DEFAULT 1,
                    priority INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(key_id, model_db_id)
                );
                CREATE TABLE IF NOT EXISTS provider_catalog_sources (
                    provider TEXT PRIMARY KEY,
                    models_endpoint TEXT,
                    requires_api_key INTEGER NOT NULL DEFAULT 1,
                    free_detection_method TEXT,
                    last_sync_at TEXT,
                    sync_status TEXT NOT NULL DEFAULT 'pending'
                );
            """)

            # Seed some models
            upsert_model(
                conn,
                "groq",
                "llama-3.3-70b-versatile",
                display_name="Llama 3.3 70B",
                context_window=131072,
                tier=1,
                is_free=True,
                supports_tools=True,
            )
            upsert_model(
                conn,
                "groq",
                "mixtral-8x7b-32768",
                context_window=32768,
                tier=2,
                is_free=True,
            )
            upsert_model(
                conn, "openai", "gpt-4o", context_window=128000, tier=1, is_free=False
            )
            upsert_model(
                conn,
                "google",
                "gemini-2.0-flash",
                context_window=1048576,
                tier=1,
                is_free=True,
                supports_vision=True,
            )

        from llm_apipool.api.app import _load_provider_configs

        configs = _load_provider_configs()
        from llm_apipool.api.routes.models import _create_models_router

        router = _create_models_router(configs, store=store)
        return router

    @pytest.fixture
    def client(self, app_with_models, monkeypatch):
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(app_with_models)
        from fastapi.testclient import TestClient

        return TestClient(app)

    def test_list_models(self, client):
        resp = client.get("/v1/models")
        assert resp.status_code == 200
        body = resp.json()
        assert body["object"] == "list"
        assert len(body["data"]) >= 4

    def test_filters_free_only(self, client):
        resp = client.get("/v1/models?free_only=true")
        assert resp.status_code == 200
        models = resp.json()["data"]
        # Paid models should be excluded
        paid = [m for m in models if not m.get("is_free", True)]
        assert len(paid) == 0

    def test_filters_provider(self, client):
        resp = client.get("/v1/models?provider=groq")
        assert resp.status_code == 200
        models = resp.json()["data"]
        preamble_ids = {"LLM-Apipool"} | {f"g{i}" for i in range(1, 20)}
        for m in models:
            if m["id"] in preamble_ids:
                continue
            # Only check DB models (they have provider field)
            if m.get("provider") is not None:
                assert m.get("provider") == "groq", f"{m['id']} should be groq"

    def test_filters_tier(self, client):
        resp = client.get("/v1/models?tier=1")
        assert resp.status_code == 200
        models = resp.json()["data"]
        # Exclude LLM-Keypool and gateway models from assertion
        real_models = [
            m
            for m in models
            if m["id"] not in ("LLM-Apipool",) and not m["id"].startswith("g")
        ]
        for m in real_models:
            # Only check DB models (they have tier field)
            if m.get("tier") is not None:
                assert m.get("tier") == 1

    def test_search(self, client):
        resp = client.get("/v1/models?search=llama")
        assert resp.status_code == 200
        models = resp.json()["data"]
        ids = [m["id"] for m in models]
        assert any("llama" in mid.lower() for mid in ids)

    def test_enriched_fields(self, client):
        resp = client.get("/v1/models")
        assert resp.status_code == 200
        models = resp.json()["data"]
        groq_models = [m for m in models if m.get("provider") == "groq"]
        if groq_models:
            m = groq_models[0]
            assert "context_window" in m
            assert "supports_tools" in m
            assert "is_free" in m
            assert "tier" in m

    def test_preamble_always_present(self, client):
        resp = client.get("/v1/models")
        data = resp.json()["data"]
        ids = {m["id"] for m in data}
        assert "LLM-Apipool" in ids
        assert "g1" in ids
