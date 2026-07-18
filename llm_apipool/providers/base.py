"""Base types and abstract provider class for LLM providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator


@dataclass
class CompletionResult:
    """Result of a provider API completion call."""

    text: str
    tokens_used: int
    was_429: bool
    error: str | None = None
    remaining_requests: int | None = None
    rate_limit_headers: dict[str, Any] = field(default_factory=dict)
    reasoning_content: str | None = None
    tool_calls: list[dict[str, Any]] | None = None


@dataclass
class CompletionOptions:
    """Options for chat completion requests."""

    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: str | dict[str, Any] | None = None
    parallel_tool_calls: bool | None = None
    timeout_ms: int | None = None


@dataclass
class ChatCompletionResponse:
    """Normalized chat completion response."""

    id: str
    object: str = "chat.completion"
    created: int = 0
    model: str = ""
    choices: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, int] | None = None


@dataclass
class ChatCompletionChunk:
    """Normalized streaming chunk."""

    id: str
    object: str = "chat.completion.chunk"
    created: int = 0
    model: str = ""
    choices: list[dict[str, Any]] = field(default_factory=list)
    error: dict[str, Any] | None = None


class ProviderHttpError(Exception):
    """HTTP error from provider with status code and optional retry-after."""

    def __init__(self, status: int | None = None, retry_after_ms: int | None = None):
        self.status = status
        self.retry_after_ms = retry_after_ms
        super().__init__(f"Provider HTTP error: status={status}")


def parse_retry_after_ms(value: str | None) -> int | None:
    """Parse HTTP Retry-After header to milliseconds."""
    if not value:
        return None
    value = value.strip()
    try:
        return int(value) * 1000
    except ValueError:
        pass
    return None


class BaseProvider(ABC):
    """Abstract base class for all provider implementations."""

    @property
    @abstractmethod
    def platform(self) -> str:
        """Platform identifier (e.g., 'groq', 'openai')."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable provider name."""
        ...

    @property
    def keyless(self) -> bool:
        """Whether this provider needs no API key (default: False)."""
        return False

    @abstractmethod
    async def chat_completion(
        self,
        api_key: str,
        messages: list[dict[str, Any]],
        model_id: str,
        options: CompletionOptions | None = None,
    ) -> ChatCompletionResponse:
        """Generate a non-streaming chat completion."""
        ...

    @abstractmethod
    def stream_chat_completion(
        self,
        api_key: str,
        messages: list[dict[str, Any]],
        model_id: str,
        options: CompletionOptions | None = None,
    ) -> AsyncGenerator[ChatCompletionChunk, None]:
        """Generate a streaming chat completion."""
        ...

    @abstractmethod
    async def validate_key(self, api_key: str) -> bool:
        """Validate that an API key works for this provider."""
        ...
