"""Shared base class for OpenAI-compatible provider adapters.

Reduces boilerplate: each concrete adapter only needs to set ``platform``,
``name``, ``default_model``, and ``base_url``.
"""

from __future__ import annotations

from typing import Any, AsyncGenerator

from ..base import (
    BaseProvider,
    CompletionOptions,
    ChatCompletionResponse,
    ChatCompletionChunk,
    CompletionResult,
)


class OpenAICompatProvider(BaseProvider):
    """Base for providers that speak the OpenAI chat-completions wire format.

    Concrete subclasses set class-level attributes; the methods delegate to
    ``llm_apipool.providers.openai_compat`` at runtime.
    """

    platform: str = ""
    name: str = ""
    default_model: str = ""
    base_url: str = ""
    openai_compatible: bool = True

    # Provider-specific limits
    rpm_limit: int | None = None
    rpd_limit: int | None = None
    tpm_limit: int | None = None
    tpd_limit: int | None = None

    async def chat_completion(
        self,
        api_key: str,
        messages: list[dict[str, Any]],
        model_id: str,
        options: CompletionOptions | None = None,
    ) -> ChatCompletionResponse:
        from ..openai_compat import complete as _openai_complete

        model = model_id or self.default_model
        key_data: dict[str, Any] = {
            "api_key": api_key,
            "base_url": self.base_url,
            "model": model,
            "provider": self.platform,
        }
        result = await _openai_complete(key_data, messages, stream=False)
        if isinstance(result, AsyncGenerator):
            raise RuntimeError("Expected non-streaming result, got AsyncGenerator")
        return self._to_response(result, model)

    async def stream_chat_completion(
        self,
        api_key: str,
        messages: list[dict[str, Any]],
        model_id: str,
        options: CompletionOptions | None = None,
    ) -> AsyncGenerator[ChatCompletionChunk, None]:
        from ..openai_compat import complete as _openai_complete

        model = model_id or self.default_model
        key_data: dict[str, Any] = {
            "api_key": api_key,
            "base_url": self.base_url,
            "model": model,
            "provider": self.platform,
        }
        gen = await _openai_complete(key_data, messages, stream=True)
        if isinstance(gen, CompletionResult):
            raise RuntimeError("Expected streaming result, got CompletionResult")
        async for chunk in gen:
            yield self._to_chunk(chunk, model)

    async def validate_key(self, api_key: str) -> bool:
        """Check the key by listing models from the provider."""
        try:
            import httpx

            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self.base_url.rstrip('/')}/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                return resp.status_code == 200
        except Exception:  # noqa: BLE001
            return False

    async def fetch_models(self) -> list[dict[str, Any]]:
        """Fetch available models from the provider's /v1/models endpoint."""
        try:
            import httpx

            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self.base_url.rstrip('/')}/v1/models")
                resp.raise_for_status()
                data = resp.json()
                return data.get("data", [])
        except Exception:  # noqa: BLE001
            return []

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _to_response(result: Any, model: str) -> ChatCompletionResponse:
        if isinstance(result, ChatCompletionResponse):
            if not result.model:
                result.model = model
            return result
        if isinstance(result, dict):
            return ChatCompletionResponse(
                id=result.get("id", ""),
                model=result.get("model", model),
                choices=result.get("choices", []),
                usage=result.get("usage"),
            )
        return ChatCompletionResponse(id="", model=model)

    @staticmethod
    def _to_chunk(chunk: Any, model: str) -> ChatCompletionChunk:
        if isinstance(chunk, ChatCompletionChunk):
            if not chunk.model:
                chunk.model = model
            return chunk
        if isinstance(chunk, dict):
            return ChatCompletionChunk(
                id=chunk.get("id", ""),
                model=chunk.get("model", model),
                choices=chunk.get("choices", []),
            )
        return ChatCompletionChunk(id="", model=model)
