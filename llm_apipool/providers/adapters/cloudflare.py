"""
Cloudflare Workers AI provider adapter.

Wraps the existing ``llm_apipool.providers.cloudflare`` module into a
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
class CloudflareProvider(BaseProvider):
    platform = "cloudflare"
    name = "Cloudflare Workers AI"
    default_model = "@cf/meta/llama-3.3-70b-instruct"
    base_url = "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run"

    async def chat_completion(
        self,
        api_key: str,
        messages: list[dict[str, Any]],
        model_id: str,
        options: CompletionOptions | None = None,
    ) -> ChatCompletionResponse:
        from ..cloudflare import complete

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
        from ..cloudflare import complete

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
                    "https://api.cloudflare.com/client/v4/user/tokens/verify",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                return resp.status_code == 200
        except Exception:  # noqa: BLE001
            return False

    async def fetch_models(self) -> list[dict[str, Any]]:
        try:
            import httpx

            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://api.cloudflare.com/client/v4/ai/models/search?per_page=50",
                )
                resp.raise_for_status()
                data = resp.json()
                return data.get("result", [])
        except Exception:  # noqa: BLE001
            return []

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

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
