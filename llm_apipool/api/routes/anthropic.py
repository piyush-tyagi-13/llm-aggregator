"""Anthropic-compatible /v1/messages endpoint.

Translates Anthropic wire format ↔ internal (OpenAI-shaped) ChatMessage
format, routing through the same dispatch/rotator machinery the OpenAI
chat route uses.

Supports:
- Non-streaming ``POST /v1/messages``
- Streaming ``POST /v1/messages`` (SSE event sequence)
- ``POST /v1/messages/count_tokens``
- Content-negotiated ``GET /v1/models`` (returns Anthropic shape when
  ``anthropic-version`` header is present)
"""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

from llm_apipool.api.errors import (
    RATE_LIMIT_ERROR,
    ROUTING_ERROR,
    SERVER_ERROR,
    error_response,
)
from llm_apipool.core.handoff import (
    get_handoff_mode,
    maybe_inject,
    record_incoming,
    record_successful,
)

_MAX_RETRIES = 20
_DEFAULT_MAX_TOKENS = 1024
_IMAGE_TOKEN_ESTIMATE = 1000
_MODEL_CREATED_AT = "2026-01-01T00:00:00Z"

# ── Anthropic content-block helpers ──────────────────────────────────────────

_ANTHROPIC_STOP_REASON_MAP: dict[str, str] = {
    "stop": "end_turn",
    "length": "max_tokens",
    "content_filter": "end_turn",
    "tool_calls": "tool_use",
}


def _new_message_id() -> str:
    return f"msg_{uuid.uuid4().hex[:24]}"


def _flatten_system(system: Any) -> str:
    if not system:
        return ""
    if isinstance(system, str):
        return system
    if isinstance(system, list):
        parts = []
        for block in system:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "\n".join(parts)
    return str(system)


def _flatten_tool_result(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "\n".join(parts)
    return json.dumps(content)


def _image_block_to_url(block: dict[str, Any]) -> str | None:
    src = block.get("source")
    if not isinstance(src, dict):
        return None
    if src.get("type") == "base64":
        media_type = src.get("media_type", "")
        data = src.get("data", "")
        if media_type and data:
            return f"data:{media_type};base64,{data}"
    if src.get("type") == "url":
        url = src.get("url")
        if isinstance(url, str):
            return url
    return None


def _convert_tool_choice(choice: Any) -> str | dict[str, Any] | None:
    if not isinstance(choice, dict):
        return None
    tc_type = choice.get("type")
    if tc_type == "auto":
        return "auto"
    if tc_type == "none":
        return "none"
    if tc_type == "any":
        return "required"
    if tc_type == "tool":
        name = choice.get("name")
        if name:
            return {"type": "function", "function": {"name": name}}
        return "required"
    return None


def _map_stop_reason(finish_reason: str | None, had_tool_calls: bool) -> str:
    if had_tool_calls:
        return "tool_use"
    if finish_reason == "length":
        return "max_tokens"
    return _ANTHROPIC_STOP_REASON_MAP.get(finish_reason or "stop", "end_turn")


def _parse_tool_input(raw: str) -> dict[str, Any]:
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}


# ── Request / Response models ────────────────────────────────────────────────


class _AnthropicContentBlock(BaseModel):
    type: str
    text: str | None = None
    id: str | None = None
    name: str | None = None
    input: dict[str, Any] | None = None
    source: dict[str, Any] | None = None
    tool_use_id: str | None = None
    content: Any = None


class _AnthropicMessage(BaseModel):
    model_config = {"extra": "ignore"}
    role: str
    content: str | list[dict[str, Any]]


class _AnthropicToolSchema(BaseModel):
    model_config = {"extra": "ignore"}
    name: str
    description: str | None = None
    input_schema: dict[str, Any] | None = None


class _AnthropicToolChoice(BaseModel):
    model_config = {"extra": "ignore"}
    type: str = "auto"
    name: str | None = None


class _AnthropicRequest(BaseModel):
    model_config = {"extra": "ignore"}
    model: str | None = None
    max_tokens: int | None = None
    messages: list[dict[str, Any]]
    system: str | list[dict[str, Any]] | None = None
    temperature: float | None = None
    top_p: float | None = None
    stream: bool | None = False
    stop_sequences: list[str] | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: dict[str, Any] | None = None


# ── Request translation: Anthropic → internal OpenAI-shaped ──────────────────


def _convert_request(
    body: _AnthropicRequest,
) -> tuple[
    list[dict[str, Any]], list[dict[str, Any]] | None, str | dict[str, Any] | None, bool
]:
    """Convert Anthropic request to internal format.

    Returns ``(messages, tools, tool_choice, has_image)``.
    """
    messages: list[dict[str, Any]] = []
    has_image = False

    # System prompt
    system = _flatten_system(body.system)
    if system:
        messages.append({"role": "system", "content": system})

    for msg in body.messages:
        role = msg.get("role", "user")

        # System role inlined in messages array
        if role == "system":
            if isinstance(msg.get("content"), str):
                messages.append({"role": "system", "content": msg["content"]})
            elif isinstance(msg.get("content"), list):
                text = _flatten_tool_result(msg["content"])
                if text:
                    messages.append({"role": "system", "content": text})
            continue

        # String content
        if isinstance(msg.get("content"), str):
            messages.append({"role": role, "content": msg["content"]})
            continue

        # Content blocks
        text_parts: list[str] = []
        image_blocks: list[dict[str, Any]] = []
        tool_calls: list[dict[str, Any]] = []
        tool_results: list[dict[str, Any]] = []
        content_blocks = msg.get("content", [])

        if isinstance(content_blocks, list):
            for block in content_blocks:
                if not isinstance(block, dict):
                    continue
                block_type = block.get("type")
                if block_type == "text":
                    text = block.get("text", "")
                    if text:
                        text_parts.append(text)
                elif block_type == "image":
                    url = _image_block_to_url(block)
                    if url:
                        image_blocks.append(
                            {"type": "image_url", "image_url": {"url": url}}
                        )
                        has_image = True
                elif block_type == "tool_use":
                    tc_id = block.get("id")
                    # Generate ID if missing, None, or not a valid string
                    if tc_id and isinstance(tc_id, str) and len(tc_id) > 0:
                        valid_tc_id = tc_id
                    else:
                        valid_tc_id = f"call_{uuid.uuid4().hex[:10]}"
                    tc_name = block.get("name", "")
                    tc_input = block.get("input", {})
                    tool_calls.append(
                        {
                            "id": valid_tc_id,
                            "type": "function",
                            "function": {
                                "name": str(tc_name),
                                "arguments": json.dumps(tc_input),
                            },
                        }
                    )
                elif block_type == "tool_result":
                    tool_results.append(
                        {
                            "role": "tool",
                            "tool_call_id": str(block.get("tool_use_id", "")),
                            "content": _flatten_tool_result(block.get("content")),
                        }
                    )

        text = "\n".join(text_parts)

        if role == "assistant":
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": text if text else None,
            }
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            messages.append(assistant_msg)
        else:
            # User turn — tool results are interleaved in Anthropic format
            messages.extend(tool_results)
            if image_blocks:
                blocks: list[dict[str, Any]] = []
                if text:
                    blocks.append({"type": "text", "text": text})
                blocks.extend(image_blocks)
                messages.append({"role": "user", "content": blocks})
            elif text:
                messages.append({"role": "user", "content": text})

    # Tools
    tools: list[dict[str, Any]] | None = None
    if body.tools:
        tools = []
        for t in body.tools:
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": t.get("name", ""),
                        "description": t.get("description", ""),
                        "parameters": t.get("input_schema")
                        or {"type": "object", "properties": {}},
                    },
                }
            )

    tool_choice = _convert_tool_choice(body.tool_choice)

    return messages, tools, tool_choice, has_image


# ── Response translation: internal → Anthropic ───────────────────────────────


def _to_anthropic_content(
    text: str, tool_calls: list[dict[str, Any]] | None
) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    if text:
        blocks.append({"type": "text", "text": text})
    for tc in tool_calls or []:
        tc_id = tc.get("id")
        # Generate ID if missing, None, or not a valid string
        if tc_id and isinstance(tc_id, str) and len(tc_id) > 0:
            valid_tc_id = tc_id
        else:
            valid_tc_id = f"toolu_{uuid.uuid4().hex[:16]}"
        blocks.append(
            {
                "type": "tool_use",
                "id": valid_tc_id,
                "name": tc.get("function", {}).get("name", ""),
                "input": _parse_tool_input(
                    tc.get("function", {}).get("arguments", "{}")
                ),
            }
        )
    return blocks


def _estimate_tokens(content: str) -> int:
    """Heuristic token estimate (matches FreeLLMAPI's len/4)."""
    return max(1, math.ceil(len(content) / 4))


def _estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += _estimate_tokens(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and "text" in block:
                    total += _estimate_tokens(block["text"])
    return total


# ── Router ───────────────────────────────────────────────────────────────────


def _list_models(configs: dict[str, Any], store: Any) -> list[dict[str, Any]]:
    """Build a flat model listing from the DB or provider configs."""
    from llm_apipool.core.model_db import get_models

    data: list[dict[str, Any]] = []
    try:
        rows = get_models(store._conn())
        if rows:
            for r in rows:
                data.append(
                    {
                        "id": r["model_id"],
                        "name": r.get("display_name") or r["model_id"],
                        "provider": r["platform"],
                        "available": bool(r.get("enabled", True)),
                    }
                )
            return data
    except Exception:
        pass

    # Fallback: use only default_model per provider (no hardcoded lists)
    for provider_name, cfg in configs.items():
        default = cfg.get("default_model")
        if default:
            data.append(
                {
                    "id": default,
                    "name": default,
                    "provider": provider_name,
                    "available": True,
                }
            )
    return data


def _create_anthropic_router(
    store: Any, rotator: Any, configs: dict[str, Any], default_capabilities: list[str]
) -> APIRouter:
    from llm_apipool.providers.dispatch import complete as dispatch_complete
    from llm_apipool.providers.dispatch import _estimate_tokens as _dispatch_estimate

    router = APIRouter()

    @router.post("/v1/messages")
    async def messages_endpoint(
        req: _AnthropicRequest,
        x_subscriber_id: Annotated[str | None, Header()] = None,
        x_session_id: Annotated[str | None, Header()] = None,
    ) -> Any:

        subscriber = x_subscriber_id or "anthropic"

        # Resolve model (Claude families → auto)
        requested_model = req.model or "auto"

        max_tokens = (
            req.max_tokens
            if req.max_tokens and req.max_tokens > 0
            else _DEFAULT_MAX_TOKENS
        )

        # Convert request
        messages, tools, tool_choice, has_image = _convert_request(req)

        # Context handoff
        session_key = _compute_session_key(messages, x_session_id)
        if session_key:
            record_incoming(session_key, messages)
        messages = _setup_handoff(session_key, messages, requested_model)

        estimated_input_tokens = _estimate_messages_tokens(messages)
        # Build dispatch kwargs
        kwargs: dict[str, Any] = {
            "max_tokens": max_tokens,
        }
        if req.temperature is not None:
            kwargs["temperature"] = req.temperature
        if req.top_p is not None:
            kwargs["top_p"] = req.top_p
        if tools:
            kwargs["tools"] = tools
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice

        # Determine capabilities
        caps = list(default_capabilities)
        if has_image and "vision" not in caps:
            caps.append("vision")

        if req.stream:
            return await _handle_stream(
                store,
                rotator,
                caps,
                messages,
                kwargs,
                subscriber,
                requested_model,
                estimated_input_tokens,
                session_key,
            )

        # Non-streaming path
        last_error: str | None = None
        last_key_data: dict[str, Any] | None = None
        last_result = None

        for _attempt in range(_MAX_RETRIES):
            try:
                result, key_data = await dispatch_complete(
                    rotator,
                    capabilities=caps,
                    messages=messages,
                    subscriber_id=subscriber,
                    **kwargs,
                )
                if result.text or (result.error and "rate" in result.error.lower()):
                    last_result = result
                    last_key_data = key_data
                    break
                last_error = result.error
            except Exception as e:
                last_error = str(e)

        if not last_result or (not last_result.text and last_result.error):
            msg = last_error or "All available keys exhausted"
            if "rate" in msg.lower():
                return error_response(429, msg, RATE_LIMIT_ERROR)
            return error_response(503, msg, ROUTING_ERROR)

        model_out = (last_key_data or {}).get("model") or "auto"
        provider = (last_key_data or {}).get("provider", "unknown")
        if session_key and last_key_data:
            record_successful(session_key, last_key_data.get("model", ""))

        resp_msg: dict[str, Any] = {"role": "assistant", "content": last_result.text}
        if getattr(last_result, "reasoning_content", None):
            resp_msg["reasoning_content"] = last_result.reasoning_content

        prompt_tokens = _dispatch_estimate(messages)
        completion_tokens = last_result.tokens_used

        anthropic_content = _to_anthropic_content(last_result.text, None)

        return JSONResponse(
            content={
                "id": _new_message_id(),
                "type": "message",
                "role": "assistant",
                "model": requested_model,
                "content": anthropic_content,
                "stop_reason": _map_stop_reason("stop", False),
                "stop_sequence": None,
                "usage": {
                    "input_tokens": prompt_tokens,
                    "output_tokens": completion_tokens,
                },
            },
            headers={
                "X-Routed-Via": f"{provider}/{model_out}",
            },
        )

    @router.post("/v1/messages/count_tokens")
    async def count_tokens(req: _AnthropicRequest) -> dict[str, Any]:
        messages, _tools, _tool_choice, _has_image = _convert_request(req)
        return {"input_tokens": _estimate_messages_tokens(messages)}

    return router


def _compute_session_key(
    messages: list[dict[str, Any]], x_session_id: str | None
) -> str:
    if x_session_id:
        return x_session_id
    for m in messages:
        if m.get("role") == "user":
            content = m.get("content", "")
            if isinstance(content, list):
                text = "".join(
                    p.get("text", "") for p in content if isinstance(p, dict)
                )
            else:
                text = str(content or "")
            return hashlib.sha1(text.encode()).hexdigest()[:16]
    return ""


def _setup_handoff(
    session_key: str, messages: list[dict[str, Any]], model_key: str
) -> list[dict[str, Any]]:
    if not session_key or get_handoff_mode() == "off":
        return messages
    msgs, injected, _ = maybe_inject(session_key, messages, model_key)
    return msgs


async def _handle_stream(
    store: Any,
    rotator: Any,
    caps: list[str],
    messages: list[dict[str, Any]],
    kwargs: dict[str, Any],
    subscriber: str,
    requested_model: str,
    estimated_input_tokens: int,
    session_key: str = "",
) -> StreamingResponse:
    """Handle streaming Anthropic response via SSE events."""
    from llm_apipool.providers.dispatch import complete as dispatch_complete

    gen, key_data = await dispatch_complete(
        rotator,
        capabilities=caps,
        messages=messages,
        subscriber_id=subscriber,
        stream=True,
        **kwargs,
    )

    if key_data is None:
        return error_response(503, "All available keys exhausted", ROUTING_ERROR)

    provider = key_data.get("provider", "unknown")
    model_out = key_data.get("model", "unknown")

    # Peek first chunk
    first_chunk = None
    rest_chunks: list[dict[str, Any]] = []

    async for chunk in gen:
        if first_chunk is None:
            first_chunk = chunk
        else:
            rest_chunks.append(chunk)
        break

    if first_chunk is None:
        return error_response(502, "Provider returned empty stream", SERVER_ERROR)

    x_err = first_chunk.get("x_error")
    if x_err:
        return error_response(502, x_err, SERVER_ERROR)

    async def _consume_gen(
        gen: AsyncGenerator[dict[str, Any], None],
        first_chunk: dict[str, Any],
        rest_chunks: list[dict[str, Any]],
    ) -> AsyncGenerator[str, None]:
        msg_id_local = _new_message_id()
        text_block_index = -1
        text_block_open = False
        next_index = 0
        upstream_finish: str | None = None
        tool_acc: dict[int, dict[str, Any]] = {}
        output_chars = 0

        # Send message_start
        yield f"event: message_start\ndata: {json.dumps({'type': 'message_start', 'message': {'id': msg_id_local, 'type': 'message', 'role': 'assistant', 'model': requested_model, 'content': [], 'stop_reason': None, 'stop_sequence': None, 'usage': {'input_tokens': estimated_input_tokens, 'output_tokens': 0}}})}\n\n"

        def _emit_text(text: str) -> list[str]:
            nonlocal text_block_index, text_block_open, next_index, output_chars
            events: list[str] = []
            if not text:
                return events
            if not text_block_open:
                text_block_index = next_index
                next_index += 1
                events.append(
                    f"event: content_block_start\ndata: {json.dumps({'type': 'content_block_start', 'index': text_block_index, 'content_block': {'type': 'text', 'text': ''}})}\n\n"
                )
                text_block_open = True
            events.append(
                f"event: content_block_delta\ndata: {json.dumps({'type': 'content_block_delta', 'index': text_block_index, 'delta': {'type': 'text_delta', 'text': text}})}\n\n"
            )
            output_chars += len(text)
            return events

        def _accumulate_tool_calls(delta_tc: list[dict[str, Any]]) -> None:
            for tc in delta_tc:
                idx = tc.get("index", 0)
                if idx not in tool_acc:
                    tool_acc[idx] = {"id": None, "name": "", "args": ""}
                acc = tool_acc[idx]
                tc_id_val = tc.get("id")
                if (
                    tc_id_val
                    and isinstance(tc_id_val, str)
                    and len(tc_id_val) > 0
                    and not acc["id"]
                ):
                    acc["id"] = tc_id_val
                func = tc.get("function", {})
                if func.get("name"):
                    acc["name"] += func["name"]
                if func.get("arguments"):
                    acc["args"] += func["arguments"]

        def _emit_tool_calls() -> list[str]:
            nonlocal next_index, output_chars
            events: list[str] = []
            for idx in sorted(tool_acc.keys()):
                acc = tool_acc[idx]
                acc_id = acc.get("id")
                # Generate ID if missing, None, or not a valid string
                if acc_id and isinstance(acc_id, str) and len(acc_id) > 0:
                    call_id = acc_id
                else:
                    call_id = f"toolu_{uuid.uuid4().hex[:16]}"
                tool_block_index = next_index
                next_index += 1
                events.append(
                    f"event: content_block_start\ndata: {json.dumps({'type': 'content_block_start', 'index': tool_block_index, 'content_block': {'type': 'tool_use', 'id': call_id, 'name': acc['name'], 'input': {}}})}\n\n"
                )
                events.append(
                    f"event: content_block_delta\ndata: {json.dumps({'type': 'content_block_delta', 'index': tool_block_index, 'delta': {'type': 'input_json_delta', 'partial_json': acc['args'] or '{}'}})}\n\n"
                )
                events.append(
                    f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': tool_block_index})}\n\n"
                )
                output_chars += len(acc.get("args", ""))
            return events

        # Process all chunks
        all_items = [first_chunk] + rest_chunks
        seen_chunks = 0
        for item in all_items:
            seen_chunks += 1
            events = _process_stream_chunk(
                item, tool_acc, upstream_finish, _emit_text, _accumulate_tool_calls
            )
            for ev in events:
                if ev.startswith("error:"):
                    yield ev[6:]
                    yield "event: message_stop\ndata: {}\n\n"
                    return
                if ev.startswith("finish:"):
                    upstream_finish = ev[7:]
                    continue
                yield ev

        async for chunk in gen:
            seen_chunks += 1
            events = _process_stream_chunk(
                chunk, tool_acc, upstream_finish, _emit_text, _accumulate_tool_calls
            )
            for ev in events:
                if ev.startswith("error:"):
                    yield ev[6:]
                    yield "event: message_stop\ndata: {}\n\n"
                    return
                if ev.startswith("finish:"):
                    upstream_finish = ev[7:]
                    continue
                yield ev

        # Close text block
        if text_block_open:
            yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': text_block_index})}\n\n"

        # Emit tool calls
        for ev in _emit_tool_calls():
            yield ev

        # Finalize
        stop_reason = _map_stop_reason(upstream_finish, bool(tool_acc))
        output_tokens = max(1, math.ceil(output_chars / 4))
        yield f"event: message_delta\ndata: {json.dumps({'type': 'message_delta', 'delta': {'stop_reason': stop_reason, 'stop_sequence': None}, 'usage': {'output_tokens': output_tokens}})}\n\n"
        yield "event: message_stop\ndata: {}\n\n"
        if session_key:
            record_successful(session_key, model_out)

    return StreamingResponse(
        _consume_gen(gen, first_chunk, rest_chunks),
        media_type="text/event-stream",
        headers={
            "X-Routed-Via": f"{provider}/{model_out}",
        },
    )


def _process_stream_chunk(
    chunk: dict[str, Any],
    tool_acc: dict[int, dict[str, Any]],
    upstream_finish: str | None,
    emit_text: Any,
    accumulate_tool_calls: Any,
) -> list[str]:
    """Process a single streaming chunk and return list of event strings.

    Special prefixes in returned strings:
    - ``error:...`` — mid-stream error
    - ``finish:...`` — finish reason update
    """
    # Check for mid-stream errors
    x_err_mid = chunk.get("x_error")
    if x_err_mid:
        return [
            f"error:event: error\ndata: {json.dumps({'type': 'error', 'error': {'type': 'api_error', 'message': f'Provider error: {x_err_mid}'}})}\n\n"
        ]

    choices = chunk.get("choices", [])
    if not choices:
        return []

    choice = choices[0]
    results: list[str] = []

    if choice.get("finish_reason"):
        results.append(f"finish:{choice['finish_reason']}")

    delta = choice.get("delta", {})

    # Accumulate tool calls
    delta_tc = delta.get("tool_calls", [])
    if delta_tc:
        accumulate_tool_calls(delta_tc)

    # Text content
    text = delta.get("content", "")
    if text:
        results.extend(emit_text(text))

    return results


__all__ = ["_create_anthropic_router"]
