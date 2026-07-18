"""OpenAI-compatible provider client."""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import AsyncGenerator, Generator
from threading import Lock
from typing import Any

import httpx
from openai import APIStatusError, APIConnectionError, AsyncOpenAI, RateLimitError

from .base import CompletionResult
from .headers import collect_rl_headers, extract_remaining_requests

# Import connection pool for PERFECT TTFT optimization
from llm_apipool.core.connection_pool import get_connection_pool

_NO_AUTH_SENTINEL = "sentinel-no-op"

# ── Connection pool — reuse clients to avoid TLS handshake per request ──
# LEGACY: Per-key caching is kept as fallback for sync compatibility
_client_cache: dict[str, AsyncOpenAI] = {}
_client_cache_lock = Lock()

# ── New: PERFECT async pool integration ──
_async_pool_client_ctx: dict[int, AsyncOpenAI] = {}
_async_ctx_lock = Lock()

# ── Timeout constants ──
_AGGRESSIVE_TIMEOUT = httpx.Timeout(30.0, connect=5.0, read=30.0)
_AGGRESSIVE_TIMEOUT_STREAM = httpx.Timeout(120.0, connect=5.0, read=120.0)


def _cache_key(base_url: str, api_key: str, no_auth: bool, stream: bool) -> str:
    return f"{base_url}|{api_key}|{no_auth}|{stream}"


# LEGACY: Keep sync version for backward compatibility
def _get_client(
    base_url: str, api_key: str, no_auth: bool = False, stream: bool = False
) -> AsyncOpenAI:
    """Return a cached ``AsyncOpenAI`` client, creating one if missing.

    LEGACY VERSION: Uses per-key caching. For PERFECT TTFT, use async version.
    """
    key = _cache_key(base_url, api_key, no_auth, stream)
    with _client_cache_lock:
        client = _client_cache.get(key)
        if client is None:
            client = _new_client(base_url, api_key, no_auth, stream)
            _client_cache[key] = client
        return client


async def _get_client_pooled(
    base_url: str,
    api_key: str,
    no_auth: bool = False,
    stream: bool = False,
) -> AsyncOpenAI:
    """PERFECT async version: Get client from provider-level connection pool.

    Returns a client backed by a pooled HTTP connection for true reuse across keys.
    The client MUST be returned via :func:`_return_client` after use.
    """
    pool = get_connection_pool()
    client = await pool.get_client(base_url, api_key, no_auth, stream)

    with _async_ctx_lock:
        _async_pool_client_ctx[id(client)] = client
    return client


async def _return_client(client: AsyncOpenAI, base_url: str) -> None:
    """Return client to the connection pool for reuse."""
    pool = get_connection_pool()

    with _async_ctx_lock:
        _async_pool_client_ctx.pop(id(client), None)

    await pool.return_client(base_url, client)


def _clear_client_cache() -> None:
    """Close and clear all cached clients (for testing / config changes)."""
    global _client_cache
    with _client_cache_lock:
        for client in _client_cache.values():
            # Close synchronously by using the client's internal cleanup
            # The httpx client is managed by AsyncOpenAI, we just clear the cache here
            pass
        _client_cache = {}


class _NoAuth(httpx.Auth):
    def auth_flow(
        self, request: httpx.Request
    ) -> Generator[httpx.Request, httpx.Response, None]:
        request.headers.pop("authorization", None)
        yield request


def _new_client(
    base_url: str, api_key: str, no_auth: bool = False, stream: bool = False
) -> AsyncOpenAI:
    """Create an AsyncOpenAI client with aggressive timeouts for low TTFT.

    Sets ``max_retries=0`` so retries are handled by dispatch's retry loop
    instead of the OpenAI SDK. Uses short connect (5s) and read timeouts
    so slow providers are abandoned quickly.
    """
    timeout = _AGGRESSIVE_TIMEOUT_STREAM if stream else _AGGRESSIVE_TIMEOUT
    if no_auth or not api_key or api_key == "empty-key-placeholder":
        http_client = httpx.AsyncClient(auth=_NoAuth(), timeout=timeout)
        return AsyncOpenAI(
            base_url=base_url,
            api_key=_NO_AUTH_SENTINEL,
            http_client=http_client,
            max_retries=0,
        )
    return AsyncOpenAI(
        base_url=base_url, api_key=api_key, timeout=timeout, max_retries=0
    )


# Backward compat alias — tests import this directly
_make_client = _new_client


_THINK_CLOSED_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)
_THINK_OPEN_RE = re.compile(r"<think>.*$", re.DOTALL)
_MASK_MIN_LEN = 8
_MASK_SHOW = 4


def _mask_key(api_key: str) -> str:
    """Mask API key for safe logging: show last 4 chars only."""
    if len(api_key) <= _MASK_MIN_LEN:
        return "****" + api_key[-_MASK_SHOW:] if len(api_key) > _MASK_SHOW else "****"
    return api_key[:_MASK_SHOW] + "****" + api_key[-_MASK_SHOW:]


def _strip_thinking(text: str) -> str:
    text = _THINK_CLOSED_RE.sub("", text)
    text = _THINK_OPEN_RE.sub("", text)
    return text.strip()


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


def _build_error_chunk(
    chunk_id: str,
    created: int,
    model: str,
    error: str,
    was_429: bool = False,
) -> dict[str, Any]:
    return _build_chunk(
        chunk_id,
        created,
        model,
        x_error=error,
        x_was_429=was_429,
    )


def _make_stream_gen(
    key_data: dict[str, Any],
    messages: list[dict[str, Any]],
    model: str,
    provider: str,
    api_key: str,
    base_url: str,
    strip_thinking: bool,
    no_auth: bool = False,
    **kwargs: Any,  # noqa: ANN401
) -> AsyncGenerator[dict[str, Any], None]:
    """Return an async generator that yields OpenAI-format streaming chunks."""
    chunk_id = _make_chunk_id()
    created = int(time.time())

    async def _gen() -> AsyncGenerator[dict[str, Any], None]:
        client = _get_client(
            base_url=base_url, api_key=api_key, no_auth=no_auth, stream=True
        )
        try:
            raw_stream = await client.chat.completions.with_raw_response.create(
                model=model,
                messages=messages,
                stream=True,  # type: ignore[call-overload]
                stream_options={"include_usage": True},
                **kwargs,
            )
            stream = raw_stream.parse()

            async for event in stream:
                choices_list: list[dict[str, Any]] = []
                if event.choices:
                    choice = event.choices[0]
                    delta = choice.delta
                    delta_out: dict[str, Any] = {}
                    if delta is not None:
                        if delta.role is not None:
                            delta_out["role"] = delta.role

                        has_real_content = delta.content is not None
                        if has_real_content:
                            delta_out["content"] = delta.content

                        # reasoning_content — Z.ai/OpenCode Zen/Cloudflare
                        # reasoning         — Ollama
                        rc = getattr(delta, "reasoning_content", None)
                        if rc is not None:
                            delta_out["reasoning_content"] = rc
                        r = getattr(delta, "reasoning", None)
                        if r is not None:
                            delta_out["reasoning"] = r

                        # FreeLLMAPI's normalizeChoices only folds reasoning into content
                        # on the non-streaming path. For streaming, we forward
                        # reasoning_content as its own field and NEVER touch
                        # content — the client accumulates it correctly.

                        # Tool-call delta chunks — forward as-is, fill missing index
                        dtc = getattr(delta, "tool_calls", None)
                        if dtc is not None:
                            tc_list: list[dict[str, Any]] = []
                            for tc in dtc:
                                tc_dict: dict[str, Any] = {"index": tc.index}
                                # Always include id — generate one if upstream didn't provide it
                                if tc.id and isinstance(tc.id, str) and len(tc.id) > 0:
                                    tc_dict["id"] = str(tc.id)
                                else:
                                    tc_dict["id"] = (
                                        f"chatcmpl-tool-{uuid.uuid4().hex[:10]}"
                                    )
                                # Always include type and function per OpenAI schema
                                tc_dict["type"] = (
                                    str(tc.type)
                                    if tc.type and isinstance(tc.type, str)
                                    else "function"
                                )
                                func_dict: dict[str, Any] = {}
                                if tc.function:
                                    if tc.function.name and isinstance(
                                        tc.function.name, str
                                    ):
                                        func_dict["name"] = tc.function.name
                                    if tc.function.arguments and isinstance(
                                        tc.function.arguments, str
                                    ):
                                        func_dict["arguments"] = tc.function.arguments
                                # Always include function field with at least empty name/arguments
                                tc_dict["function"] = (
                                    func_dict
                                    if func_dict
                                    else {"name": "", "arguments": ""}
                                )
                                tc_list.append(tc_dict)
                            if tc_list:
                                delta_out["tool_calls"] = tc_list
                    finish = str(choice.finish_reason) if choice.finish_reason else None
                    choices_list = [
                        {
                            "index": choice.index,
                            "delta": delta_out,
                            "finish_reason": finish,
                        },
                    ]

                extra: dict[str, Any] = {}
                if event.usage:
                    extra["x_tokens_used"] = event.usage.total_tokens or 0

                yield {
                    "id": chunk_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": choices_list,
                    **extra,
                }

        except RateLimitError as e:
            yield _build_error_chunk(
                chunk_id,
                created,
                model,
                error=f"Rate limited (429): {str(e)[:150]}",
                was_429=True,
            )
        except APIStatusError as e:
            yield _build_error_chunk(
                chunk_id,
                created,
                model,
                error=f"HTTP {e.status_code} from provider {provider}: {str(e)[:160]}",
            )
        except httpx.TimeoutException as e:
            yield _build_error_chunk(
                chunk_id,
                created,
                model,
                error=f"Request to {_mask_key(base_url)} timed out: {str(e)[:100]}",
            )
        except httpx.NetworkError as e:
            yield _build_error_chunk(
                chunk_id,
                created,
                model,
                error=f"Network error connecting to {_mask_key(base_url)}: {str(e)[:100]}",
            )
        except httpx.HTTPStatusError as e:
            yield _build_error_chunk(
                chunk_id,
                created,
                model,
                error=f"HTTP {e.response.status_code} from provider {provider}: {str(e)[:160]}",
            )
        except httpx.RequestError as e:
            yield _build_error_chunk(
                chunk_id,
                created,
                model,
                error=f"Request error: {str(e)[:100]}",
            )
        except APIConnectionError as e:
            yield _build_error_chunk(
                chunk_id,
                created,
                model,
                error=f"Connection error to {_mask_key(base_url)}: {str(e)[:150]}",
            )
        except Exception as e:  # noqa: BLE001
            yield _build_error_chunk(
                chunk_id,
                created,
                model,
                error=f"Unexpected error: {type(e).__name__}: {str(e)[:150]}",
            )

    return _gen()


async def complete(
    key_data: dict[str, Any],
    messages: list[dict[str, Any]],
    stream: bool = False,
    **kwargs: Any,  # noqa: ANN401
) -> CompletionResult | AsyncGenerator[dict[str, Any], None]:
    """Call an OpenAI-compatible provider with the given key and messages.

    When *stream* is ``False`` (default), returns a :class:`CompletionResult`.
    When *stream* is ``True``, returns an async generator that yields dicts in
    OpenAI streaming chunk format.
    """
    strip_thinking = kwargs.pop("strip_thinking", True)
    model = kwargs.pop("model", None) or key_data["model"]

    if stream:
        return _make_stream_gen(
            key_data,
            messages,
            model,
            provider=key_data.get("provider", ""),
            api_key=key_data["api_key"] or "empty-key-placeholder",
            base_url=key_data["base_url"],
            strip_thinking=strip_thinking,
            no_auth=key_data.get("no_auth", False),
            **kwargs,
        )

    provider = key_data.get("provider", "")
    api_key = key_data["api_key"] or "empty-key-placeholder"
    base_url = key_data["base_url"]
    no_auth = key_data.get("no_auth", False)

    client = await _get_client_pooled(
        base_url=base_url, api_key=api_key, no_auth=no_auth
    )
    try:
        raw = await client.chat.completions.with_raw_response.create(
            model=model,
            messages=messages,  # type: ignore[arg-type]
            **kwargs,
        )
        resp = raw.parse()
        rl_headers = collect_rl_headers(raw.headers)
        remaining = extract_remaining_requests(provider, rl_headers)
        msg = resp.choices[0].message
        text = msg.content or ""
        reasoning_content: str | None = None
        if hasattr(msg, "reasoning_content") and msg.reasoning_content:
            reasoning_content = msg.reasoning_content
        if not text and reasoning_content:
            text = reasoning_content
        if strip_thinking:
            text = _strip_thinking(text)

        tool_calls_raw = getattr(msg, "tool_calls", None)
        tool_calls_processed = None
        if tool_calls_raw:
            tool_calls_processed = []
            for tc in tool_calls_raw:
                tc_id = (
                    tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
                )
                if tc_id and isinstance(tc_id, str) and len(tc_id) > 0:
                    final_id = tc_id
                else:
                    final_id = f"chatcmpl-tool-{uuid.uuid4().hex[:10]}"
                tc_dict: dict[str, Any] = {
                    "id": str(final_id),
                    "type": "function",
                    "function": {"name": "", "arguments": ""},
                }
                tc_func = (
                    tc.get("function")
                    if isinstance(tc, dict)
                    else getattr(tc, "function", None)
                )
                if tc_func:
                    func_name = (
                        tc_func.get("name")
                        if isinstance(tc_func, dict)
                        else getattr(tc_func, "name", None)
                    )
                    func_args = (
                        tc_func.get("arguments")
                        if isinstance(tc_func, dict)
                        else getattr(tc_func, "arguments", None)
                    )
                    if func_name:
                        tc_dict["function"]["name"] = str(func_name)
                    if func_args:
                        tc_dict["function"]["arguments"] = str(func_args)
                tool_calls_processed.append(tc_dict)

        return CompletionResult(
            text=text,
            tokens_used=resp.usage.total_tokens if resp.usage else 0,
            was_429=False,
            remaining_requests=remaining,
            rate_limit_headers=rl_headers,
            reasoning_content=reasoning_content,
            tool_calls=tool_calls_processed,
        )
    except RateLimitError as e:
        rl_headers = {}
        if hasattr(e, "response") and e.response is not None:
            rl_headers = collect_rl_headers(e.response.headers)
        return CompletionResult(
            text="",
            tokens_used=0,
            was_429=True,
            error=f"Rate limited (429): {str(e)[:150]}",
            rate_limit_headers=rl_headers,
        )
    except APIStatusError as e:
        err = f"HTTP {e.status_code} from provider {key_data.get('provider', '?')}: {str(e)[:160]}"
        return CompletionResult(text="", tokens_used=0, was_429=False, error=err)
    except httpx.TimeoutException as e:
        err = f"Request to {_mask_key(key_data.get('base_url', ''))} timed out: {str(e)[:100]}"
        return CompletionResult(text="", tokens_used=0, was_429=False, error=err)
    except httpx.NetworkError as e:
        err = f"Network error connecting to {_mask_key(key_data.get('base_url', ''))}: {str(e)[:100]}"
        return CompletionResult(text="", tokens_used=0, was_429=False, error=err)
    except httpx.HTTPStatusError as e:
        err = f"HTTP {e.response.status_code} from provider {key_data.get('provider', '?')}: {str(e)[:160]}"
        return CompletionResult(text="", tokens_used=0, was_429=False, error=err)
    except httpx.RequestError as e:
        err = f"Request error: {str(e)[:100]}"
        return CompletionResult(text="", tokens_used=0, was_429=False, error=err)
    except APIConnectionError as e:
        err = f"Connection error to {_mask_key(key_data.get('base_url', ''))}: {str(e)[:150]}"
        return CompletionResult(text="", tokens_used=0, was_429=False, error=err)
    except Exception as e:  # noqa: BLE001
        err = f"Unexpected error: {type(e).__name__}: {str(e)[:150]}"
        return CompletionResult(text="", tokens_used=0, was_429=False, error=err)
    finally:
        await _return_client(client, base_url)


__all__ = ["complete", "CompletionResult"]
