"""
Cohere provider adapter.

Wraps the existing ``llm_apipool.providers.cohere`` module into a
``BaseProvider`` subclass.
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
from ..registry import register


@register
class CohereProvider(BaseProvider):
    platform = "cohere"
    name = "Cohere"
    default_model = "command-r-plus"
    base_url = "https://api.cohere.com/v2"

    async def chat_completion(
        self,
        api_key: str,
        messages: list[dict[str, Any]],
        model_id: str,
        options: CompletionOptions | None = None,
    ) -> ChatCompletionResponse:
        from ..cohere import complete

        model = model_id or self.default_model
        key_data: dict[str, Any] = {
            "api_key": api_key,
            "base_url": self.base_url,
            "model": model,
            "provider": self.platform,
        }
        result = await complete(key_data, messages)
        if isinstance(result, AsyncGenerator):
            raise RuntimeError("Expected non-streaming result, got AsyncGenerator")
        return self._result_to_response(result, model)

    async def stream_chat_completion(
        self,
        api_key: str,
        messages: list[dict[str, Any]],
        model_id: str,
        options: CompletionOptions | None = None,
    ) -> AsyncGenerator[ChatCompletionChunk, None]:
        from ..cohere import complete

        model = model_id or self.default_model
        key_data: dict[str, Any] = {
            "api_key": api_key,
            "base_url": self.base_url,
            "model": model,
            "provider": self.platform,
        }
        _gen = await complete(key_data, messages, stream=True)
        if isinstance(_gen, CompletionResult):
            raise RuntimeError("Expected streaming result, got CompletionResult")
        async for chunk in _gen:
            yield self._dict_to_chunk(chunk, model)

    async def validate_key(self, api_key: str) -> bool:
        try:
            import httpx

            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://api.cohere.com/v1/models",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Accept": "application/json",
                    },
                )
                return resp.status_code == 200
        except Exception:
            return False

    async def fetch_models(self) -> list[dict[str, Any]]:
        try:
            import httpx

            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get("https://api.cohere.com/v1/models")
                resp.raise_for_status()
                data = resp.json()
                return data.get("models", [])
        except Exception:
            return []

    @staticmethod
    def _result_to_response(
        result: CompletionResult, model: str
    ) -> ChatCompletionResponse:
        return ChatCompletionResponse(
            id="",
            model=model,
            choices=[
                {"index": 0, "message": {"role": "assistant", "content": result.text}}
            ],
            usage={
                "prompt_tokens": 0,
                "completion_tokens": result.tokens_used,
                "total_tokens": result.tokens_used,
            },
        )

    @staticmethod
    def _dict_to_chunk(chunk: dict[str, Any], model: str) -> ChatCompletionChunk:
        return ChatCompletionChunk(
            id=chunk.get("id", ""),
            model=model,
            choices=chunk.get("choices", []),
        )
