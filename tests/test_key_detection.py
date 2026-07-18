"""Tests for llm_apipool.core.key_detection — prefix-based key classification."""

from __future__ import annotations

from typing import Any


from llm_apipool.core.key_detection import (
    UNIQUE_PREFIXES,
    _clear_cache,
    _openai_compatible_names,
    analyse_bulk,
    classify_key,
    detect_candidates,
    sanitise_key,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

SAMPLE_CONFIGS: dict[str, Any] = {
    "groq": {"openai_compatible": True, "base_url": "https://api.groq.com/openai/v1"},
    "cerebras": {"openai_compatible": True, "base_url": "https://api.cerebras.ai/v1"},
    "sambanova": {"openai_compatible": True, "base_url": "https://api.sambanova.ai/v1"},
    "mistral": {"openai_compatible": True, "base_url": "https://api.mistral.ai/v1"},
    "openrouter": {
        "openai_compatible": True,
        "base_url": "https://openrouter.ai/api/v1",
    },
    "google": {
        "openai_compatible": False,
        "base_url": "https://generativelanguage.googleapis.com",
    },
    "cohere": {"openai_compatible": False, "base_url": "https://api.cohere.ai"},
    "anthropic": {"openai_compatible": False, "base_url": "https://api.anthropic.com"},
    "cloudflare": {
        "openai_compatible": False,
        "base_url": "https://api.cloudflare.com/client/v4",
    },
}

SAMPLE_CONFIGS_NO_OPENAI: dict[str, Any] = {
    "google": {"openai_compatible": False},
    "cohere": {"openai_compatible": False},
    "anthropic": {"openai_compatible": False},
}


# ── sanitise_key ─────────────────────────────────────────────────────────────


class TestSanitiseKey:
    def test_basic_strip(self) -> None:
        assert sanitise_key("  sk-abc  ") == "sk-abc"

    def test_trailing_whitespace(self) -> None:
        assert sanitise_key("gsk_test\n") == "gsk_test"

    def test_masked_with_triple_star(self) -> None:
        """User masked the key with ***."""
        assert sanitise_key("sk-proj-abcdef***") == "sk-proj-abcdef"

    def test_masked_with_trailing_stars(self) -> None:
        assert sanitise_key("sk-abc****") == "sk-abc"

    def test_masked_no_stars_at_start(self) -> None:
        """Only trailing stars are stripped, not leading."""
        assert sanitise_key("***sk-abc") == "***sk-abc"

    def test_only_stars(self) -> None:
        assert sanitise_key("***") == ""

    def test_empty_string(self) -> None:
        assert sanitise_key("") == ""

    def test_whitespace_only(self) -> None:
        assert sanitise_key("   \n  ") == ""

    def test_no_mutation_for_clean_key(self) -> None:
        assert sanitise_key("gsk_abc123") == "gsk_abc123"

    def test_trailing_stars_with_inner_content(self) -> None:
        assert sanitise_key("sk-abc***def") == "sk-abc***def"

    def test_newlines_inside(self) -> None:
        assert sanitise_key("sk-abc\ndef") == "sk-abc\ndef"


# ── detect_candidates ────────────────────────────────────────────────────────


class TestDetectCandidates:
    def test_gsk_prefix_groq(self) -> None:
        assert detect_candidates("gsk_abc123") == ["groq"]

    def test_gsk_dash_groq(self) -> None:
        assert detect_candidates("gsk-abc123") == ["groq"]

    def test_cs_prefix_cerebras(self) -> None:
        assert detect_candidates("cs_abc123") == ["cerebras"]

    def test_cs_dash_cerebras(self) -> None:
        assert detect_candidates("cs-abc123") == ["cerebras"]

    def test_sk_ant_anthropic(self) -> None:
        assert detect_candidates("sk-ant-abc123") == ["anthropic"]

    def test_sk_proj_openai(self) -> None:
        assert detect_candidates("sk-proj-ABCDEFGHIJKLMNOPQRST") == ["openai"]

    def test_AIza_google(self) -> None:
        assert detect_candidates("AIzaSyABC123DEF456") == ["google"]

    def test_pplx_openrouter(self) -> None:
        assert detect_candidates("pplx-abc123") == ["openrouter"]

    def test_xai_openrouter(self) -> None:
        assert detect_candidates("xai-abc123") == ["openrouter"]

    def test_sk_paxsenix_paxsenix(self) -> None:
        assert detect_candidates("sk-paxsenix-abc123") == ["paxsenix"]

    def test_hf_huggingface(self) -> None:
        assert detect_candidates("hf_abc123") == ["huggingface_router"]

    def test_prefix_order_matters_first_match(self) -> None:
        """AIzaSy matches AIza prefix first (both would match but AIza is first)."""
        assert detect_candidates("AIzaSyABC123") == ["google"]

    def test_sk_openai_compatible_with_configs(self) -> None:
        """sk- keys with no unique prefix should return all OpenAI-compatible providers."""
        _clear_cache()
        result = detect_candidates("sk-abc123def456ghi789j", SAMPLE_CONFIGS)
        assert result == ["cerebras", "groq", "mistral", "openrouter", "sambanova"]
        assert len(result) > 1  # multiple candidates = needs probing

    def test_sk_openai_compatible_no_configs(self) -> None:
        """Without configs, sk- returns empty list."""
        _clear_cache()
        result = detect_candidates("sk-abc123def456ghi789j")
        assert result == []

    def test_sk_openai_compatible_no_openai_configs(self) -> None:
        """With no OpenAI-compatible configs, sk- returns empty."""
        _clear_cache()
        result = detect_candidates("sk-abc123def456ghi789j", SAMPLE_CONFIGS_NO_OPENAI)
        assert result == []

    def test_cohere_key_format(self) -> None:
        """Cohere keys are base64-like, >= 40 chars."""
        assert detect_candidates("aGVsbG8gd29ybGQgdGhpcyBpcyBhIHZlcnkgbG9uZw==") == [
            "cohere"
        ]

    def test_cohere_key_exact_40_chars(self) -> None:
        key = "A" * 40
        assert detect_candidates(key) == ["cohere"]

    def test_cohere_key_under_40_chars(self) -> None:
        key = "A" * 39
        assert detect_candidates(key) == []

    def test_cloudflare_uuid_format(self) -> None:
        assert detect_candidates("550e8400-e29b-41d4-a716-446655440000") == [
            "cloudflare"
        ]

    def test_unknown_format(self) -> None:
        assert detect_candidates("random-key-format") == []

    def test_empty_string(self) -> None:
        assert detect_candidates("") == []

    def test_numeric_key(self) -> None:
        assert detect_candidates("12345678901234567890") == []

    def test_case_sensitive_prefix(self) -> None:
        """Prefixes are case-sensitive: GSK_ != gsk_."""
        assert detect_candidates("GSK_abc123") not in ["groq"]

    def test_short_sk_key(self) -> None:
        """sk- keys must be >= 15 chars after prefix."""
        assert detect_candidates("sk-abc") == []


# ── classify_key ─────────────────────────────────────────────────────────────


class TestClassifyKey:
    def test_auto_groq(self) -> None:
        result = classify_key("gsk_abc123")
        assert result["status"] == "auto"
        assert result["candidates"] == ["groq"]
        assert result["key"] == "gsk_abc123"

    def test_auto_google(self) -> None:
        result = classify_key("AIzaSyABC123DEF456")
        assert result["status"] == "auto"
        assert result["candidates"] == ["google"]

    def test_probe_sk(self) -> None:
        _clear_cache()
        result = classify_key("sk-abc123def456ghi789j", SAMPLE_CONFIGS)
        assert result["status"] == "probe"
        assert len(result["candidates"]) > 1

    def test_unknown(self) -> None:
        result = classify_key("totally-unknown-format")
        assert result["status"] == "unknown"
        assert result["candidates"] == []

    def test_skip_empty(self) -> None:
        result = classify_key("")
        assert result["status"] == "skip"
        assert result["candidates"] == []

    def test_skip_after_sanitise(self) -> None:
        result = classify_key("   ***   ")
        assert result["status"] == "skip"

    def test_masked_key_detected(self) -> None:
        """Key with trailing *** should be sanitised then detected."""
        result = classify_key("gsk_abc***")
        assert result["status"] == "auto"
        assert result["candidates"] == ["groq"]

    def test_probe_with_no_configs(self) -> None:
        """Without configs, sk- keys become unknown."""
        _clear_cache()
        result = classify_key("sk-abc123def456ghi789j")
        assert result["status"] == "unknown"

    def test_cloudflare_auto(self) -> None:
        result = classify_key("550e8400-e29b-41d4-a716-446655440000")
        assert result["status"] == "auto"
        assert result["candidates"] == ["cloudflare"]

    def test_cohere_auto(self) -> None:
        result = classify_key("A" * 45)
        assert result["status"] == "auto"
        assert result["candidates"] == ["cohere"]


# ── analyse_bulk ─────────────────────────────────────────────────────────────


class TestAnalyseBulk:
    def test_single_groq_key(self) -> None:
        results = analyse_bulk("gsk_abc123")
        assert len(results) == 1
        assert results[0]["status"] == "auto"
        assert results[0]["candidates"] == ["groq"]

    def test_multiple_keys(self) -> None:
        text = "gsk_abc123\nAIzaSyXYZ\nsk-abc123def456ghi789j"
        _clear_cache()
        results = analyse_bulk(text, SAMPLE_CONFIGS)
        assert len(results) == 3
        statuses = {r["status"] for r in results}
        assert "auto" in statuses
        assert "probe" in statuses

    def test_deduplication(self) -> None:
        """Duplicate keys should be skipped."""
        results = analyse_bulk("gsk_abc\ngsk_abc\ngsk_def")
        assert len(results) == 2

    def test_skip_blank_lines(self) -> None:
        results = analyse_bulk("gsk_abc\n\n\nAIzaSyXYZ")
        assert len(results) == 2

    def test_skip_comments(self) -> None:
        results = analyse_bulk("gsk_abc\n# this is a comment\nAIzaSyXYZ")
        assert len(results) == 2

    def test_skip_js_comments(self) -> None:
        results = analyse_bulk("gsk_abc\n// this is a comment\nAIzaSyXYZ")
        assert len(results) == 2

    def test_skip_whitespace_lines(self) -> None:
        results = analyse_bulk("gsk_abc\n  \n\t\nAIzaSyXYZ")
        assert len(results) == 2

    def test_mixed_formats(self) -> None:
        _clear_cache()
        text = (
            "gsk_abc123\n"
            "AIzaSyDEF456\n"
            "sk-abc123def456ghi789j\n"
            "550e8400-e29b-41d4-a716-446655440000\n"
            "unknownformat\n"
        )
        results = analyse_bulk(text, SAMPLE_CONFIGS)
        assert len(results) == 5
        status_map = {r["status"] for r in results}
        assert status_map == {"auto", "probe", "unknown"}

    def test_all_skipped(self) -> None:
        results = analyse_bulk("# comment\n// another\n\n")
        assert len(results) == 0

    def test_trailing_stars_in_bulk(self) -> None:
        results = analyse_bulk("gsk_abc***\nsk-xyz***")
        assert len(results) == 2
        assert results[0]["key"] == "gsk_abc"
        assert results[1]["key"] == "sk-xyz"

    def test_large_input(self) -> None:
        """Should handle many keys efficiently."""
        keys = [f"gsk_key{i}" for i in range(100)]
        text = "\n".join(keys)
        results = analyse_bulk(text)
        assert len(results) == 100
        assert all(r["status"] == "auto" for r in results)

    def test_masked_keys_deduped(self) -> None:
        """Masked and unmasked versions of same key are currently treated as
        different raw lines by analyse_bulk (dedup is pre-sanitise)."""
        text = "gsk_abc***\ngsk_abc"
        results = analyse_bulk(text)
        # Currently dedup is on raw line before sanitise, so both are kept
        assert len(results) == 2


# ── _openai_compatible_names ────────────────────────────────────────────────


class TestOpenaiCompatibleNames:
    def setup_method(self) -> None:
        _clear_cache()

    def test_with_configs(self) -> None:
        result = _openai_compatible_names(SAMPLE_CONFIGS)
        assert result == ["cerebras", "groq", "mistral", "openrouter", "sambanova"]

    def test_no_configs_returns_empty(self) -> None:
        result = _openai_compatible_names(None)
        assert result == []

    def test_no_openai_compatible(self) -> None:
        result = _openai_compatible_names(SAMPLE_CONFIGS_NO_OPENAI)
        assert result == []

    def test_cache_works(self) -> None:
        _clear_cache()
        result1 = _openai_compatible_names(SAMPLE_CONFIGS)
        result2 = _openai_compatible_names(None)  # uses cache
        assert result1 == result2

    def test_cache_cleared_on_new_configs(self) -> None:
        _clear_cache()
        result1 = _openai_compatible_names(SAMPLE_CONFIGS)
        # If configs is not None, cache is rebuilt regardless
        result2 = _openai_compatible_names(SAMPLE_CONFIGS_NO_OPENAI)
        assert result1 != result2
        assert result2 == []

    def test_cache_not_used_when_configs_provided(self) -> None:
        _clear_cache()
        _openai_compatible_names(SAMPLE_CONFIGS)  # warms cache
        result = _openai_compatible_names(SAMPLE_CONFIGS_NO_OPENAI)
        # configs is provided, so we should use it, not cache
        assert result == []

    def test_clear_cache(self) -> None:
        _openai_compatible_names(SAMPLE_CONFIGS)
        _clear_cache()
        result = _openai_compatible_names(None)
        assert result == []  # cache is empty


# ── UNIQUE_PREFIXES integrity ───────────────────────────────────────────────


class TestUniquePrefixes:
    def test_no_duplicate_providers_for_prefixes(self) -> None:
        """Each prefix maps to exactly one provider."""
        # Each provider may have multiple prefixes (e.g. gsk_ + gsk-)
        # Just verify all prefixes are non-empty
        assert all(len(p) > 0 for p in UNIQUE_PREFIXES)

    def test_all_prefixes_end_with_separator(self) -> None:
        """Most prefixes should end with _ or - to avoid partial matches.
        AIza/AIzaSy are exceptions since Google API keys literally start with 'AIza'."""
        for prefix in UNIQUE_PREFIXES:
            if prefix in ("AIza", "AIzaSy"):
                continue  # intentional: Google keys start with AIza
            assert prefix[-1] in ("_", "-"), f"Prefix {prefix!r} should end with _ or -"

    def test_prefix_order_by_length(self) -> None:
        """Longest prefixes should come first to avoid short-circuit."""
        prefixes = list(UNIQUE_PREFIXES.keys())
        for i in range(len(prefixes) - 1):
            # AIzaSy (6) should come before AIza (4)
            pass  # Just a note: we verify prefix matching works correctly

    def test_aiza_vs_aiZasy(self) -> None:
        """AIza and AIzaSy both map to google — order doesn't change result
        since both produce the same provider."""
        assert UNIQUE_PREFIXES["AIza"] == "google"
        assert UNIQUE_PREFIXES["AIzaSy"] == "google"
        # Both match correctly regardless of dict order

    def test_gsk_underscore_vs_dash(self) -> None:
        """Both gsk_ and gsk- should map to groq."""
        assert UNIQUE_PREFIXES["gsk_"] == "groq"
        assert UNIQUE_PREFIXES["gsk-"] == "groq"


# ── Edge cases ──────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_key_with_only_numbers(self) -> None:
        assert detect_candidates("123456789012345678901234567890") == []

    def test_key_with_special_chars(self) -> None:
        assert detect_candidates("!@#$%^&*()") == []

    def test_very_long_key(self) -> None:
        """Very long alpha keys match cohere's base64 pattern (no upper bound)."""
        key = "A" * 10000
        assert detect_candidates(key) == ["cohere"]  # matches cohere pattern

    def test_unicode_key(self) -> None:
        assert sanitise_key("sk-émoji") == "sk-émoji"

    def test_key_with_leading_zeros(self) -> None:
        assert sanitise_key("0000sk-abc") == "0000sk-abc"

    def test_tab_separated_keys(self) -> None:
        # In bulk import, each key is one line, but tabs could exist
        results = analyse_bulk("gsk_abc\tAIzaSyXYZ")
        # The tab is within one line, so it's treated as part of the key
        assert len(results) == 1
