"""Cohere native API client (not OpenAI-compatible)."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import httpx

from .base import CompletionResult
from .headers import collect_rl_headers

BASE_URL = "https://api.cohere.com/v2"
HTTP_429 = 429


def _make_chunk_id() -> str:
    return f"chatcmpl-{uuid.uuid4().hex[:12]}"


def _build_chunk(
    chunk_id: str,
    created: int,
    model: str,
    delta_content: str | None = None,
    delta_role: str | None = None,
    finish_reason: str | None = None,
    index: int = 0,
    **extra: Any,  # noqa: ANN401
) -> dict[str, Any]:
    """Build an OpenAI-format streaming chunk dict."""
    chunk: dict[str, Any] = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [],
    }
    if delta_content is not None or delta_role is not None or finish_reason is not None:
        delta: dict[str, Any] = {}
        if delta_role is not None:
            delta["role"] = delta_role
        if delta_content is not None:
            delta["content"] = delta_content
        chunk["choices"] = [
            {
                "index": index,
                "delta": delta,
                "finish_reason": finish_reason,
            },
        ]
    chunk.update(extra)
    return chunk


async def _real_stream(
    key_data: dict[str, Any],
    messages: list[dict[str, Any]],
    **kwargs: Any,  # noqa: ANN401
) -> AsyncGenerator[dict[str, Any], None]:
    """Real SSE streaming for Cohere v2 chat API.

    Calls the Cohere v2 ``/chat`` endpoint with ``stream: true`` and
    yields OpenAI-format streaming chunks from the SSE event stream.
    """
    chunk_id = _make_chunk_id()
    created = int(time.time())
    model = key_data["model"]
    base_url = key_data.get("base_url", BASE_URL)
    max_tokens = kwargs.get("max_tokens", 1024)
    temperature = kwargs.get("temperature", 0.7)

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": True,
    }
    headers = {
        "Authorization": f"Bearer {key_data['api_key']}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            async with client.stream(
                "POST",
                f"{base_url}/chat",
                json=payload,
                headers=headers,
            ) as resp:
                if resp.status_code == HTTP_429:
                    yield _build_chunk(
                        chunk_id,
                        created,
                        model,
                        x_error="429 rate limit",
                        x_was_429=True,
                    )
                    return
                resp.raise_for_status()

                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    try:
                        data = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue

                    event_type = data.get("event_type", "") or data.get("type", "")

                    if event_type == "text-generation":
                        text = data.get("text", "")
                        if text:
                            yield _build_chunk(
                                chunk_id,
                                created,
                                model,
                                delta_content=text,
                                delta_role="assistant",
                            )

                    elif event_type == "stream-end":
                        finish = data.get("finish_reason", "COMPLETE")
                        finish_map = {
                            "COMPLETE": "stop",
                            "MAX_TOKENS": "length",
                            "ERROR": "error",
                            "ERROR_TOXIC": "error",
                        }
                        mapped = finish_map.get(finish, "stop")
                        meta = data.get("response", {}).get("meta", {})
                        billed = meta.get("billed_units", {})
                        tokens = billed.get("input_tokens", 0) + billed.get(
                            "output_tokens", 0
                        )
                        extra: dict[str, Any] = {}
                        if tokens:
                            extra["x_tokens_used"] = tokens
                        yield _build_chunk(
                            chunk_id,
                            created,
                            model,
                            finish_reason=mapped,
                            **extra,
                        )
    except httpx.HTTPStatusError as e:
        yield _build_chunk(
            chunk_id,
            created,
            model,
            x_error=f"HTTP {e.response.status_code}",
        )
    except httpx.TimeoutException:
        yield _build_chunk(
            chunk_id,
            created,
            model,
            x_error="Request to Cohere timed out",
        )
    except httpx.RequestError as e:
        yield _build_chunk(
            chunk_id,
            created,
            model,
            x_error=f"Request error: {str(e)[:100]}",
        )
    except Exception as e:  # noqa: BLE001
        yield _build_chunk(
            chunk_id,
            created,
            model,
            x_error=f"Unexpected Cohere error: {type(e).__name__}: {str(e)[:150]}",
        )


async def complete(
    key_data: dict[str, Any],
    messages: list[dict[str, Any]],
    stream: bool = False,
    **kwargs: Any,  # noqa: ANN401
) -> CompletionResult | AsyncGenerator[dict[str, Any], None]:
    """Call Cohere API with the given key and messages.

    When *stream* is ``False`` (default), returns a :class:`CompletionResult`.
    When *stream* is ``True``, returns an async generator that yields dicts in
    OpenAI streaming chunk format.  This is a *simulated* stream — Cohere does
    not currently have native streaming support in this client, so the full
    response is collected first and yielded as a single chunk.
    """
    if stream:
        return _real_stream(key_data, messages, **kwargs)

    max_tokens = kwargs.get("max_tokens", 1024)
    temperature = kwargs.get("temperature", 0.7)

    payload = {
        "model": key_data["model"],
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    headers = {
        "Authorization": f"Bearer {key_data['api_key']}",
        "Content-Type": "application/json",
    }
    try:
        base_url = key_data.get("base_url", BASE_URL)
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(f"{base_url}/chat", json=payload, headers=headers)
        rl_headers = collect_rl_headers(resp.headers)
        if resp.status_code == HTTP_429:
            return CompletionResult(
                text="",
                tokens_used=0,
                was_429=True,
                error="429 rate limit",
                rate_limit_headers=rl_headers,
            )
        resp.raise_for_status()
        data = resp.json()
        text = data["message"]["content"][0]["text"]
        tokens = data.get("usage", {}).get("tokens", {})
        total = tokens.get("input_tokens", 0) + tokens.get("output_tokens", 0)
        return CompletionResult(
            text=text,
            tokens_used=total,
            was_429=False,
            rate_limit_headers=rl_headers,
        )
    except httpx.HTTPStatusError as e:
        return CompletionResult(
            text="",
            tokens_used=0,
            was_429=False,
            error=f"HTTP {e.response.status_code}",
        )
    except httpx.TimeoutException:
        return CompletionResult(
            text="", tokens_used=0, was_429=False, error="Request to Cohere timed out"
        )
    except httpx.RequestError as e:
        return CompletionResult(
            text="",
            tokens_used=0,
            was_429=False,
            error=f"Request error: {str(e)[:100]}",
        )
    except Exception as e:  # noqa: BLE001
        return CompletionResult(
            text="",
            tokens_used=0,
            was_429=False,
            error=f"Unexpected Cohere error: {type(e).__name__}: {str(e)[:150]}",
        )
