from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

from llm_apipool.api.errors import (
    RATE_LIMIT_ERROR,
    ROUTING_ERROR,
    SERVER_ERROR,
    error_response,
)
from llm_apipool.api.routes.responses import (
    ResponsesRequest,
    build_response_object,
    to_chat_messages,
    to_chat_tools,
)
from llm_apipool.providers.dispatch import (
    _estimate_tokens,
    complete as dispatch_complete,
)
from llm_apipool.core.affinity import (
    is_affinity_enabled,
    register_request,
    on_success as affinity_success,
    on_error as affinity_error,
)
from llm_apipool.core.fallback_modes import get_fallback_modes
from llm_apipool.core.handoff import (
    get_handoff_mode,
    maybe_inject,
    record_incoming,
    record_successful,
)
from llm_apipool.core.slimey import get_slimey_router

MAX_RETRIES = 20


class _ChatRequest(BaseModel):
    model_config = {"extra": "ignore"}  # FreeLLMAPI-style: tolerate unknown fields

    model: str | None = None
    messages: list[dict[str, Any]]
    max_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    stream: bool | None = False
    stop: str | list[str] | None = None
    frequency_penalty: float | None = None
    presence_penalty: float | None = None
    seed: int | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: str | dict[str, Any] | None = None
    reasoning_effort: str | None = None
    response_format: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    user: str | None = None
    unicid: str | None = None


def _normalize_messages(messages: list[dict[str, Any]]) -> None:
    """Normalize incoming messages in-place to tolerate common client quirks.

    * ``developer`` role → ``system`` (OpenAI SDKs send ``developer``
      for newer models; providers only understand ``system``).
    * Assistant turns with null/empty content and no ``tool_calls`` → ``""``.
    * Tool-result turns with null/empty content → ``""``.
    """
    for msg in messages:
        role = msg.get("role")
        if role == "developer":
            msg["role"] = "system"
        elif role == "assistant":
            content = msg.get("content")
            has_tool_calls = bool(msg.get("tool_calls"))
            if not has_tool_calls and content is None:
                msg["content"] = ""
        elif role == "tool":
            if msg.get("content") is None:
                msg["content"] = ""


def _normalize_chunk(
    chunk: dict[str, Any], resp_id: str, created: int, model: str
) -> None:
    if "id" not in chunk:
        chunk["id"] = resp_id
    if "created" not in chunk:
        chunk["created"] = created
    if "model" not in chunk:
        chunk["model"] = model


def _compute_session_key(
    req: _ChatRequest,
    x_session_id: str | None,
) -> str:
    """Compute a stable session key from headers or the first user message."""
    if x_session_id:
        return x_session_id
    if req.unicid:
        # Reuse the sticky-session identifier
        return req.unicid
    # Fall back to a hash of the first user message
    for m in req.messages:
        if m.get("role") == "user":
            content = m.get("content", "")
            if isinstance(content, list):
                text = "".join(
                    p.get("text", "") for p in content if isinstance(p, dict)
                )
            else:
                text = str(content or "")
            return hashlib.sha256(text.encode()).hexdigest()[:16]
    return ""


def _setup_handoff(req: _ChatRequest, x_session_id: str | None) -> str:
    """Record incoming messages and return a session key (or empty)."""
    sk = _compute_session_key(req, x_session_id)
    if sk:
        record_incoming(sk, req.messages)
    return sk


def _inject_handoff(
    session_key: str, messages: list[dict[str, Any]], model_key: str
) -> list[dict[str, Any]]:
    """Apply handoff injection if the model changed for this session."""
    if not session_key or get_handoff_mode() == "off":
        return messages
    msgs, injected, _ = maybe_inject(session_key, messages, model_key)
    return msgs


def _create_chat_router(
    store: Any, rotator: Any, configs: dict[str, Any], default_capabilities: list[str]
) -> APIRouter:
    router = APIRouter()

    @router.post("/v1/chat/completions")
    async def chat_completions(
        req: _ChatRequest,
        x_apipool_capabilities: Annotated[str | None, Header()] = None,
        x_subscriber_id: Annotated[str | None, Header()] = None,
        x_session_id: Annotated[str | None, Header()] = None,
    ) -> Any:
        from llm_apipool.core.model_parser import ModelParser
        from llm_apipool.group_routing import extract_group, parse_context_filter

        # Normalize messages before any processing
        _normalize_messages(req.messages)

        # Context handoff — compute session key and record incoming messages
        session_key = _setup_handoff(req, x_session_id)

        if x_apipool_capabilities:
            caps = [c.strip() for c in x_apipool_capabilities.split(",") if c.strip()]
        else:
            caps = default_capabilities

        subscriber = x_subscriber_id or "proxy"

        model_param = req.model or "default"

        # When force_provider is active, override everything to the forced model
        if rotator.force_provider:
            forced_key_data = rotator.get_best_key(
                caps if caps else default_capabilities, subscriber_id=subscriber
            )
            forced_model = (forced_key_data or {}).get(
                "model", "deepseek-v4-flash-free"
            )
            model_param = forced_model

        group = extract_group(model_param)
        context_filter = parse_context_filter(model_param)
        min_context = None
        if context_filter:
            group, min_context = context_filter

        base_model, model_filter, strategy_override = ModelParser.parse(model_param)
        min_context = min_context or model_filter.context_min
        require_tools = model_filter.tools
        require_vision = model_filter.vision

        kwargs: dict[str, Any] = {}
        # When force_provider is active, the provider's model is authoritative
        # and must NOT be overridden by the user's requested model
        if not rotator.force_provider and model_param not in ("auto", "default"):
            kwargs["model"] = model_param
        # Forward all supported OpenAI params from the request to dispatch
        for _field in (
            "max_tokens",
            "temperature",
            "top_p",
            "stop",
            "frequency_penalty",
            "presence_penalty",
            "seed",
            "tools",
            "tool_choice",
            "reasoning_effort",
            "response_format",
            "metadata",
            "user",
        ):
            val = getattr(req, _field, None)
            if val is not None:
                kwargs[_field] = val

        resp_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        created = int(time.time())

        if req.stream:
            _msgs = _inject_handoff(session_key, req.messages, model_param)
            gen, key_data = await dispatch_complete(
                rotator,
                capabilities=caps,
                messages=_msgs,
                subscriber_id=subscriber,
                stream=True,
                min_context=min_context,
                require_tools=require_tools,
                require_vision=require_vision,
                http_method="POST",
                path="/v1/chat/completions",
                **kwargs,
            )
            if key_data is None:
                return error_response(
                    503, "All available keys exhausted", ROUTING_ERROR
                )

            model_used = (
                key_data.get("model", "unknown")
                if rotator.force_provider
                else (
                    model_param
                    if model_param not in ("auto", "default")
                    else key_data.get("model", "unknown")
                )
            )
            provider_used = key_data.get("provider", "unknown")

            # Slimey — QoS tracking for streaming
            _slimey_active = False
            _slimey_start = 0.0
            _slimey_tokens = 0
            _slimey_first_chunk = True
            if req.unicid and key_data:
                sr = get_slimey_router()
                if sr.is_enabled():
                    _slimey_active = True
                    sr.try_pin(
                        req.unicid,
                        key_data["provider"],
                        key_data.get("model", ""),
                        key_data["key_id"],
                    )
                    _slimey_start = time.monotonic()

            # Affinity — register request
            _affinity_registered = False
            if is_affinity_enabled() and req.unicid and key_data:
                kid = key_data.get("key_id", 0)
                mdl = key_data.get("model", "")
                if kid and mdl:
                    _affinity_registered = register_request(req.unicid, kid, mdl)

            if req.unicid and key_data.get("is_sticky_enabled"):
                store.create_sticky_session(
                    req.unicid,
                    key_data["key_id"],
                    key_data["provider"],
                    key_data.get("model"),
                    key_data.get("sticky_ttl_hours", 1),
                )

            async def _stream() -> AsyncGenerator[str, None]:
                nonlocal _slimey_tokens, _slimey_first_chunk
                async for chunk in gen:
                    # Slimey — record TTFT on first chunk
                    if _slimey_active and _slimey_first_chunk and req.unicid and key_data:
                        _slimey_first_chunk = False
                        ttft_ms = (time.monotonic() - _slimey_start) * 1000
                        get_slimey_router().record_ttft(
                            req.unicid,
                            key_data["provider"],
                            key_data.get("model", ""),
                            ttft_ms,
                        )
                    # Slimey — track tokens for throughput
                    if _slimey_active:
                        usage = chunk.get("usage")
                        if isinstance(usage, dict):
                            ct = usage.get("completion_tokens", 0)
                            if ct:
                                _slimey_tokens = ct
                        xt = chunk.get("x_tokens_used")
                        if xt:
                            _slimey_tokens = xt

                    x_err_mid = chunk.get("x_error")
                    if x_err_mid:
                        if _slimey_active and req.unicid and key_data:
                            get_slimey_router().record_error(
                                req.unicid,
                                key_data["provider"],
                                key_data.get("model", ""),
                            )
                        if _affinity_registered and req.unicid and key_data:
                            affinity_error(
                                req.unicid,
                                key_data["key_id"],
                                key_data.get("model", ""),
                            )
                        yield f"data: {json.dumps({'error': {'message': x_err_mid, 'type': 'stream_error'}})}\n\n"
                        yield "data: [DONE]\n\n"
                        return
                    _normalize_chunk(chunk, resp_id, created, model_used)
                    yield f"data: {json.dumps(chunk)}\n\n"
                # Stream completed successfully
                if _slimey_active and req.unicid and key_data:
                    elapsed = time.monotonic() - _slimey_start
                    if elapsed > 0 and _slimey_tokens > 0:
                        tp = _slimey_tokens / elapsed
                        get_slimey_router().record_throughput(
                            req.unicid,
                            key_data["provider"],
                            key_data.get("model", ""),
                            tp,
                        )
                        if not get_slimey_router().is_qos_acceptable(
                            req.unicid,
                            key_data["provider"],
                            key_data.get("model", ""),
                        ):
                            get_slimey_router().record_error(
                                req.unicid,
                                key_data["provider"],
                                key_data.get("model", ""),
                            )
                if _affinity_registered and req.unicid and key_data:
                    affinity_success(
                        req.unicid, key_data["key_id"], key_data.get("model", "")
                    )
                if session_key and key_data:
                    record_successful(session_key, key_data.get("model", ""))
                yield "data: [DONE]\n\n"

            return StreamingResponse(
                _stream(),
                media_type="text/event-stream",
                headers={
                    "X-Routed-Via": f"{provider_used}/{model_used}",
                    "X-Request-Id": resp_id,
                },
            )

        _t0 = time.monotonic()
        try:
            _msgs = _inject_handoff(session_key, req.messages, model_param)
            result, key_data = await dispatch_complete(
                rotator,
                capabilities=caps,
                messages=_msgs,
                subscriber_id=subscriber,
                min_context=min_context,
                require_tools=require_tools,
                require_vision=require_vision,
                http_method="POST",
                path="/v1/chat/completions",
                **kwargs,
            )
        except Exception as exc:
            return error_response(
                502, f"{type(exc).__name__}: {str(exc)[:200]}", SERVER_ERROR
            )

        # Slimey — record QoS for non-streaming
        if req.unicid and key_data and not getattr(result, "error", None):
            sr = get_slimey_router()
            if sr.is_enabled():
                sr.try_pin(
                    req.unicid,
                    key_data["provider"],
                    key_data.get("model", ""),
                    key_data["key_id"],
                )
                _elapsed = time.monotonic() - _t0
                if _elapsed > 0:
                    sr.record_ttft(
                        req.unicid,
                        key_data["provider"],
                        key_data.get("model", ""),
                        _elapsed * 1000,
                    )
                    if result.tokens_used > 0:
                        tp = result.tokens_used / _elapsed
                        sr.record_throughput(
                            req.unicid,
                            key_data["provider"],
                            key_data.get("model", ""),
                            tp,
                        )
                    if not sr.is_qos_acceptable(
                        req.unicid,
                        key_data["provider"],
                        key_data.get("model", ""),
                    ):
                        sr.record_error(
                            req.unicid,
                            key_data["provider"],
                            key_data.get("model", ""),
                        )

        # Affinity — register on success, or error
        aff_registered = False
        if is_affinity_enabled() and req.unicid and key_data:
            kid = key_data.get("key_id", 0)
            mdl = key_data.get("model", "")
            if kid and mdl:
                aff_registered = register_request(req.unicid, kid, mdl)

        if result.error and not result.text:
            if aff_registered and req.unicid and key_data:
                affinity_error(
                    req.unicid, key_data["key_id"], key_data.get("model", "")
                )
            if result.was_429:
                return error_response(429, result.error, RATE_LIMIT_ERROR)
            if "exhausted" in result.error.lower():
                return error_response(503, result.error, ROUTING_ERROR)
            return error_response(502, result.error, SERVER_ERROR)

        model_used = (
            key_data["model"]
            if (rotator.force_provider and key_data)
            else (
                model_param
                if model_param not in ("auto", "default")
                else (key_data["model"] if key_data else "unknown")
            )
        )
        provider_used = key_data["provider"] if key_data else "unknown"

        if req.unicid and key_data and key_data.get("is_sticky_enabled"):
            store.create_sticky_session(
                req.unicid,
                key_data["key_id"],
                key_data["provider"],
                key_data.get("model"),
                key_data.get("sticky_ttl_hours", 1),
            )

        # Affinity — mark success
        if aff_registered and req.unicid and key_data:
            affinity_success(req.unicid, key_data["key_id"], key_data.get("model", ""))
        if session_key and key_data:
            record_successful(session_key, key_data.get("model", ""))

        prompt_tokens = _estimate_tokens(req.messages)
        completion_tokens = result.tokens_used
        total_tokens = prompt_tokens + completion_tokens

        msg_out: dict[str, Any] = {"role": "assistant", "content": result.text}
        if getattr(result, "reasoning_content", None):
            msg_out["reasoning_content"] = result.reasoning_content
        if getattr(result, "tool_calls", None):
            # Ensure all tool_calls have IDs
            processed_tool_calls = []
            for tc in result.tool_calls:
                tc_id = tc.get("id")
                # Generate ID if missing, None, or not a valid string
                if tc_id and isinstance(tc_id, str) and len(tc_id) > 0:
                    final_id = tc_id
                else:
                    final_id = f"chatcmpl-tool-{uuid.uuid4().hex[:10]}"
                func = tc.get("function", {})
                # Ensure function has name and arguments
                processed_tool_calls.append(
                    {
                        "id": str(final_id),
                        "type": "function",
                        "function": {
                            "name": str(func.get("name", ""))
                            if isinstance(func, dict)
                            else "",
                            "arguments": str(func.get("arguments", ""))
                            if isinstance(func, dict)
                            else "",
                        },
                    }
                )
            msg_out["tool_calls"] = processed_tool_calls
        from fastapi.responses import JSONResponse

        return JSONResponse(
            content={
                "id": resp_id,
                "object": "chat.completion",
                "created": created,
                "model": model_used,
                "choices": [{"index": 0, "message": msg_out, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                },
            },
            headers={
                "X-Routed-Via": f"{provider_used}/{model_used}",
                "X-Request-Id": resp_id,
            },
        )

    @router.post("/v1/responses")
    async def responses_endpoint(
        req: ResponsesRequest,
        x_apipool_capabilities: Annotated[str | None, Header()] = None,
        x_subscriber_id: Annotated[str | None, Header()] = None,
    ) -> Any:
        from llm_apipool.core.model_parser import ModelParser

        caps = (
            x_apipool_capabilities.split(",")
            if x_apipool_capabilities
            else ["general_purpose"]
        )
        subscriber = x_subscriber_id or "responses"
        messages = to_chat_messages(req)
        _normalize_messages(messages)
        tools = to_chat_tools(req.tools)

        model_param = req.model or "auto"
        _, model_filter, _ = ModelParser.parse(model_param)

        response_id = f"resp_{uuid.uuid4().hex}"
        last_error: str | None = None
        last_key_data: dict[str, Any] | None = None
        last_result = None

        for _attempt in range(MAX_RETRIES):
            try:
                result, key_data = await dispatch_complete(
                    rotator,
                    capabilities=caps,
                    messages=messages,
                    subscriber_id=subscriber,
                    tools=tools,
                    max_tokens=req.max_output_tokens,
                    temperature=req.temperature,
                    top_p=req.top_p,
                    min_context=model_filter.context_min,
                    require_tools=model_filter.tools,
                    require_vision=model_filter.vision,
                    http_method="POST",
                    path="/v1/responses",
                )
                if result.text or getattr(result, "tool_calls", None):
                    last_result = result
                    last_key_data = key_data
                    break
                last_error = result.error
            except Exception as e:
                last_error = str(e)

        if not last_result or (
            not last_result.text and not getattr(last_result, "tool_calls", None)
        ):
            msg = last_error or "All available keys exhausted"
            if "rate" in msg.lower():
                return error_response(429, msg, RATE_LIMIT_ERROR)
            return error_response(503, msg, ROUTING_ERROR)

        model_out = (last_key_data or {}).get("model") or "auto"
        tool_calls = getattr(last_result, "tool_calls", None) or []
        # Ensure all tool_calls have IDs
        processed_tool_calls = []
        for tc in tool_calls:
            tc_id = tc.get("id")
            # Generate ID if missing, None, or not a valid string
            if tc_id and isinstance(tc_id, str) and len(tc_id) > 0:
                final_id = tc_id
            else:
                final_id = f"fc_{uuid.uuid4().hex[:16]}"
            func = tc.get("function", {})
            processed_tool_calls.append(
                {
                    "id": str(final_id),
                    "type": "function",
                    "function": {
                        "name": str(func.get("name", ""))
                        if isinstance(func, dict)
                        else "",
                        "arguments": str(func.get("arguments", ""))
                        if isinstance(func, dict)
                        else "",
                    },
                }
            )
        return build_response_object(
            response_id=response_id,
            model=model_out,
            text=last_result.text,
            tool_calls=processed_tool_calls,
            prompt_tokens=_estimate_tokens(messages),
            completion_tokens=last_result.tokens_used,
        )

    return router


__all__ = ["_create_chat_router"]
