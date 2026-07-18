"""Responses API endpoint for Codex CLI wire format compatibility.

Translated from server/src/routes/responses.ts
"""

from __future__ import annotations

import json
import time
import uuid
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter
from pydantic import BaseModel

if TYPE_CHECKING:
    pass

router = APIRouter()
MAX_RETRIES = 20


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _now_unix() -> int:
    return int(time.time())


# Request schema (lenient - we only consume the fields we can map)
class ContentPart(BaseModel):
    type: str | None = None


class MessageItem(BaseModel):
    type: str | None = None
    role: str | None = None
    content: str | list[ContentPart] | None = None


class FunctionCallItem(BaseModel):
    type: str | None = None
    call_id: str | None = None
    name: str | None = None
    arguments: str | None = None


class FunctionCallOutputItem(BaseModel):
    type: str | None = None
    call_id: str | None = None
    output: str | list[Any] | dict[str, Any] | None = None


# Accept ANY tool type, not just 'function'
class ResponsesTool(BaseModel):
    type: str = "function"
    name: str | None = None
    description: str | None = None
    parameters: dict[str, Any] | None = None
    strict: bool | None = None


class ResponsesRequest(BaseModel):
    model: str | None = None
    instructions: str | None = None
    input: str | list[Any] | None = None
    stream: bool = False
    temperature: float | None = None
    top_p: float | None = None
    max_output_tokens: int | None = None
    tools: list[ResponsesTool] | None = None
    tool_choice: str | dict[str, Any] | None = None
    parallel_tool_calls: bool | None = None


def _parts_to_string(content: str | list[dict[str, Any]]) -> str:
    """Responses content parts → plain text."""
    if isinstance(content, str):
        return content
    return "".join(p.get("text", "") for p in content if isinstance(p, dict))


def to_chat_messages(req: ResponsesRequest) -> list[dict[str, Any]]:
    """Translate Responses request → internal chat messages."""
    messages: list[dict[str, Any]] = []

    if req.instructions:
        messages.append({"role": "system", "content": req.instructions})

    if isinstance(req.input, str):
        messages.append({"role": "user", "content": req.input})
        return messages

    if req.input:
        for item in req.input:
            if isinstance(item, dict):
                item_type = item.get("type")
                if item_type == "function_call":
                    messages.append(
                        {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": item.get("call_id"),
                                    "type": "function",
                                    "function": {
                                        "name": item.get("name"),
                                        "arguments": item.get("arguments"),
                                    },
                                }
                            ],
                        }
                    )
                elif item_type == "function_call_output":
                    output = item.get("output")
                    if isinstance(output, str):
                        pass
                    elif isinstance(output, list):
                        output = _parts_to_string(output)
                    else:
                        output = json.dumps(output)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": item.get("call_id"),
                            "content": output,
                        }
                    )
                else:
                    role = item.get("role", "user")
                    if role == "developer":
                        role = "system"
                    messages.append(
                        {
                            "role": role,
                            "content": _parts_to_string(item.get("content", "")),
                        }
                    )

    return messages


def to_chat_tools(tools: list[ResponsesTool] | None) -> list[dict[str, Any]] | None:
    """Forward only function tools (chat-completions upstreams reject others)."""
    if not tools:
        return None
    return [t.model_dump() for t in tools if t.type == "function" and t.name]


def build_response_object(
    response_id: str,
    model: str,
    text: str,
    tool_calls: list[dict[str, Any]],
    prompt_tokens: int,
    completion_tokens: int,
) -> dict[str, Any]:
    """Build the final non-stream Responses object."""
    output: list[dict[str, Any]] = []
    if text:
        output.append(
            {
                "type": "message",
                "id": _new_id("msg"),
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
        )
    for tc in tool_calls:
        tc_id = tc.get("id")
        # Generate ID if missing, None, or not a valid string
        if tc_id and isinstance(tc_id, str) and len(tc_id) > 0:
            call_id = tc_id
        else:
            call_id = f"fc_{uuid.uuid4().hex[:16]}"
        func = tc.get("function", {})
        output.append(
            {
                "type": "function_call",
                "id": _new_id("fc"),
                "call_id": str(call_id),
                "name": str(func.get("name", "")) if isinstance(func, dict) else "",
                "arguments": str(func.get("arguments", ""))
                if isinstance(func, dict)
                else "",
                "status": "completed",
            }
        )

    return {
        "id": response_id,
        "object": "response",
        "created_at": _now_unix(),
        "status": "completed",
        "model": model,
        "output": output,
        "output_text": text,
        "usage": {
            "input_tokens": prompt_tokens,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens": completion_tokens,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }
