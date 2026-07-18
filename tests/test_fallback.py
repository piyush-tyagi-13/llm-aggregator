from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from llm_apipool.core.fallback import AllModelsExhaustedError, FallbackManager


@pytest.fixture
def mock_store():
    store = MagicMock()
    store.get_active_keys.return_value = [
        {
            "id": 1,
            "provider": "groq",
            "model": "llama-3.3-70b-versatile",
            "api_key": "gsk_test",
            "is_active": 1,
        },
        {
            "id": 2,
            "provider": "groq",
            "model": "llama-3.3-70b-versatile",
            "api_key": "gsk_test2",
            "is_active": 1,
        },
        {
            "id": 3,
            "provider": "cerebras",
            "model": "llama3.3-70b",
            "api_key": "csk_test",
            "is_active": 1,
        },
    ]
    return store


def test_fallback_manager_init(mock_store):
    fm = FallbackManager(mock_store)
    assert fm.store is mock_store
    assert fm.MAX_ATTEMPTS_SAME_KEY == 3
    assert fm.MAX_ATTEMPTS_SAME_PROVIDER == 3
    assert fm.MAX_ATTEMPTS_ALL_PROVIDERS == 3


def test_fallback_reset(mock_store):
    fm = FallbackManager(mock_store)
    fm._key_attempts[1] = 5
    fm._provider_attempts["groq"] = 5
    fm._model_attempts["test"] = 5
    fm._reset()
    assert fm._key_attempts == {}
    assert fm._provider_attempts == {}
    assert fm._model_attempts == {}


def test_fallback_should_skip_key(mock_store):
    fm = FallbackManager(mock_store)
    assert not fm._should_skip_key(999)
    fm._key_attempts[999] = 3
    assert fm._should_skip_key(999)


def test_fallback_should_skip_provider(mock_store):
    fm = FallbackManager(mock_store)
    assert not fm._should_skip_provider("groq")
    fm._provider_attempts["groq"] = 3
    assert fm._should_skip_provider("groq")


@pytest.mark.asyncio
async def test_fallback_no_candidates():
    store = MagicMock()
    store.get_enabled_models.return_value = []
    fm = FallbackManager(store)
    with pytest.raises(AllModelsExhaustedError):
        await fm.route_with_fallback({"messages": []})


@pytest.mark.asyncio
async def test_fallback_route_exhausted():
    store = MagicMock()
    store.get_enabled_models.return_value = [
        {"id": 1, "platform": "groq", "model_id": "llama-3.3-70b-versatile"},
    ]
    store.get_active_keys.return_value = []
    fm = FallbackManager(store)
    with pytest.raises(AllModelsExhaustedError):
        await fm.route_with_fallback({"messages": [{"role": "user", "content": "hi"}]})
