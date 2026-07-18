"""Tests for streaming code paths in openai_compat and dispatch.

Covers uncovered lines in:
- openai_compat.py: 24, 35, 49-70, 80, 97-171, 190, 220-224 (tool_calls id generation)
- dispatch.py: 32-34, 49, 72-112, 123-128, 134-144, 148-163
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from llm_apipool.providers import openai_compat as oc
from llm_apipool.providers.base import CompletionResult


# Clear client cache before each test to prevent test pollution from connection pooling
@pytest.fixture(autouse=True)
def _clear_cache():
    oc._clear_client_cache()


# ---------------------------------------------------------------------------
# openai_compat._NoAuth
# ---------------------------------------------------------------------------


class TestNoAuth:
    """_NoAuth — httpx Auth handler that strips Authorization header."""

    def test_strips_authorization_header(self):
        """_NoAuth.auth_flow removes the Authorization header."""
        request = httpx.Request("POST", "https://example.com/v1/chat/completions")
        request.headers["authorization"] = "Bearer some-token"
        request.headers["content-type"] = "application/json"

        auth = oc._NoAuth()
        results = list(auth.auth_flow(request))
        assert len(results) == 1
        assert "authorization" not in results[0].headers
        # Other headers preserved
        assert results[0].headers["content-type"] == "application/json"

    def test_no_header_no_error(self):
        """_NoAuth handles requests with no Authorization header gracefully."""
        request = httpx.Request("POST", "https://example.com/v1/chat/completions")
        auth = oc._NoAuth()
        results = list(auth.auth_flow(request))
        assert len(results) == 1

    def test_empty_authorization_header(self):
        """_NoAuth handles empty Authorization header."""
        request = httpx.Request("POST", "https://example.com/v1/chat/completions")
        request.headers["authorization"] = ""
        auth = oc._NoAuth()
        results = list(auth.auth_flow(request))
        assert len(results) == 1
        assert "authorization" not in results[0].headers


# ---------------------------------------------------------------------------
# openai_compat._make_client
# ---------------------------------------------------------------------------


class TestMakeClient:
    """_make_client — creates AsyncOpenAI with correct config."""

    BASE_URL = "https://api.test.com/v1"
    API_KEY = "sk-test-key-12345"

    def test_no_auth_true_uses_sentinel_key(self):
        """no_auth=True creates client with sentinel key and custom http_client."""
        client = oc._make_client(
            base_url=self.BASE_URL,
            api_key=self.API_KEY,
            no_auth=True,
        )
        assert client.api_key == "sentinel-no-op"
        assert str(client.base_url) == f"{self.BASE_URL}/"

    def test_no_auth_false_uses_real_key(self):
        """no_auth=False creates client with real API key."""
        client = oc._make_client(
            base_url=self.BASE_URL,
            api_key=self.API_KEY,
            no_auth=False,
        )
        assert client.api_key == self.API_KEY
        assert str(client.base_url) == f"{self.BASE_URL}/"

    def test_empty_api_key_triggers_no_auth_path(self):
        """Empty api_key triggers the _NoAuth path even if no_auth=False."""
        client = oc._make_client(
            base_url=self.BASE_URL,
            api_key="",
            no_auth=False,
        )
        assert client.api_key == "sentinel-no-op"
        assert str(client.base_url) == f"{self.BASE_URL}/"

    def test_empty_key_placeholder_triggers_no_auth_path(self):
        """ "empty-key-placeholder" triggers the _NoAuth path."""
        client = oc._make_client(
            base_url=self.BASE_URL,
            api_key="empty-key-placeholder",
            no_auth=False,
        )
        assert client.api_key == "sentinel-no-op"
        assert str(client.base_url) == f"{self.BASE_URL}/"


# ---------------------------------------------------------------------------
# openai_compat._mask_key
# ---------------------------------------------------------------------------


class TestOpenaiCompatMaskKey:
    """_mask_key — safe API-key masking for logs."""

    def test_normal(self):
        """Len > 8: show first 4 + **** + last 4."""
        assert oc._mask_key("sk-abc12345def67890") == "sk-a****7890"

    def test_short(self):
        """Len <= 8 but > 4: show last 4 with **** prefix."""
        assert oc._mask_key("abc12345") == "****2345"

    def test_very_short(self):
        """Len <= 4: just return ****."""
        assert oc._mask_key("abc") == "****"

    def test_empty(self):
        """Empty string returns ****."""
        assert oc._mask_key("") == "****"


# ---------------------------------------------------------------------------
# openai_compat._make_chunk_id
# ---------------------------------------------------------------------------


class TestOpenaiCompatMakeChunkId:
    """_make_chunk_id — unique chunk ID generation."""

    def test_returns_chatcmpl_prefix(self):
        chunk_id = oc._make_chunk_id()
        assert chunk_id.startswith("chatcmpl-")

    def test_unique_ids(self):
        ids = {oc._make_chunk_id() for _ in range(100)}
        assert len(ids) == 100


# ---------------------------------------------------------------------------
# openai_compat._strip_thinking
# ---------------------------------------------------------------------------


class TestOpenaiCompatStripThinking:
    """_strip_thinking — strip <think> blocks from text."""

    def test_no_think_tags(self):
        assert oc._strip_thinking("Hello world") == "Hello world"

    def test_closed_think_tag(self):
        result = oc._strip_thinking(
            "<think>Let me reason</think>\nThe answer is 42.",
        )
        assert "think" not in result
        assert result.startswith("The answer is 42.")

    def test_open_think_tag_strips_all(self):
        """Open <think> with no </think> matches to end of string."""
        result = oc._strip_thinking(
            "<think>Unfinished reasoning\nThe answer is 42.",
        )
        assert result == ""

    def test_only_think_block(self):
        assert oc._strip_thinking("<think>thinking</think>") == ""

    def test_empty_string(self):
        assert oc._strip_thinking("") == ""

    def test_whitespace_only(self):
        assert oc._strip_thinking("   ") == ""

    def test_multiline_think_block(self):
        text = (
            "<think>Step 1: analyze\n"
            "Step 2: compute\n"
            "Step 3: conclude</think>\n"
            "Final output here.\n"
        )
        result = oc._strip_thinking(text)
        assert result == "Final output here."

    def test_no_whitespace_after_close(self):
        """Trailing whitespace/newlines after </think> are stripped."""
        result = oc._strip_thinking(
            "<think>hmm</think>\n\n\nAnswer",
        )
        assert result == "Answer"


# ---------------------------------------------------------------------------
# openai_compat._build_chunk
# ---------------------------------------------------------------------------


class TestOpenaiCompatBuildChunk:
    """_build_chunk — build OpenAI-format streaming chunk dicts."""

    CHUNK_ID = "chatcmpl-test"
    CREATED = 1_000_000
    MODEL = "test-model"

    def test_delta_content_only(self):
        chunk = oc._build_chunk(
            self.CHUNK_ID,
            self.CREATED,
            self.MODEL,
            delta_content="Hello",
        )
        assert chunk["id"] == self.CHUNK_ID
        assert chunk["object"] == "chat.completion.chunk"
        assert chunk["created"] == self.CREATED
        assert chunk["model"] == self.MODEL
        assert len(chunk["choices"]) == 1
        assert chunk["choices"][0]["delta"] == {"content": "Hello"}
        assert chunk["choices"][0]["finish_reason"] is None

    def test_delta_role_only(self):
        chunk = oc._build_chunk(
            self.CHUNK_ID,
            self.CREATED,
            self.MODEL,
            delta_role="assistant",
        )
        assert chunk["choices"][0]["delta"] == {"role": "assistant"}

    def test_finish_reason_only(self):
        chunk = oc._build_chunk(
            self.CHUNK_ID,
            self.CREATED,
            self.MODEL,
            finish_reason="stop",
        )
        assert chunk["choices"][0]["finish_reason"] == "stop"
        assert chunk["choices"][0]["delta"] == {}

    def test_all_params(self):
        chunk = oc._build_chunk(
            self.CHUNK_ID,
            self.CREATED,
            self.MODEL,
            delta_content="Hello",
            delta_role="assistant",
            finish_reason="stop",
            index=1,
        )
        assert len(chunk["choices"]) == 1
        assert chunk["choices"][0]["index"] == 1
        assert chunk["choices"][0]["delta"] == {
            "role": "assistant",
            "content": "Hello",
        }
        assert chunk["choices"][0]["finish_reason"] == "stop"

    def test_extra_kwargs(self):
        chunk = oc._build_chunk(
            self.CHUNK_ID,
            self.CREATED,
            self.MODEL,
            x_custom="value",
            x_tokens_used=42,
        )
        assert chunk["x_custom"] == "value"
        assert chunk["x_tokens_used"] == 42

    def test_all_none_optionals(self):
        """When all optional params are None, choices is empty list."""
        chunk = oc._build_chunk(
            self.CHUNK_ID,
            self.CREATED,
            self.MODEL,
        )
        assert chunk["choices"] == []

    def test_delta_content_empty_string(self):
        """Empty string content is still included."""
        chunk = oc._build_chunk(
            self.CHUNK_ID,
            self.CREATED,
            self.MODEL,
            delta_content="",
        )
        assert chunk["choices"][0]["delta"]["content"] == ""


# ---------------------------------------------------------------------------
# openai_compat._build_error_chunk
# ---------------------------------------------------------------------------


class TestOpenaiCompatBuildErrorChunk:
    """_build_error_chunk — build error chunk dicts."""

    CHUNK_ID = "chatcmpl-err"
    CREATED = 2_000_000
    MODEL = "err-model"
    ERROR_MSG = "Something went wrong"

    def test_default_was_429_false(self):
        chunk = oc._build_error_chunk(
            self.CHUNK_ID,
            self.CREATED,
            self.MODEL,
            self.ERROR_MSG,
        )
        assert chunk["x_error"] == self.ERROR_MSG
        assert chunk["x_was_429"] is False

    def test_was_429_true(self):
        chunk = oc._build_error_chunk(
            self.CHUNK_ID,
            self.CREATED,
            self.MODEL,
            self.ERROR_MSG,
            was_429=True,
        )
        assert chunk["x_error"] == self.ERROR_MSG
        assert chunk["x_was_429"] is True


# ---------------------------------------------------------------------------
# openai_compat._make_stream_gen
# ---------------------------------------------------------------------------


@pytest.fixture
def stream_gen_kwargs() -> dict:
    """Standard keyword arguments for _make_stream_gen."""
    return {
        "key_data": {
            "provider": "test",
            "model": "test-model",
            "api_key": "test-key",
            "base_url": "https://test.com/v1",
        },
        "messages": [{"role": "user", "content": "Hello"}],
        "model": "test-model",
        "provider": "test",
        "api_key": "test-key",
        "base_url": "https://test.com/v1",
        "strip_thinking": True,
    }


@pytest.fixture
def mock_openai_client() -> MagicMock:
    """Build a mock AsyncOpenAI client.

    Callers must attach ``client.chat.completions.with_raw_response.create``
    (as an ``AsyncMock``) and ``raw.parse()`` (returning an async iterable).
    """
    client = MagicMock()
    client.chat.completions.with_raw_response.create = AsyncMock()
    return client


class TestOpenaiCompatMakeStreamGen:
    """_make_stream_gen — async generator for streaming."""

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _choice_maker(
        delta_content: str | None = None,
        delta_role: str | None = None,
        finish_reason: str | None = None,
        index: int = 0,
        reasoning_content: str | None = None,
        reasoning: str | None = None,
    ) -> MagicMock:
        delta = MagicMock(content=delta_content, role=delta_role)
        delta.reasoning_content = reasoning_content
        delta.reasoning = reasoning
        return MagicMock(
            delta=delta,
            finish_reason=finish_reason,
            index=index,
        )

    @staticmethod
    def _event_maker(
        choices: list | None = None,
        total_tokens: int | None = None,
    ) -> MagicMock:
        usage = (
            MagicMock(total_tokens=total_tokens) if total_tokens is not None else None
        )
        return MagicMock(choices=choices or [], usage=usage)

    # -- normal streaming -------------------------------------------------

    @pytest.mark.asyncio
    async def test_normal_streaming(self, stream_gen_kwargs, mock_openai_client):
        """Normal streaming yields content chunks, ending with usage."""

        async def _stream():
            yield self._event_maker(
                choices=[
                    self._choice_maker(delta_content="Hello", delta_role="assistant")
                ],
            )
            yield self._event_maker(
                choices=[
                    self._choice_maker(delta_content=" world", finish_reason="stop")
                ],
                total_tokens=10,
            )

        raw = MagicMock()
        raw.parse = MagicMock(return_value=_stream())
        mock_openai_client.chat.completions.with_raw_response.create = AsyncMock(
            return_value=raw,
        )

        with patch(
            "llm_apipool.providers.openai_compat.AsyncOpenAI",
            return_value=mock_openai_client,
        ):
            gen = oc._make_stream_gen(**stream_gen_kwargs)
            chunks = [c async for c in gen]

        assert len(chunks) == 2
        # First chunk
        assert chunks[0]["choices"][0]["delta"]["content"] == "Hello"
        assert chunks[0]["choices"][0]["delta"]["role"] == "assistant"
        assert chunks[0]["choices"][0]["finish_reason"] is None
        assert "x_tokens_used" not in chunks[0]
        # Second chunk
        assert chunks[1]["choices"][0]["delta"]["content"] == " world"
        assert chunks[1]["choices"][0]["finish_reason"] == "stop"
        assert chunks[1]["x_tokens_used"] == 10
        # Common fields
        for c in chunks:
            assert c["object"] == "chat.completion.chunk"
            assert c["model"] == "test-model"

    @pytest.mark.asyncio
    async def test_reasoning_content_not_folded_in_streaming(
        self, stream_gen_kwargs, mock_openai_client
    ):
        """reasoning_content is NOT folded into content during streaming (FreeLLMAPI compat)."""

        async def _stream():
            yield self._event_maker(
                choices=[self._choice_maker(delta_role="assistant")],
            )
            yield self._event_maker(
                choices=[
                    self._choice_maker(
                        reasoning_content="Let me think about this...",
                    )
                ],
            )
            yield self._event_maker(
                choices=[
                    self._choice_maker(
                        reasoning_content="The answer is 42.",
                        finish_reason="stop",
                    )
                ],
                total_tokens=15,
            )

        raw = MagicMock()
        raw.parse = MagicMock(return_value=_stream())
        mock_openai_client.chat.completions.with_raw_response.create = AsyncMock(
            return_value=raw,
        )

        with patch(
            "llm_apipool.providers.openai_compat.AsyncOpenAI",
            return_value=mock_openai_client,
        ):
            gen = oc._make_stream_gen(**stream_gen_kwargs)
            chunks = [c async for c in gen]

        assert len(chunks) == 3
        assert "content" not in chunks[0]["choices"][0]["delta"]
        assert chunks[0]["choices"][0]["delta"]["role"] == "assistant"
        # reasoning_content is its own field, NOT folded into content
        assert "content" not in chunks[1]["choices"][0]["delta"]
        assert (
            chunks[1]["choices"][0]["delta"]["reasoning_content"]
            == "Let me think about this..."
        )
        assert "content" not in chunks[2]["choices"][0]["delta"]
        assert (
            chunks[2]["choices"][0]["delta"]["reasoning_content"] == "The answer is 42."
        )
        assert chunks[2]["choices"][0]["finish_reason"] == "stop"
        assert chunks[2]["x_tokens_used"] == 15

    @pytest.mark.asyncio
    async def test_real_content_not_overridden_by_reasoning(
        self, stream_gen_kwargs, mock_openai_client
    ):
        """Real content and reasoning_content are separate fields in streaming."""

        async def _stream():
            yield self._event_maker(
                choices=[
                    self._choice_maker(
                        reasoning_content="Thinking step by step...",
                    )
                ],
            )
            yield self._event_maker(
                choices=[
                    self._choice_maker(
                        delta_content="The answer is ",
                        reasoning_content="",
                    )
                ],
            )
            yield self._event_maker(
                choices=[
                    self._choice_maker(
                        delta_content="42.",
                        reasoning_content="",
                        finish_reason="stop",
                    )
                ],
            )

        raw = MagicMock()
        raw.parse = MagicMock(return_value=_stream())
        mock_openai_client.chat.completions.with_raw_response.create = AsyncMock(
            return_value=raw,
        )

        with patch(
            "llm_apipool.providers.openai_compat.AsyncOpenAI",
            return_value=mock_openai_client,
        ):
            gen = oc._make_stream_gen(**stream_gen_kwargs)
            chunks = [c async for c in gen]

        assert len(chunks) == 3
        # reasoning-only chunk: content is NOT set (not folded)
        assert "content" not in chunks[0]["choices"][0]["delta"]
        assert (
            chunks[0]["choices"][0]["delta"]["reasoning_content"]
            == "Thinking step by step..."
        )
        # subsequent chunks with real content work as normal
        assert chunks[1]["choices"][0]["delta"]["content"] == "The answer is "
        assert chunks[1]["choices"][0]["delta"]["reasoning_content"] == ""
        assert chunks[2]["choices"][0]["delta"]["content"] == "42."
        assert chunks[2]["choices"][0]["finish_reason"] == "stop"

    @pytest.mark.asyncio
    async def test_reasoning_fallback_ollama_not_folded(
        self, stream_gen_kwargs, mock_openai_client
    ):
        """Ollama 'reasoning' field is NOT folded into content during streaming."""

        async def _stream():
            yield self._event_maker(
                choices=[
                    self._choice_maker(
                        reasoning="Ollama reasoning...",
                    )
                ],
            )
            yield self._event_maker(
                choices=[
                    self._choice_maker(
                        delta_content="Actual answer",
                        finish_reason="stop",
                    )
                ],
            )

        raw = MagicMock()
        raw.parse = MagicMock(return_value=_stream())
        mock_openai_client.chat.completions.with_raw_response.create = AsyncMock(
            return_value=raw,
        )

        with patch(
            "llm_apipool.providers.openai_compat.AsyncOpenAI",
            return_value=mock_openai_client,
        ):
            gen = oc._make_stream_gen(**stream_gen_kwargs)
            chunks = [c async for c in gen]

        assert len(chunks) == 2
        # Ollama reasoning is its own field, NOT folded into content during streaming
        assert "content" not in chunks[0]["choices"][0]["delta"]
        assert chunks[0]["choices"][0]["delta"]["reasoning"] == "Ollama reasoning..."
        assert chunks[1]["choices"][0]["delta"]["content"] == "Actual answer"

    @pytest.mark.asyncio
    async def test_no_auth_true_creates_correct_client(
        self, stream_gen_kwargs, mock_openai_client
    ):
        """no_auth=True passes through _make_client to create sentinel-key client."""

        async def _stream():
            yield self._event_maker(
                choices=[
                    self._choice_maker(delta_content="Hello", finish_reason="stop")
                ],
                total_tokens=5,
            )

        raw = MagicMock()
        raw.parse = MagicMock(return_value=_stream())
        mock_openai_client.chat.completions.with_raw_response.create = AsyncMock(
            return_value=raw,
        )

        with patch(
            "llm_apipool.providers.openai_compat.AsyncOpenAI",
            return_value=mock_openai_client,
        ) as mock_async_openai:
            gen = oc._make_stream_gen(
                **{**stream_gen_kwargs, "no_auth": True},
            )
            chunks = [c async for c in gen]

        assert len(chunks) == 1
        assert chunks[0]["choices"][0]["delta"]["content"] == "Hello"
        # Verify AsyncOpenAI was constructed with sentinel key
        mock_async_openai.assert_called_once()
        _call_kwargs = mock_async_openai.call_args[1]
        assert _call_kwargs["api_key"] == "sentinel-no-op"

    @pytest.mark.asyncio
    async def test_empty_choices(self, stream_gen_kwargs, mock_openai_client):
        """Events with empty choices still yield a chunk."""

        async def _stream():
            yield self._event_maker(choices=[])

        raw = MagicMock()
        raw.parse = MagicMock(return_value=_stream())
        mock_openai_client.chat.completions.with_raw_response.create = AsyncMock(
            return_value=raw,
        )

        with patch(
            "llm_apipool.providers.openai_compat.AsyncOpenAI",
            return_value=mock_openai_client,
        ):
            gen = oc._make_stream_gen(**stream_gen_kwargs)
            chunks = [c async for c in gen]

        assert len(chunks) == 1
        assert chunks[0]["choices"] == []

    # -- error conditions -------------------------------------------------

    @pytest.mark.asyncio
    async def test_rate_limit_error(self, stream_gen_kwargs, mock_openai_client):
        """RateLimitError yields error chunk with was_429=True."""
        from openai import RateLimitError

        mock_openai_client.chat.completions.with_raw_response.create = AsyncMock(
            side_effect=RateLimitError(
                message="Rate limited",
                response=MagicMock(status_code=429),
                body={},
            ),
        )

        with patch(
            "llm_apipool.providers.openai_compat.AsyncOpenAI",
            return_value=mock_openai_client,
        ):
            gen = oc._make_stream_gen(**stream_gen_kwargs)
            chunks = [c async for c in gen]

        assert len(chunks) == 1
        assert chunks[0]["x_was_429"] is True
        assert "429" in chunks[0]["x_error"]

    @pytest.mark.asyncio
    async def test_api_status_error(self, stream_gen_kwargs, mock_openai_client):
        """APIStatusError yields error chunk with HTTP status."""
        from openai import APIStatusError

        mock_openai_client.chat.completions.with_raw_response.create = AsyncMock(
            side_effect=APIStatusError(
                message="Bad Request",
                response=MagicMock(status_code=400),
                body={},
            ),
        )

        with patch(
            "llm_apipool.providers.openai_compat.AsyncOpenAI",
            return_value=mock_openai_client,
        ):
            gen = oc._make_stream_gen(**stream_gen_kwargs)
            chunks = [c async for c in gen]

        assert len(chunks) == 1
        assert chunks[0]["x_was_429"] is False
        assert "HTTP 400" in chunks[0]["x_error"]

    @pytest.mark.asyncio
    async def test_timeout_exception(self, stream_gen_kwargs, mock_openai_client):
        """httpx.TimeoutException yields error chunk with timeout message."""
        mock_openai_client.chat.completions.with_raw_response.create = AsyncMock(
            side_effect=httpx.TimeoutException("Connection timed out"),
        )

        with patch(
            "llm_apipool.providers.openai_compat.AsyncOpenAI",
            return_value=mock_openai_client,
        ):
            gen = oc._make_stream_gen(**stream_gen_kwargs)
            chunks = [c async for c in gen]

        assert len(chunks) == 1
        assert "timed out" in chunks[0]["x_error"].lower()

    @pytest.mark.asyncio
    async def test_network_error(self, stream_gen_kwargs, mock_openai_client):
        """httpx.NetworkError yields error chunk with network message."""
        mock_openai_client.chat.completions.with_raw_response.create = AsyncMock(
            side_effect=httpx.NetworkError("DNS resolution failed"),
        )

        with patch(
            "llm_apipool.providers.openai_compat.AsyncOpenAI",
            return_value=mock_openai_client,
        ):
            gen = oc._make_stream_gen(**stream_gen_kwargs)
            chunks = [c async for c in gen]

        assert len(chunks) == 1
        error_msg = chunks[0]["x_error"].lower()
        assert "network" in error_msg or "request error" in error_msg

    @pytest.mark.asyncio
    async def test_tool_calls_with_missing_id_gets_generated(
        self, stream_gen_kwargs, mock_openai_client
    ):
        """Tool calls without id get a generated unique id."""
        from unittest.mock import MagicMock

        # Create a tool_call delta with no id (simulates upstream not providing it)
        tool_call_mock = MagicMock(index=0)
        tool_call_mock.id = None  # Missing id
        tool_call_mock.type = "function"
        tool_call_mock.function = MagicMock(
            name="get_weather", arguments='{"city": "SF"}'
        )

        delta = MagicMock(content=None, role="assistant")
        delta.tool_calls = [tool_call_mock]
        delta.reasoning = None
        delta.reasoning_content = None

        async def _stream():
            yield self._event_maker(
                choices=[MagicMock(delta=delta, finish_reason=None, index=0)],
            )

        raw = MagicMock()
        raw.parse = MagicMock(return_value=_stream())
        mock_openai_client.chat.completions.with_raw_response.create = AsyncMock(
            return_value=raw,
        )

        with patch(
            "llm_apipool.providers.openai_compat.AsyncOpenAI",
            return_value=mock_openai_client,
        ):
            gen = oc._make_stream_gen(**stream_gen_kwargs)
            chunks = [c async for c in gen]

        assert len(chunks) == 1
        tool_calls = chunks[0]["choices"][0]["delta"]["tool_calls"]
        assert len(tool_calls) == 1
        assert "id" in tool_calls[0]
        assert tool_calls[0]["id"].startswith("chatcmpl-tool-")

    @pytest.mark.asyncio
    async def test_tool_calls_with_provided_id_preserved(
        self, stream_gen_kwargs, mock_openai_client
    ):
        """Tool calls with id preserve the upstream value."""
        from unittest.mock import MagicMock

        tool_call_mock = MagicMock(index=0)
        tool_call_mock.id = "call_abc123"
        tool_call_mock.type = "function"
        tool_call_mock.function = MagicMock(
            name="get_weather", arguments='{"city": "SF"}'
        )

        delta = MagicMock(content=None, role="assistant")
        delta.tool_calls = [tool_call_mock]
        delta.reasoning = None
        delta.reasoning_content = None

        async def _stream():
            yield self._event_maker(
                choices=[MagicMock(delta=delta, finish_reason=None, index=0)],
            )

        raw = MagicMock()
        raw.parse = MagicMock(return_value=_stream())
        mock_openai_client.chat.completions.with_raw_response.create = AsyncMock(
            return_value=raw,
        )

        with patch(
            "llm_apipool.providers.openai_compat.AsyncOpenAI",
            return_value=mock_openai_client,
        ):
            gen = oc._make_stream_gen(**stream_gen_kwargs)
            chunks = [c async for c in gen]

        assert len(chunks) == 1
        tool_calls = chunks[0]["choices"][0]["delta"]["tool_calls"]
        assert tool_calls[0]["id"] == "call_abc123"

    @pytest.mark.asyncio
    async def test_tool_calls_with_empty_string_id_gets_generated(
        self, stream_gen_kwargs, mock_openai_client
    ):
        """Tool calls with empty string id get a generated unique id."""
        from unittest.mock import MagicMock

        tool_call_mock = MagicMock(index=0)
        tool_call_mock.id = ""  # Empty string id (also falsy)
        tool_call_mock.type = "function"
        tool_call_mock.function = MagicMock(
            name="get_weather", arguments='{"city": "SF"}'
        )

        delta = MagicMock(content=None, role="assistant")
        delta.tool_calls = [tool_call_mock]
        delta.reasoning = None
        delta.reasoning_content = None

        async def _stream():
            yield self._event_maker(
                choices=[MagicMock(delta=delta, finish_reason=None, index=0)],
            )

        raw = MagicMock()
        raw.parse = MagicMock(return_value=_stream())
        mock_openai_client.chat.completions.with_raw_response.create = AsyncMock(
            return_value=raw,
        )

        with patch(
            "llm_apipool.providers.openai_compat.AsyncOpenAI",
            return_value=mock_openai_client,
        ):
            gen = oc._make_stream_gen(**stream_gen_kwargs)
            chunks = [c async for c in gen]

        assert len(chunks) == 1
        tool_calls = chunks[0]["choices"][0]["delta"]["tool_calls"]
        assert len(tool_calls) == 1
        assert "id" in tool_calls[0]
        assert tool_calls[0]["id"].startswith("chatcmpl-tool-")

    @pytest.mark.asyncio
    async def test_generic_exception(self, stream_gen_kwargs, mock_openai_client):
        """Generic Exception yields error chunk with Unexpected error prefix."""
        mock_openai_client.chat.completions.with_raw_response.create = AsyncMock(
            side_effect=ValueError("something unexpected"),
        )

        with patch(
            "llm_apipool.providers.openai_compat.AsyncOpenAI",
            return_value=mock_openai_client,
        ):
            gen = oc._make_stream_gen(**stream_gen_kwargs)
            chunks = [c async for c in gen]

        assert len(chunks) == 1
        assert "Unexpected error" in chunks[0]["x_error"]
        assert "ValueError" in chunks[0]["x_error"]


# ---------------------------------------------------------------------------
# openai_compat.complete with stream=True
# ---------------------------------------------------------------------------


@pytest.fixture
def key_data() -> dict:
    return {
        "provider": "groq",
        "model": "llama-3.3-70b-versatile",
        "base_url": "https://api.groq.com/openai/v1",
        "api_key": "gsk_test123",
        "openai_compatible": True,
    }


class TestOpenaiCompatCompleteStream:
    """openai_compat.complete with stream=True routing."""

    @pytest.mark.asyncio
    async def test_complete_stream_routes_to_make_stream_gen(self, key_data):
        """stream=True returns the result of _make_stream_gen."""
        with patch("llm_apipool.providers.openai_compat._make_stream_gen") as mock_gen:
            expected = "stream_generator"
            mock_gen.return_value = expected

            result = await oc.complete(
                key_data,
                [{"role": "user", "content": "Hi"}],
                stream=True,
            )

            assert result == expected
            mock_gen.assert_called_once_with(
                key_data,
                [{"role": "user", "content": "Hi"}],
                "llama-3.3-70b-versatile",
                provider="groq",
                api_key="gsk_test123",
                base_url="https://api.groq.com/openai/v1",
                strip_thinking=True,
                no_auth=False,
            )

    @pytest.mark.asyncio
    async def test_complete_stream_with_extra_kwargs(self, key_data):
        """Extra kwargs are forwarded to _make_stream_gen."""
        with patch("llm_apipool.providers.openai_compat._make_stream_gen") as mock_gen:
            mock_gen.return_value = "stream_gen"

            await oc.complete(
                key_data,
                [{"role": "user", "content": "Hi"}],
                stream=True,
                temperature=0.7,
                max_tokens=100,
            )

            _call_kwargs = mock_gen.call_args[1]
            assert _call_kwargs["temperature"] == 0.7
            assert _call_kwargs["max_tokens"] == 100

    @pytest.mark.asyncio
    async def test_complete_stream_strip_thinking_default(self, key_data):
        """strip_thinking defaults to True and is passed to _make_stream_gen."""
        with patch("llm_apipool.providers.openai_compat._make_stream_gen") as mock_gen:
            mock_gen.return_value = "stream_gen"

            await oc.complete(
                key_data,
                [{"role": "user", "content": "Hi"}],
                stream=True,
            )

            assert mock_gen.call_args[1]["strip_thinking"] is True

    @pytest.mark.asyncio
    async def test_complete_stream_strip_thinking_false(self, key_data):
        """strip_thinking=False is forwarded to _make_stream_gen."""
        with patch("llm_apipool.providers.openai_compat._make_stream_gen") as mock_gen:
            mock_gen.return_value = "stream_gen"

            await oc.complete(
                key_data,
                [{"role": "user", "content": "Hi"}],
                stream=True,
                strip_thinking=False,
            )

            assert mock_gen.call_args[1]["strip_thinking"] is False

    @pytest.mark.asyncio
    async def test_complete_stream_empty_api_key(self, key_data):
        """Empty api_key uses 'empty-key-placeholder'."""
        key_data["api_key"] = ""
        with patch("llm_apipool.providers.openai_compat._make_stream_gen") as mock_gen:
            mock_gen.return_value = "stream_gen"

            await oc.complete(
                key_data,
                [{"role": "user", "content": "Hi"}],
                stream=True,
            )

            assert mock_gen.call_args[1]["api_key"] == "empty-key-placeholder"

    @pytest.mark.asyncio
    async def test_complete_stream_with_model_in_kwargs(self, key_data):
        """model kwarg overrides key_data model."""
        with patch("llm_apipool.providers.openai_compat._make_stream_gen") as mock_gen:
            mock_gen.return_value = "stream_gen"

            await oc.complete(
                key_data,
                [{"role": "user", "content": "Hi"}],
                stream=True,
                model="custom-model",
            )

            # model is popped from kwargs and passed as positional arg
            args = mock_gen.call_args[0]
            assert args[2] == "custom-model"  # third positional = model
            assert "model" not in mock_gen.call_args[1]

    @pytest.mark.asyncio
    async def test_complete_stream_no_auth_true(self, key_data):
        """no_auth=True in key_data is forwarded to _make_stream_gen."""
        key_data["no_auth"] = True
        with patch("llm_apipool.providers.openai_compat._make_stream_gen") as mock_gen:
            mock_gen.return_value = "stream_gen"

            await oc.complete(
                key_data,
                [{"role": "user", "content": "Hi"}],
                stream=True,
            )

            assert mock_gen.call_args[1]["no_auth"] is True

    @pytest.mark.asyncio
    async def test_complete_stream_no_auth_default(self, key_data):
        """When no no_auth in key_data, _make_stream_gen gets no_auth=False."""
        with patch("llm_apipool.providers.openai_compat._make_stream_gen") as mock_gen:
            mock_gen.return_value = "stream_gen"

            await oc.complete(
                key_data,
                [{"role": "user", "content": "Hi"}],
                stream=True,
            )

            assert mock_gen.call_args[1]["no_auth"] is False


# ---------------------------------------------------------------------------
# dispatch._estimate_tokens (fallback)
# ---------------------------------------------------------------------------


class TestDispatchEstimateTokensFallback:
    """dispatch._estimate_tokens — fallback when tiktoken unavailable."""

    def test_fallback_on_tiktoken_failure(self):
        """When tiktoken raises, fall back to char/4 heuristic."""
        from llm_apipool.providers import dispatch as dispatch_mod

        messages = [
            {"role": "user", "content": "Hello, world!"},  # 13 chars → 3
            {"role": "user", "content": "Test message here"},  # 17 chars → 4
        ]
        expected = (13 // 4) + (17 // 4)  # 3 + 4 = 7

        with patch.object(
            dispatch_mod.tiktoken,
            "get_encoding",
            side_effect=Exception("tiktoken broken"),
        ):
            count = dispatch_mod._estimate_tokens(messages)

        assert count == expected

    def test_fallback_with_empty_messages(self):
        """Fallback handles empty message list."""
        from llm_apipool.providers import dispatch as dispatch_mod

        with patch.object(
            dispatch_mod.tiktoken,
            "get_encoding",
            side_effect=Exception("broken"),
        ):
            count = dispatch_mod._estimate_tokens([])

        assert count == 0

    def test_fallback_negative_char_count_returns_zero(self):
        """Messages with content shorter than 4 chars round to 0."""
        from llm_apipool.providers import dispatch as dispatch_mod

        messages = [{"role": "user", "content": "abc"}]  # 3 // 4 = 0

        with patch.object(
            dispatch_mod.tiktoken,
            "get_encoding",
            side_effect=Exception("broken"),
        ):
            count = dispatch_mod._estimate_tokens(messages)

        assert count == 0


# ---------------------------------------------------------------------------
# dispatch._make_chunk_id
# ---------------------------------------------------------------------------


class TestDispatchMakeChunkId:
    """dispatch._make_chunk_id — unique chunk ID generation."""

    def test_returns_chatcmpl_prefix(self):
        from llm_apipool.providers.dispatch import _make_chunk_id

        chunk_id = _make_chunk_id()
        assert chunk_id.startswith("chatcmpl-")

    def test_unique_ids(self):
        from llm_apipool.providers.dispatch import _make_chunk_id

        ids = {_make_chunk_id() for _ in range(100)}
        assert len(ids) == 100


# ---------------------------------------------------------------------------
# dispatch._error_generator
# ---------------------------------------------------------------------------


class TestDispatchErrorGenerator:
    """dispatch._error_generator — single error chunk generator."""

    @pytest.mark.asyncio
    async def test_yields_error_chunk(self):
        from llm_apipool.providers.dispatch import _error_generator

        gen = _error_generator("test_error", "test-model")
        chunks = [c async for c in gen]

        assert len(chunks) == 1
        chunk = chunks[0]
        assert chunk["object"] == "chat.completion.chunk"
        assert chunk["x_error"] == "test_error"
        assert chunk["model"] == "test-model"
        assert chunk["choices"] == []


# ---------------------------------------------------------------------------
# dispatch._stream_complete
# ---------------------------------------------------------------------------


class TestDispatchStreamComplete:
    """dispatch._stream_complete — streaming complete with no retry."""

    @pytest.mark.asyncio
    async def test_returns_generator_and_key_data(self):
        """Key found: returns (generator, key_data)."""
        from llm_apipool.providers import dispatch as dispatch_mod

        mock_rotator = MagicMock()
        key_data = {
            "key_id": "test-key",
            "provider": "groq",
            "model": "test-model",
            "api_key": "test-key",
            "base_url": "https://test.com/v1",
            "openai_compatible": True,
        }
        mock_rotator.get_best_key.return_value = key_data

        async def _fake_gen() -> AsyncGenerator[dict, None]:
            yield {"id": "chunk-1"}

        with patch(
            "llm_apipool.providers.dispatch.openai_compat.complete",
        ) as mock_complete:
            mock_complete.return_value = _fake_gen()

            gen, returned_key = await dispatch_mod._stream_complete(
                mock_rotator,
                ["general"],
                [{"role": "user", "content": "Hi"}],
                subscriber_id="test-sub",
            )

            assert returned_key == key_data
            chunks = [c async for c in gen]
            assert chunks == [{"id": "chunk-1"}]
            mock_complete.assert_called_once_with(
                key_data,
                [{"role": "user", "content": "Hi"}],
                stream=True,
            )
            mock_rotator.get_best_key.assert_called_once_with(
                ["general"],
                subscriber_id="test-sub",
                min_context=None,
                require_tools=None,
                require_vision=None,
                uid=None,
            )
            # Stream lifecycle: success registered on exhaustion
            mock_rotator.handle_success.assert_called_once()
            mock_rotator.handle_429.assert_not_called()

    @pytest.mark.asyncio
    async def test_stream_with_error_chunk_calls_handle_429(self):
        """Error chunk triggers handle_429, retry logic exhausts keys, returns all_keys_exhausted."""
        from llm_apipool.providers import dispatch as dispatch_mod

        mock_rotator = MagicMock()
        mock_rotator.store.get_all_keys.return_value = [
            {"key_id": 1, "is_active": True, "provider": "groq", "model": "test-model"},
        ]
        key_data = {
            "key_id": 1,
            "provider": "groq",
            "model": "test-model",
            "api_key": "test-key",
            "base_url": "https://test.com/v1",
            "openai_compatible": True,
        }
        mock_rotator.get_best_key.return_value = key_data

        async def _error_gen() -> AsyncGenerator[dict, None]:
            yield {"x_error": "Rate limited", "x_was_429": True}

        with patch(
            "llm_apipool.providers.dispatch.openai_compat.complete",
        ) as mock_complete:
            mock_complete.return_value = _error_gen()

            gen, returned_key = await dispatch_mod._stream_complete(
                mock_rotator,
                ["general"],
                [{"role": "user", "content": "Hi"}],
                subscriber_id="test-sub",
            )

            chunks = [c async for c in gen]
            assert len(chunks) == 1
            # Error chunk was absorbed by retry logic; no more keys to try
            assert "all_keys_exhausted" in chunks[0]["x_error"]
            # handle_429 was called for the failed key
            mock_rotator.handle_429.assert_called()
            mock_rotator.handle_success.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_keys_returns_error_generator(self):
        """No keys available: returns (error_generator, None)."""
        from llm_apipool.providers import dispatch as dispatch_mod

        mock_rotator = MagicMock()
        mock_rotator.get_best_key.return_value = None

        gen, key_data = await dispatch_mod._stream_complete(
            mock_rotator,
            ["general"],
            [],
            "test-sub",
        )

        assert key_data is None
        chunks = [c async for c in gen]
        assert len(chunks) == 1
        assert "all_keys_exhausted" in chunks[0].get("x_error", "")


# ---------------------------------------------------------------------------
# dispatch._call_complete
# ---------------------------------------------------------------------------


class TestDispatchCallComplete:
    """dispatch._call_complete — routing to correct provider."""

    # -- stream=True ------------------------------------------------------

    @pytest.mark.asyncio
    async def test_stream_openai_compatible(self):
        """stream=True, openai_compatible=True → openai_compat.complete."""
        from llm_apipool.providers import dispatch as dispatch_mod

        key_data = {
            "provider": "groq",
            "model": "test",
            "api_key": "key",
            "base_url": "https://test.com",
            "openai_compatible": True,
        }

        async def _gen():  # noqa: ANN202
            yield {"id": "c1"}

        with patch(
            "llm_apipool.providers.dispatch.openai_compat.complete",
        ) as mock_oc:
            mock_oc.return_value = _gen()
            result = await dispatch_mod._call_complete(
                key_data,
                [{"role": "user", "content": "Hi"}],
                stream=True,
            )

            chunks = [c async for c in result]
            assert chunks == [{"id": "c1"}]
            mock_oc.assert_called_once_with(
                key_data,
                [{"role": "user", "content": "Hi"}],
                stream=True,
            )

    @pytest.mark.asyncio
    async def test_stream_cohere(self):
        """stream=True, cohere provider → cohere.complete."""
        from llm_apipool.providers import dispatch as dispatch_mod

        key_data = {
            "provider": "cohere",
            "model": "command-r",
            "api_key": "co_key",
            "base_url": "https://api.cohere.com/v2",
            "openai_compatible": False,
        }

        async def _gen():  # noqa: ANN202
            yield {"id": "cohere-chunk"}

        with patch(
            "llm_apipool.providers.dispatch._cohere.complete",
        ) as mock_co:
            mock_co.return_value = _gen()
            result = await dispatch_mod._call_complete(
                key_data,
                [{"role": "user", "content": "Hi"}],
                stream=True,
            )

            chunks = [c async for c in result]
            assert chunks == [{"id": "cohere-chunk"}]
            mock_co.assert_called_once_with(
                key_data,
                [{"role": "user", "content": "Hi"}],
                stream=True,
            )

    @pytest.mark.asyncio
    async def test_stream_cloudflare(self):
        """stream=True, cloudflare provider → cloudflare.complete."""
        from llm_apipool.providers import dispatch as dispatch_mod

        key_data = {
            "provider": "cloudflare",
            "model": "@cf/meta/llama",
            "api_key": "cf_key",
            "base_url": "https://api.cloudflare.com/client/v4/accounts/x/ai/run",
            "openai_compatible": False,
        }

        async def _gen():  # noqa: ANN202
            yield {"id": "cf-chunk"}

        with patch(
            "llm_apipool.providers.dispatch._cloudflare.complete",
        ) as mock_cf:
            mock_cf.return_value = _gen()
            result = await dispatch_mod._call_complete(
                key_data,
                [{"role": "user", "content": "Hi"}],
                stream=True,
            )

            chunks = [c async for c in result]
            assert chunks == [{"id": "cf-chunk"}]
            mock_cf.assert_called_once_with(
                key_data,
                [{"role": "user", "content": "Hi"}],
                stream=True,
            )

    @pytest.mark.asyncio
    async def test_stream_unknown_provider(self):
        """stream=True, unknown provider → error_generator."""
        from llm_apipool.providers import dispatch as dispatch_mod

        key_data = {
            "provider": "unknown_provider",
            "model": "some-model",
            "api_key": "",
            "base_url": "",
            "openai_compatible": False,
        }

        result = await dispatch_mod._call_complete(
            key_data,
            [{"role": "user", "content": "Hi"}],
            stream=True,
        )

        chunks = [c async for c in result]
        assert len(chunks) == 1
        assert "no client" in chunks[0]["x_error"]

    # -- stream=False -----------------------------------------------------

    @pytest.mark.asyncio
    async def test_non_stream_openai_compatible(self):
        """stream=False, openai_compatible=True → openai_compat.complete."""
        from llm_apipool.providers import dispatch as dispatch_mod

        key_data = {
            "provider": "groq",
            "model": "test",
            "api_key": "key",
            "base_url": "https://test.com",
            "openai_compatible": True,
        }

        with patch(
            "llm_apipool.providers.dispatch.openai_compat.complete",
        ) as mock_oc:
            mock_oc.return_value = CompletionResult(
                text="Hello",
                tokens_used=5,
                was_429=False,
            )
            result = await dispatch_mod._call_complete(
                key_data,
                [{"role": "user", "content": "Hi"}],
            )

            assert isinstance(result, CompletionResult)
            assert result.text == "Hello"
            mock_oc.assert_called_once_with(
                key_data,
                [{"role": "user", "content": "Hi"}],
            )

    @pytest.mark.asyncio
    async def test_non_stream_cohere(self):
        """stream=False, cohere provider → cohere.complete."""
        from llm_apipool.providers import dispatch as dispatch_mod

        key_data = {
            "provider": "cohere",
            "model": "command-r",
            "api_key": "co_key",
            "base_url": "https://api.cohere.com/v2",
            "openai_compatible": False,
        }

        with patch(
            "llm_apipool.providers.dispatch._cohere.complete",
        ) as mock_co:
            mock_co.return_value = CompletionResult(
                text="Cohere reply",
                tokens_used=10,
                was_429=False,
            )
            result = await dispatch_mod._call_complete(
                key_data,
                [{"role": "user", "content": "Hi"}],
            )

            assert result.text == "Cohere reply"
            mock_co.assert_called_once()

    @pytest.mark.asyncio
    async def test_non_stream_cloudflare(self):
        """stream=False, cloudflare provider → cloudflare.complete."""
        from llm_apipool.providers import dispatch as dispatch_mod

        key_data = {
            "provider": "cloudflare",
            "model": "@cf/meta/llama",
            "api_key": "cf_key",
            "base_url": "https://api.cloudflare.com/...",
            "openai_compatible": False,
        }

        with patch(
            "llm_apipool.providers.dispatch._cloudflare.complete",
        ) as mock_cf:
            mock_cf.return_value = CompletionResult(
                text="CF reply",
                tokens_used=0,
                was_429=False,
            )
            result = await dispatch_mod._call_complete(
                key_data,
                [{"role": "user", "content": "Hi"}],
            )

            assert result.text == "CF reply"
            mock_cf.assert_called_once()

    @pytest.mark.asyncio
    async def test_non_stream_unknown_provider(self):
        """stream=False, unknown provider → CompletionResult with error."""
        from llm_apipool.providers import dispatch as dispatch_mod

        key_data = {
            "provider": "unknown_provider",
            "model": "some-model",
            "api_key": "",
            "base_url": "",
            "openai_compatible": False,
        }

        result = await dispatch_mod._call_complete(
            key_data,
            [{"role": "user", "content": "Hi"}],
        )

        assert isinstance(result, CompletionResult)
        assert "no client" in (result.error or "")
        assert result.was_429 is False


# ---------------------------------------------------------------------------
# dispatch.complete (stream=True)
# ---------------------------------------------------------------------------


class TestDispatchCompleteStream:
    """dispatch.complete with stream=True."""

    @pytest.mark.asyncio
    async def test_stream_complete_routing(self):
        """stream=True: calls _stream_complete, returns (generator, key_data)."""
        from llm_apipool.providers import dispatch as dispatch_mod

        mock_rotator = MagicMock()
        key_data = {
            "key_id": "test-key",
            "provider": "groq",
            "model": "test",
            "api_key": "key",
            "base_url": "https://test.com",
            "openai_compatible": True,
        }
        mock_rotator.get_best_key.return_value = key_data

        async def _fake_gen():
            yield {"id": "stream-chunk"}

        with patch(
            "llm_apipool.providers.dispatch.openai_compat.complete",
        ) as mock_oc:
            mock_oc.return_value = _fake_gen()

            gen, returned_key = await dispatch_mod.complete(
                mock_rotator,
                capabilities=["general"],
                messages=[{"role": "user", "content": "Hi"}],
                subscriber_id="test-sub",
                stream=True,
            )

            assert returned_key == key_data
            chunks = [c async for c in gen]
            assert chunks == [{"id": "stream-chunk"}]
            # Stream lifecycle: success registered on exhaustion
            mock_rotator.handle_success.assert_called_once()

    @pytest.mark.asyncio
    async def test_stream_no_keys(self):
        """stream=True, no keys available → error_generator."""
        from llm_apipool.providers import dispatch as dispatch_mod

        mock_rotator = MagicMock()
        mock_rotator.get_best_key.return_value = None

        gen, key_data = await dispatch_mod.complete(
            mock_rotator,
            capabilities=["general"],
            messages=[{"role": "user", "content": "Hi"}],
            subscriber_id="test-sub",
            stream=True,
        )

        assert key_data is None
        chunks = [c async for c in gen]
        assert len(chunks) == 1
        assert "all_keys_exhausted" in chunks[0].get("x_error", "")


# ---------------------------------------------------------------------------
# dispatch.complete (non-streaming — retry loop)
# ---------------------------------------------------------------------------


class TestDispatchCompleteNonStream:
    """dispatch.complete non-streaming retry loop."""

    KEY_DATA = {
        "key_id": "test-key",
        "provider": "groq",
        "model": "test-model",
        "api_key": "gsk_test123",
        "base_url": "https://api.groq.com/openai/v1",
        "openai_compatible": True,
    }

    @pytest.mark.asyncio
    async def test_all_keys_exhausted(self):
        """get_best_key returns None → all_keys_exhausted."""
        from llm_apipool.providers import dispatch as dispatch_mod

        mock_rotator = MagicMock()
        mock_rotator.get_best_key.return_value = None

        result, key_data = await dispatch_mod.complete(
            mock_rotator,
            capabilities=[],
            messages=[],
        )

        assert result.error == "all_keys_exhausted"
        assert key_data is None

    @pytest.mark.asyncio
    async def test_success_flow(self):
        """First attempt succeeds → returns result and key_data."""
        from llm_apipool.providers import dispatch as dispatch_mod

        mock_rotator = MagicMock()
        mock_rotator.get_best_key.return_value = self.KEY_DATA

        with patch(
            "llm_apipool.providers.dispatch.openai_compat.complete",
        ) as mock_oc:
            mock_oc.return_value = CompletionResult(
                text="Success!",
                tokens_used=42,
                was_429=False,
                rate_limit_headers={"x-ratelimit-remaining": "10"},
            )

            result, key_data = await dispatch_mod.complete(
                mock_rotator,
                capabilities=["general"],
                messages=[{"role": "user", "content": "Hello"}],
            )

            assert result.text == "Success!"
            assert result.tokens_used == 42
            assert key_data == self.KEY_DATA
            # handle_success should have been called
            mock_rotator.handle_success.assert_called_once()
            # handle_429 should NOT have been called
            mock_rotator.handle_429.assert_not_called()

    @pytest.mark.asyncio
    async def test_max_retries_exceeded(self):
        """All attempts return 429 → max_retries_exceeded after dynamic retries."""
        from llm_apipool.providers import dispatch as dispatch_mod

        mock_rotator = MagicMock()
        mock_rotator.get_best_key.return_value = self.KEY_DATA
        # Provide store mock for _max_attempts_for calculation
        mock_store = MagicMock()
        mock_store.get_all_keys.return_value = [
            {"is_active": True},
        ]
        mock_rotator.store = mock_store

        with (
            patch(
                "llm_apipool.providers.dispatch.openai_compat.complete",
            ) as mock_oc,
            patch(
                "llm_apipool.providers.dispatch.asyncio.sleep",
                AsyncMock(),
            ),
        ):
            mock_oc.return_value = CompletionResult(
                text="",
                tokens_used=0,
                was_429=True,
                rate_limit_headers={"retry-after": "60"},
            )

            result, key_data = await dispatch_mod.complete(
                mock_rotator,
                capabilities=["general"],
                messages=[{"role": "user", "content": "Hello"}],
            )

            assert result.error == "max_retries_exceeded"
            assert key_data is None
            # handle_429 was called at least once (key exhausted from retries)
            assert mock_rotator.handle_429.call_count >= 1

    @pytest.mark.asyncio
    async def test_retry_then_succeed(self):
        """Fail with 429 twice, then succeed on third attempt."""
        from llm_apipool.providers import dispatch as dispatch_mod

        mock_rotator = MagicMock()
        mock_rotator.get_best_key.return_value = self.KEY_DATA

        with (
            patch(
                "llm_apipool.providers.dispatch.openai_compat.complete",
            ) as mock_oc,
            patch(
                "llm_apipool.providers.dispatch.asyncio.sleep",
                AsyncMock(),
            ),
        ):
            # First two returns are 429, third succeeds
            mock_oc.side_effect = [
                CompletionResult(text="", tokens_used=0, was_429=True),
                CompletionResult(text="", tokens_used=0, was_429=True),
                CompletionResult(
                    text="Retry worked!",
                    tokens_used=5,
                    was_429=False,
                ),
            ]

            result, key_data = await dispatch_mod.complete(
                mock_rotator,
                capabilities=["general"],
                messages=[{"role": "user", "content": "Hello"}],
            )

            assert result.text == "Retry worked!"
            assert key_data == self.KEY_DATA
            assert mock_rotator.handle_429.call_count == 2
            mock_rotator.handle_success.assert_called_once()
