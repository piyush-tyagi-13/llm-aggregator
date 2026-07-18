"""Tests for provider modules - openai_compat, cohere, cloudflare."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from llm_apipool.providers import cloudflare as _cloudflare
from llm_apipool.providers import cohere as _cohere
from llm_apipool.providers import openai_compat
from llm_apipool.providers.base import CompletionResult
from llm_apipool.providers.dispatch import _estimate_tokens, _mask_key

# ---------------------------------------------------------------------------
# _mask_key  (dispatch-level helper)
# ---------------------------------------------------------------------------


class TestDispatchMaskKey:
    """dispatch._mask_key — safe API-key masking for logs."""

    def test_normal(self):
        assert _mask_key("sk-abc12345def67890") == "sk-a****7890"

    def test_short(self):
        assert _mask_key("abc12345") == "****2345"

    def test_very_short(self):
        assert _mask_key("abc") == "****"

    def test_empty(self):
        assert _mask_key("") == "****"

    def test_exactly_eight(self):
        assert _mask_key("12345678") == "****5678"


# ---------------------------------------------------------------------------
# _estimate_tokens
# ---------------------------------------------------------------------------


class TestEstimateTokens:
    """dispatch._estimate_tokens — token estimation using tiktoken."""

    def test_empty_messages(self):
        assert _estimate_tokens([]) == 0

    def test_simple_message(self):
        messages = [{"role": "user", "content": "Hello, world!"}]
        count = _estimate_tokens(messages)
        assert count > 0
        assert count < 20  # "Hello, world!" is ~3-4 tokens with cl100k_base

    def test_multiple_messages(self):
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Tell me a story about Python."},
        ]
        count = _estimate_tokens(messages)
        assert count > 0

    def test_content_with_list_parts(self):
        """Handle multimodal content that is a list of parts."""
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What is in this image?"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,..."},
                    },
                ],
            },
        ]
        count = _estimate_tokens(messages)
        assert count > 0

    def test_fallback_on_tiktoken_failure(self, monkeypatch: pytest.MonkeyPatch):
        """When tiktoken unavailable, fall back to char/4 heuristic."""
        from unittest import mock
        import tiktoken
        import llm_apipool.providers.dispatch as dispatch_mod
        # Mock tiktoken.get_encoding to raise so the fallback path runs
        monkeypatch.setattr(
            tiktoken, "encoding_for_model", mock.Mock(side_effect=Exception("tiktoken failed"))
        )
        monkeypatch.setattr(
            tiktoken, "get_encoding", mock.Mock(side_effect=Exception("tiktoken failed"))
        )
        # Clear any cached encoding
        dispatch_mod._encoding_cache = {}
        messages = [{"role": "user", "content": "Hello, world!"}]
        count = dispatch_mod._estimate_tokens(messages)
        expected = sum(len(m.get("content", "")) // 4 for m in messages)
        assert count == expected


# ---------------------------------------------------------------------------
# openai_compat.complete
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


@pytest.fixture(autouse=True)
def _clear_openai_cache() -> None:
    """Clear the client cache and connection pool for test isolation."""
    openai_compat._clear_client_cache()
    pool = openai_compat.get_connection_pool()
    pool._pools.clear()
    pool._health_trackers.clear()
    pool._heartbeat_tasks.clear()
    pool._active.clear()


class TestOpenaiCompat:
    """openai_compat.complete — OpenAI-compatible provider calls."""

    @pytest.mark.asyncio
    @patch("llm_apipool.providers.openai_compat._get_client_pooled")
    @patch("llm_apipool.providers.openai_compat.AsyncOpenAI")
    async def test_success(
        self, mock_openai: MagicMock, mock_get_client: MagicMock, key_data: dict
    ):
        """Successful response returns CompletionResult with content and tokens."""
        mock_client = MagicMock()
        mock_raw = MagicMock()
        mock_raw.headers = {"x-ratelimit-remaining-requests": "10"}
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = "Hello from AI!"
        mock_resp.usage.total_tokens = 42
        mock_client.chat.completions.with_raw_response.create = AsyncMock(
            return_value=mock_raw,
        )
        mock_raw.parse = MagicMock(return_value=mock_resp)
        mock_openai.return_value = mock_client
        mock_get_client.return_value = mock_client

        result = await openai_compat.complete(
            key_data,
            [{"role": "user", "content": "Hi"}],
        )

        assert isinstance(result, CompletionResult)
        assert result.text == "Hello from AI!"
        assert result.tokens_used == 42
        assert result.was_429 is False
        assert result.error is None

    @pytest.mark.asyncio
    @patch("llm_apipool.providers.openai_compat._get_client_pooled")
    @patch("llm_apipool.providers.openai_compat.AsyncOpenAI")
    async def test_rate_limit(
        self, mock_openai: MagicMock, mock_get_client: MagicMock, key_data: dict
    ):
        """RateLimitError sets was_429=True and includes error message."""
        from openai import RateLimitError

        mock_client = MagicMock()
        mock_client.chat.completions.with_raw_response.create = AsyncMock(
            side_effect=RateLimitError(
                message="Rate limited",
                response=MagicMock(status_code=429, headers={"retry-after": "60"}),
                body={},
            ),
        )
        mock_openai.return_value = mock_client
        mock_get_client.return_value = mock_client

        result = await openai_compat.complete(
            key_data,
            [{"role": "user", "content": "Hi"}],
        )

        assert result.was_429 is True
        assert "429" in (result.error or "")

    @pytest.mark.asyncio
    @patch("llm_apipool.providers.openai_compat._get_client_pooled")
    @patch("llm_apipool.providers.openai_compat.AsyncOpenAI")
    async def test_api_status_error(
        self, mock_openai: MagicMock, mock_get_client: MagicMock, key_data: dict
    ):
        """Non-429 API errors return was_429=False with descriptive error."""
        from openai import APIStatusError

        mock_client = MagicMock()
        mock_client.chat.completions.with_raw_response.create = AsyncMock(
            side_effect=APIStatusError(
                message="Bad Request",
                response=MagicMock(status_code=400),
                body={},
            ),
        )
        mock_openai.return_value = mock_client
        mock_get_client.return_value = mock_client

        result = await openai_compat.complete(
            key_data,
            [{"role": "user", "content": "Hi"}],
        )

        assert result.was_429 is False
        assert "HTTP 400" in (result.error or "")

    @pytest.mark.asyncio
    @patch("llm_apipool.providers.openai_compat._get_client_pooled")
    @patch("llm_apipool.providers.openai_compat.AsyncOpenAI")
    async def test_timeout(
        self, mock_openai: MagicMock, mock_get_client: MagicMock, key_data: dict
    ):
        """httpx.TimeoutException is caught and reported."""
        mock_client = MagicMock()
        mock_client.chat.completions.with_raw_response.create = AsyncMock(
            side_effect=httpx.TimeoutException("Connection timed out"),
        )
        mock_openai.return_value = mock_client
        mock_get_client.return_value = mock_client

        result = await openai_compat.complete(
            key_data,
            [{"role": "user", "content": "Hi"}],
        )

        assert result.was_429 is False
        assert "timed out" in (result.error or "").lower()

    @pytest.mark.asyncio
    @patch("llm_apipool.providers.openai_compat._get_client_pooled")
    @patch("llm_apipool.providers.openai_compat.AsyncOpenAI")
    async def test_network_error(
        self, mock_openai: MagicMock, mock_get_client: MagicMock, key_data: dict
    ):
        """httpx.NetworkError is caught and reported."""
        mock_client = MagicMock()
        mock_client.chat.completions.with_raw_response.create = AsyncMock(
            side_effect=httpx.NetworkError("DNS resolution failed"),
        )
        mock_openai.return_value = mock_client
        mock_get_client.return_value = mock_client

        result = await openai_compat.complete(
            key_data,
            [{"role": "user", "content": "Hi"}],
        )

        assert result.was_429 is False
        assert (
            "network" in (result.error or "").lower()
            or "request error" in (result.error or "").lower()
        )

    @pytest.mark.asyncio
    @patch("llm_apipool.providers.openai_compat._get_client_pooled")
    @patch("llm_apipool.providers.openai_compat.AsyncOpenAI")
    async def test_empty_api_key(
        self, mock_openai: MagicMock, mock_get_client: MagicMock, key_data: dict
    ):
        """Keyless providers work with empty (or missing) api_key."""
        key_data["api_key"] = ""
        mock_client = MagicMock()
        mock_raw = MagicMock()
        mock_raw.headers = {}
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = "Response from keyless provider"
        mock_resp.usage.total_tokens = 10
        mock_client.chat.completions.with_raw_response.create = AsyncMock(
            return_value=mock_raw,
        )
        mock_raw.parse = MagicMock(return_value=mock_resp)
        mock_openai.return_value = mock_client
        mock_get_client.return_value = mock_client

        result = await openai_compat.complete(
            key_data,
            [{"role": "user", "content": "Hi"}],
        )

        assert result.text == "Response from keyless provider"
        assert result.was_429 is False

    @pytest.mark.asyncio
    @patch("llm_apipool.providers.openai_compat._get_client_pooled")
    @patch("llm_apipool.providers.openai_compat.AsyncOpenAI")
    async def test_strip_thinking(
        self, mock_openai: MagicMock, mock_get_client: MagicMock, key_data: dict
    ):
        """<think>...</think> blocks are stripped from the response."""
        mock_client = MagicMock()
        mock_raw = MagicMock()
        mock_raw.headers = {}
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[
            0
        ].message.content = (
            "<think>Let me reason step by step...</think>\nThe answer is 42."
        )
        mock_resp.usage.total_tokens = 20
        mock_client.chat.completions.with_raw_response.create = AsyncMock(
            return_value=mock_raw,
        )
        mock_raw.parse = MagicMock(return_value=mock_resp)
        mock_openai.return_value = mock_client
        mock_get_client.return_value = mock_client

        result = await openai_compat.complete(
            key_data,
            [{"role": "user", "content": "Think step by step"}],
        )

        assert "<think>" not in result.text
        assert result.text.startswith("The answer is 42.")

    @pytest.mark.asyncio
    @patch("llm_apipool.providers.openai_compat._get_client_pooled")
    @patch("llm_apipool.providers.openai_compat.AsyncOpenAI")
    async def test_unexpected_error(
        self, mock_openai: MagicMock, mock_get_client: MagicMock, key_data: dict
    ):
        """Any unexpected exception is caught and returned as error string."""
        mock_client = MagicMock()
        mock_client.chat.completions.with_raw_response.create = AsyncMock(
            side_effect=ValueError("something unexpected"),
        )
        mock_openai.return_value = mock_client
        mock_get_client.return_value = mock_client

        result = await openai_compat.complete(
            key_data,
            [{"role": "user", "content": "Hi"}],
        )

        assert result.was_429 is False
        assert "Unexpected error" in (result.error or "")


# ---------------------------------------------------------------------------
# cohere.complete
# ---------------------------------------------------------------------------


class TestCohere:
    """cohere.complete — Cohere native API client."""

    KEY_DATA: dict = {
        "provider": "cohere",
        "model": "command-r-plus-08-2024",
        "api_key": "co_test",
        "base_url": "https://api.cohere.com/v2",
    }

    @pytest.mark.asyncio
    @patch("llm_apipool.providers.cohere.httpx.AsyncClient")
    async def test_success(self, mock_client_class: MagicMock):
        """Successful Cohere response returns CompletionResult with text and tokens."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.json.return_value = {
            "message": {"content": [{"text": "Hello from Cohere!"}]},
            "usage": {"tokens": {"input_tokens": 10, "output_tokens": 20}},
        }
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post = AsyncMock(return_value=mock_response)

        result = await _cohere.complete(
            self.KEY_DATA,
            [{"role": "user", "content": "Hi"}],
        )

        assert result.text == "Hello from Cohere!"
        assert result.tokens_used == 30
        assert result.was_429 is False

    @pytest.mark.asyncio
    @patch("llm_apipool.providers.cohere.httpx.AsyncClient")
    async def test_rate_limit_429(self, mock_client_class: MagicMock):
        """429 response sets was_429=True."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {}
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post = AsyncMock(return_value=mock_response)

        result = await _cohere.complete(
            self.KEY_DATA,
            [{"role": "user", "content": "Hi"}],
        )

        assert result.was_429 is True
        assert "429" in (result.error or "")

    @pytest.mark.asyncio
    @patch("llm_apipool.providers.cohere.httpx.AsyncClient")
    async def test_http_error(self, mock_client_class: MagicMock):
        """Non-429 HTTP errors are captured without setting was_429."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 400
        # Setting raise_for_status to raise httpx.HTTPStatusError
        from httpx import HTTPStatusError, Request, Response

        mock_response.raise_for_status.side_effect = HTTPStatusError(
            "Bad Request",
            request=Request("POST", "https://api.cohere.com/v2/chat"),
            response=Response(status_code=400),
        )
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post = AsyncMock(return_value=mock_response)

        result = await _cohere.complete(
            {
                "provider": "cohere",
                "model": "command",
                "api_key": "co_test",
                "base_url": "https://api.cohere.com/v2",
            },
            [{"role": "user", "content": "Hi"}],
        )

        assert result.was_429 is False
        assert "HTTP 400" in (result.error or "")

    @pytest.mark.asyncio
    @patch("llm_apipool.providers.cohere.httpx.AsyncClient")
    async def test_timeout(self, mock_client_class: MagicMock):
        """httpx.TimeoutException is caught and reported."""
        mock_client = MagicMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post = AsyncMock(
            side_effect=httpx.TimeoutException("Connection timed out"),
        )

        result = await _cohere.complete(
            {
                "provider": "cohere",
                "model": "command",
                "api_key": "co_test",
                "base_url": "https://api.cohere.com/v2",
            },
            [{"role": "user", "content": "Hi"}],
        )

        assert result.was_429 is False
        assert "timed out" in (result.error or "").lower()

    @pytest.mark.asyncio
    @patch("llm_apipool.providers.cohere.httpx.AsyncClient")
    async def test_network_error(self, mock_client_class: MagicMock):
        """httpx.NetworkError is caught and reported."""
        mock_client = MagicMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post = AsyncMock(
            side_effect=httpx.NetworkError("DNS resolution failed"),
        )

        result = await _cohere.complete(
            {
                "provider": "cohere",
                "model": "command",
                "api_key": "co_test",
                "base_url": "https://api.cohere.com/v2",
            },
            [{"role": "user", "content": "Hi"}],
        )

        assert result.was_429 is False
        assert (
            "request error" in (result.error or "").lower()
            or "network" in (result.error or "").lower()
        )

    @pytest.mark.asyncio
    @patch("llm_apipool.providers.cohere.httpx.AsyncClient")
    async def test_unexpected_error(self, mock_client_class: MagicMock):
        """Any unexpected exception is caught and returned as error string."""
        mock_client = MagicMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post = AsyncMock(
            side_effect=RuntimeError("unexpected failure"),
        )

        result = await _cohere.complete(
            {
                "provider": "cohere",
                "model": "command",
                "api_key": "co_test",
                "base_url": "https://api.cohere.com/v2",
            },
            [{"role": "user", "content": "Hi"}],
        )

        assert result.was_429 is False
        assert "Unexpected Cohere error" in (result.error or "")

    # -- Cohere streaming tests (covers lines 17, 31-52, 65-96, 114) --

    @pytest.mark.asyncio
    @patch("llm_apipool.providers.cohere.httpx.AsyncClient")
    async def test_stream_success(self, mock_client_class: MagicMock):
        """Cohere streaming path yields SSE content chunks then finish."""

        async def _sse_lines():
            yield 'data: {"event_type": "text-generation", "text": "Hello from Cohere stream!"}'
            yield 'data: {"event_type": "stream-end", "finish_reason": "COMPLETE", "response": {"meta": {"billed_units": {"input_tokens": 10, "output_tokens": 20}}}}'

        mock_client = MagicMock()
        mock_stream_resp = MagicMock()
        mock_stream_resp.status_code = 200
        mock_stream_resp.headers = {}
        mock_stream_resp.aiter_lines = _sse_lines
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_stream_ctx = MagicMock()
        mock_stream_ctx.__aenter__.return_value = mock_stream_resp
        mock_client.stream = MagicMock(return_value=mock_stream_ctx)

        gen = await _cohere.complete(
            {
                "provider": "cohere",
                "model": "command",
                "api_key": "co_test",
                "base_url": "https://api.cohere.com/v2",
            },
            [{"role": "user", "content": "Hi"}],
            stream=True,
        )
        chunks = [c async for c in gen]
        assert len(chunks) == 2
        assert (
            chunks[0]["choices"][0]["delta"]["content"] == "Hello from Cohere stream!"
        )
        assert chunks[1]["choices"][0]["finish_reason"] == "stop"
        assert chunks[1].get("x_tokens_used") == 30

    @pytest.mark.asyncio
    @patch("llm_apipool.providers.cohere.httpx.AsyncClient")
    async def test_stream_error(self, mock_client_class: MagicMock):
        """Cohere streaming path with 429 yields error chunk."""

        async def _no_lines():
            if False:  # noqa: FURB129
                yield ""  # pragma: no cover

        mock_client = MagicMock()
        mock_stream_resp = MagicMock()
        mock_stream_resp.status_code = 429
        mock_stream_resp.headers = {}
        mock_stream_resp.aiter_lines = _no_lines
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_stream_ctx = MagicMock()
        mock_stream_ctx.__aenter__.return_value = mock_stream_resp
        mock_client.stream = MagicMock(return_value=mock_stream_ctx)

        gen = await _cohere.complete(
            {
                "provider": "cohere",
                "model": "command",
                "api_key": "co_test",
                "base_url": "https://api.cohere.com/v2",
            },
            [{"role": "user", "content": "Hi"}],
            stream=True,
        )
        chunks = [c async for c in gen]
        assert len(chunks) == 1
        assert chunks[0].get("x_error") is not None
        assert chunks[0].get("x_was_429") is True

    @pytest.mark.asyncio
    async def test_cohere_build_chunk_variants(self):
        """Direct tests for cohere _build_chunk helper."""
        chunk = _cohere._build_chunk("cid1", 100, "m1")
        assert chunk["id"] == "cid1"
        assert chunk["choices"] == []

        chunk2 = _cohere._build_chunk(
            "cid2", 200, "m2", delta_content="hi", delta_role="assistant"
        )
        assert chunk2["choices"][0]["delta"] == {"role": "assistant", "content": "hi"}

        chunk3 = _cohere._build_chunk(
            "cid3", 300, "m3", finish_reason="stop", x_tokens=99
        )
        assert chunk3["choices"][0]["finish_reason"] == "stop"
        assert chunk3["x_tokens"] == 99

    @pytest.mark.asyncio
    async def test_cohere_make_chunk_id(self):
        """cohere _make_chunk_id returns unique IDs with correct prefix."""
        cid = _cohere._make_chunk_id()
        assert cid.startswith("chatcmpl-")


# ---------------------------------------------------------------------------
# cloudflare.complete
# ---------------------------------------------------------------------------


class TestCloudflare:
    """cloudflare.complete — Cloudflare Workers AI client."""

    KEY_DATA: dict = {
        "provider": "cloudflare",
        "model": "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
        "api_key": "cf_key",
        "base_url": "https://api.cloudflare.com/client/v4/accounts/test123/ai/run",
    }

    @pytest.mark.asyncio
    @patch("llm_apipool.providers.cloudflare.httpx.AsyncClient")
    async def test_success(self, mock_client_class: MagicMock):
        """Successful Cloudflare response returns CompletionResult with text."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.json.return_value = {
            "result": {"response": "Hello from Cloudflare!"},
        }
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post = AsyncMock(return_value=mock_response)

        result = await _cloudflare.complete(
            self.KEY_DATA,
            [{"role": "user", "content": "Hi"}],
        )

        assert result.text == "Hello from Cloudflare!"
        assert result.was_429 is False

    @pytest.mark.asyncio
    @patch("llm_apipool.providers.cloudflare.httpx.AsyncClient")
    async def test_rate_limit_429(self, mock_client_class: MagicMock):
        """429 response sets was_429=True."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {}
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post = AsyncMock(return_value=mock_response)

        result = await _cloudflare.complete(
            {
                "provider": "cloudflare",
                "model": "@cf/meta/llama-3.1-8b-instruct",
                "api_key": "cf_key",
                "base_url": "https://api.cloudflare.com/client/v4/accounts/test123/ai/run",
            },
            [{"role": "user", "content": "Hi"}],
        )

        assert result.was_429 is True
        assert "429" in (result.error or "")

    @pytest.mark.asyncio
    @patch("llm_apipool.providers.cloudflare.httpx.AsyncClient")
    async def test_http_error(self, mock_client_class: MagicMock):
        """Non-429 HTTP errors are captured without setting was_429."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 400
        from httpx import HTTPStatusError, Request, Response

        mock_response.raise_for_status.side_effect = HTTPStatusError(
            "Bad Request",
            request=Request("POST", "https://api.cloudflare.com/..."),
            response=Response(status_code=400),
        )
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post = AsyncMock(return_value=mock_response)

        result = await _cloudflare.complete(
            {
                "provider": "cloudflare",
                "model": "@cf/meta/llama-3.1-8b-instruct",
                "api_key": "cf_key",
                "base_url": "https://api.cloudflare.com/client/v4/accounts/test123/ai/run",
            },
            [{"role": "user", "content": "Hi"}],
        )

        assert result.was_429 is False
        assert "HTTP 400" in (result.error or "")

    @pytest.mark.asyncio
    @patch("llm_apipool.providers.cloudflare.httpx.AsyncClient")
    async def test_timeout(self, mock_client_class: MagicMock):
        """httpx.TimeoutException is caught and reported."""
        mock_client = MagicMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post = AsyncMock(
            side_effect=httpx.TimeoutException("Connection timed out"),
        )

        result = await _cloudflare.complete(
            {
                "provider": "cloudflare",
                "model": "@cf/meta/llama-3.1-8b-instruct",
                "api_key": "cf_key",
                "base_url": "https://api.cloudflare.com/client/v4/accounts/test123/ai/run",
            },
            [{"role": "user", "content": "Hi"}],
        )

        assert result.was_429 is False
        assert "timed out" in (result.error or "").lower()

    @pytest.mark.asyncio
    @patch("llm_apipool.providers.cloudflare.httpx.AsyncClient")
    async def test_network_error(self, mock_client_class: MagicMock):
        """httpx.NetworkError is caught and reported."""
        mock_client = MagicMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post = AsyncMock(
            side_effect=httpx.NetworkError("DNS resolution failed"),
        )

        result = await _cloudflare.complete(
            {
                "provider": "cloudflare",
                "model": "@cf/meta/llama-3.1-8b-instruct",
                "api_key": "cf_key",
                "base_url": "https://api.cloudflare.com/client/v4/accounts/test123/ai/run",
            },
            [{"role": "user", "content": "Hi"}],
        )

        assert result.was_429 is False
        assert (
            "request error" in (result.error or "").lower()
            or "network" in (result.error or "").lower()
        )

    @pytest.mark.asyncio
    @patch("llm_apipool.providers.cloudflare.httpx.AsyncClient")
    async def test_unexpected_error(self, mock_client_class: MagicMock):
        """Any unexpected exception is caught and returned as error string."""
        mock_client = MagicMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post = AsyncMock(
            side_effect=RuntimeError("unexpected failure"),
        )

        result = await _cloudflare.complete(
            {
                "provider": "cloudflare",
                "model": "@cf/meta/llama-3.1-8b-instruct",
                "api_key": "cf_key",
                "base_url": "https://api.cloudflare.com/client/v4/accounts/test123/ai/run",
            },
            [{"role": "user", "content": "Hi"}],
        )

        assert result.was_429 is False
        assert "Unexpected Cloudflare error" in (result.error or "")

    # -- Cloudflare streaming tests --

    @pytest.mark.asyncio
    @patch("llm_apipool.providers.cloudflare.httpx.AsyncClient")
    async def test_stream_success(self, mock_client_class: MagicMock):
        """Streaming path yields SSE content chunks then finish."""

        async def _sse_lines():
            yield 'data: {"response": "Hello streaming!"}'
            yield "data: [DONE]"

        mock_client = MagicMock()
        mock_stream_resp = MagicMock()
        mock_stream_resp.status_code = 200
        mock_stream_resp.headers = {}
        mock_stream_resp.aiter_lines = _sse_lines
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_stream_ctx = MagicMock()
        mock_stream_ctx.__aenter__.return_value = mock_stream_resp
        mock_client.stream = MagicMock(return_value=mock_stream_ctx)

        gen = await _cloudflare.complete(
            self.KEY_DATA,
            [{"role": "user", "content": "Hi"}],
            stream=True,
        )
        chunks = [c async for c in gen]
        assert len(chunks) == 2
        assert chunks[0]["choices"][0]["delta"]["content"] == "Hello streaming!"
        assert chunks[0]["choices"][0]["delta"]["role"] == "assistant"
        assert chunks[1]["choices"][0]["finish_reason"] == "stop"

    @pytest.mark.asyncio
    @patch("llm_apipool.providers.cloudflare.httpx.AsyncClient")
    async def test_stream_error(self, mock_client_class: MagicMock):
        """Streaming path with 429 yields a single error chunk."""

        async def _no_lines():
            if False:  # noqa: FURB129
                yield ""  # pragma: no cover

        mock_client = MagicMock()
        mock_stream_resp = MagicMock()
        mock_stream_resp.status_code = 429
        mock_stream_resp.headers = {}
        mock_stream_resp.aiter_lines = _no_lines
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_stream_ctx = MagicMock()
        mock_stream_ctx.__aenter__.return_value = mock_stream_resp
        mock_client.stream = MagicMock(return_value=mock_stream_ctx)

        gen = await _cloudflare.complete(
            self.KEY_DATA,
            [{"role": "user", "content": "Hi"}],
            stream=True,
        )
        chunks = [c async for c in gen]
        assert len(chunks) == 1
        assert chunks[0].get("x_error") is not None
        assert chunks[0].get("x_was_429") is True

    @pytest.mark.asyncio
    @patch("llm_apipool.providers.cloudflare.httpx.AsyncClient")
    async def test_stream_empty_text(self, mock_client_class: MagicMock):
        """Streaming path with empty SSE response yields empty stream."""

        async def _sse_empty():
            yield 'data: {"response": ""}'
            yield "data: [DONE]"

        mock_client = MagicMock()
        mock_stream_resp = MagicMock()
        mock_stream_resp.status_code = 200
        mock_stream_resp.headers = {}
        mock_stream_resp.aiter_lines = _sse_empty
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_stream_ctx = MagicMock()
        mock_stream_ctx.__aenter__.return_value = mock_stream_resp
        mock_client.stream = MagicMock(return_value=mock_stream_ctx)

        gen = await _cloudflare.complete(
            self.KEY_DATA,
            [{"role": "user", "content": "Hi"}],
            stream=True,
        )
        chunks = [c async for c in gen]
        assert len(chunks) == 1
        assert chunks[0]["choices"][0]["finish_reason"] == "stop"

    @pytest.mark.asyncio
    async def test_build_chunk_variants(self):
        """Direct tests for _build_chunk helper."""
        # Minimal chunk (all optionals None)
        chunk = _cloudflare._build_chunk("id1", 100, "m1")
        assert chunk["id"] == "id1"
        assert chunk["choices"] == []

        # Content + role chunk
        chunk2 = _cloudflare._build_chunk(
            "id2", 200, "m2", delta_content="hi", delta_role="assistant"
        )
        assert chunk2["choices"][0]["delta"] == {"role": "assistant", "content": "hi"}

        # Finish reason with extra kwargs
        chunk3 = _cloudflare._build_chunk(
            "id3", 300, "m3", finish_reason="stop", x_tokens=42
        )
        assert chunk3["choices"][0]["finish_reason"] == "stop"
        assert chunk3["x_tokens"] == 42

    @pytest.mark.asyncio
    async def test_make_chunk_id(self):
        """_make_chunk_id returns unique IDs with correct prefix."""
        import llm_apipool.providers.cloudflare as cf

        cid = cf._make_chunk_id()
        assert cid.startswith("chatcmpl-")
        assert len(cid) == 21  # "chatcmpl-" (9) + 12 hex chars
