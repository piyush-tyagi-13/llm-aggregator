"""Tests for headers.py - rate-limit parsing and cooldown derivation."""

from __future__ import annotations

from datetime import datetime, timezone

from llm_apipool.providers.headers import (
    _groq,
    _cerebras,
    _mistral,
    _interfaze,
    _github_models,
    collect_rl_headers,
    extract_cooldown,
    extract_remaining_requests,
    _parse_duration_str,
)


def test_parse_duration_str_seconds():
    assert _parse_duration_str("30s") == 30.0


def test_parse_duration_str_milliseconds():
    val = _parse_duration_str("170ms")
    assert val is not None and abs(val - 0.17) < 0.01


def test_parse_duration_str_hours_minutes_seconds():
    val = _parse_duration_str("1h30m20s")
    assert val is not None and abs(val - 5420.0) < 0.1


def test_parse_duration_str_invalid():
    assert _parse_duration_str("invalid") is None


def test_collect_rl_headers_filters_correctly():
    raw = {
        "content-type": "application/json",
        "x-ratelimit-remaining-requests": "10",
        "x-ratelimit-remaining-tokens": "5000",
        "x-request-id": "abc123",
    }
    result = collect_rl_headers(raw)
    assert "x-ratelimit-remaining-requests" in result
    assert "x-ratelimit-remaining-tokens" in result
    assert "content-type" not in result
    assert "x-request-id" not in result


def test_groq_no_cooldown_when_remaining():
    headers = {
        "x-ratelimit-remaining-requests": "5",
        "x-ratelimit-reset-requests": "1m",
    }
    assert _groq(headers, was_429=False) is None


def test_groq_cooldown_on_exhaustion():
    headers = {
        "x-ratelimit-remaining-requests": "0",
        "x-ratelimit-reset-requests": "30s",
    }
    result = _groq(headers, was_429=False)
    assert result is not None
    parsed = datetime.fromisoformat(result)
    now = datetime.now(timezone.utc)
    delta = (parsed - now).total_seconds()
    assert 25 <= delta <= 35


def test_groq_cooldown_on_429_with_retry_after():
    headers = {"retry-after": "60"}
    result = _groq(headers, was_429=True)
    assert result is not None
    parsed = datetime.fromisoformat(result)
    now = datetime.now(timezone.utc)
    delta = (parsed - now).total_seconds()
    assert 55 <= delta <= 65


def test_cerebras_day_exhausted():
    headers = {"x-ratelimit-remaining-requests-day": "0"}
    result = _cerebras(headers, was_429=False)
    assert result is not None
    parsed = datetime.fromisoformat(result)
    assert parsed.hour == 0
    assert parsed.minute == 0


def test_cerebras_429_fallback():
    result = _cerebras({}, was_429=True)
    assert result is not None


def test_mistral_minute_exhausted():
    headers = {"x-ratelimit-remaining-req-minute": "0"}
    result = _mistral(headers, was_429=False)
    assert result is not None
    parsed = datetime.fromisoformat(result)
    now = datetime.now(timezone.utc)
    delta = (parsed - now).total_seconds()
    assert 55 <= delta <= 65


def test_mistral_429_fallback():
    result = _mistral({}, was_429=True)
    assert result is not None


def test_mistral_no_cooldown_when_remaining():
    headers = {"x-ratelimit-remaining-req-minute": "5"}
    assert _mistral(headers, was_429=False) is None


def test_interfaze_no_cooldown_when_remaining():
    headers = {"x-ratelimit-remaining-requests": "10"}
    assert _interfaze(headers, was_429=False) is None


def test_interfaze_cooldown_on_exhaustion():
    headers = {"x-ratelimit-remaining-requests": "0"}
    result = _interfaze(headers, was_429=False)
    assert result is not None


def test_interfaze_cooldown_on_429():
    result = _interfaze({}, was_429=True)
    assert result is not None


def test_github_models_cooldown_on_exhaustion():
    headers = {"x-ratelimit-remaining-requests": "0"}
    result = _github_models(headers, was_429=False)
    assert result is not None
    parsed = datetime.fromisoformat(result)
    assert parsed.hour == 0


def test_github_models_429_fallback():
    result = _github_models({}, was_429=True)
    assert result is not None


def test_extract_cooldown_known_provider():
    headers = {"x-ratelimit-remaining-req-minute": "0"}
    result = extract_cooldown("mistral", headers, was_429=False)
    assert result is not None


def test_extract_cooldown_unknown_provider():
    assert extract_cooldown("unknown_provider", {}, was_429=False) is None


def test_extract_remaining_requests_groq():
    headers = {"x-ratelimit-remaining-requests": "15"}
    assert extract_remaining_requests("groq", headers) == 15


def test_extract_remaining_requests_interfaze():
    headers = {"x-ratelimit-remaining-requests": "42"}
    assert extract_remaining_requests("interfaze", headers) == 42


def test_extract_remaining_requests_unknown():
    assert extract_remaining_requests("unknown", {}) is None


# ===================================================================
# Edge cases: type coercion failures and uncovered branches
# ===================================================================


def test_groq_invalid_retry_after():
    """When retry-after is unparseable as float, falls through to request dimension."""
    headers = {
        "retry-after": "not-a-number",
        "x-ratelimit-remaining-requests": "0",
        "x-ratelimit-reset-requests": "30s",
    }
    result = _groq(headers, was_429=True)
    # Should fall through to request-dimension check and return a cooldown
    assert result is not None
    parsed = datetime.fromisoformat(result)
    now = datetime.now(timezone.utc)
    delta = (parsed - now).total_seconds()
    assert 25 <= delta <= 35


def test_groq_invalid_remaining_requests():
    """Non-integer x-ratelimit-remaining-requests sets remaining_int to None."""
    headers = {"x-ratelimit-remaining-requests": "abc"}
    assert _groq(headers, was_429=False) is None


def test_groq_invalid_remaining_tokens():
    """Non-integer x-ratelimit-remaining-tokens sets rem_tok_int to None."""
    headers = {"x-ratelimit-remaining-tokens": "abc", "x-ratelimit-reset-tokens": "30s"}
    assert _groq(headers, was_429=False) is None


def test_groq_token_exhaustion():
    """When remaining-tokens is 0 and reset-tokens is valid, return cooldown."""
    headers = {"x-ratelimit-remaining-tokens": "0", "x-ratelimit-reset-tokens": "30s"}
    result = _groq(headers, was_429=False)
    assert result is not None
    parsed = datetime.fromisoformat(result)
    now = datetime.now(timezone.utc)
    delta = (parsed - now).total_seconds()
    assert 25 <= delta <= 35


def test_cerebras_invalid_header_value():
    """Non-integer header value in Cerebras is caught by except block."""
    headers = {"x-ratelimit-remaining-requests-day": "abc"}
    assert _cerebras(headers, was_429=False) is None


def test_cerebras_no_header_no_429():
    """Cerebras returns None when was_429=False and no matching headers."""
    assert _cerebras({}, was_429=False) is None


def test_mistral_invalid_remaining():
    """Non-integer x-ratelimit-remaining-req-minute is caught by except."""
    headers = {"x-ratelimit-remaining-req-minute": "abc"}
    assert _mistral(headers, was_429=False) is None


def test_github_models_invalid_remaining():
    """Non-integer x-ratelimit-remaining-requests is caught by except."""
    headers = {"x-ratelimit-remaining-requests": "abc"}
    assert _github_models(headers, was_429=False) is None


def test_github_models_no_header_no_429():
    """GitHub Models returns None when was_429=False and no matching headers."""
    assert _github_models({}, was_429=False) is None


def test_interfaze_invalid_remaining():
    """Non-integer x-ratelimit-remaining-requests is caught by except."""
    headers = {"x-ratelimit-remaining-requests": "abc"}
    assert _interfaze(headers, was_429=False) is None


def test_extract_remaining_requests_cerebras():
    """Cerebras uses x-ratelimit-remaining-requests-day."""
    headers = {"x-ratelimit-remaining-requests-day": "10"}
    assert extract_remaining_requests("cerebras", headers) == 10


def test_extract_remaining_requests_mistral():
    """Mistral uses x-ratelimit-remaining-req-minute."""
    headers = {"x-ratelimit-remaining-req-minute": "5"}
    assert extract_remaining_requests("mistral", headers) == 5


def test_extract_remaining_requests_invalid():
    """Non-integer header value returns None."""
    headers = {"x-ratelimit-remaining-requests": "abc"}
    assert extract_remaining_requests("groq", headers) is None
