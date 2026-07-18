from __future__ import annotations

from llm_apipool.providers.registry import (
    get_provider,
    has_provider,
    list_providers,
    register,
)


def test_list_providers():
    providers = list_providers()
    assert isinstance(providers, list)
    assert len(providers) > 0


def test_has_known_providers():
    assert has_provider("google")
    assert has_provider("groq")
    assert has_provider("cerebras")
    assert has_provider("mistral")


def test_has_unknown_provider():
    assert not has_provider("nonexistent_provider_xyz")


def test_get_provider_known():
    provider = get_provider("google")
    assert provider is not None


def test_get_provider_unknown():
    provider = get_provider("nonexistent_provider_xyz")
    assert provider is None


def test_register_via_decorator():
    from llm_apipool.providers.base import BaseProvider
    from llm_apipool.providers.dispatch import CompletionResult

    @register
    class MockProvider(BaseProvider):
        platform = "mock_test_provider"
        name = "Mock Provider"

        async def chat_completion(self, key_data, messages, **kwargs):
            return CompletionResult(text="ok", tokens_used=5)

        async def stream_chat_completion(self, key_data, messages, **kwargs):
            # yield nothing (empty stream)
            return
            yield  # pragma: no cover

        def validate_key(self, api_key: str) -> bool:
            return True

    assert has_provider("mock_test_provider")
    provider = get_provider("mock_test_provider")
    assert provider is not None
