# Provider Implementations

**Generated:** 2026-06-22 03:30:08
**Commit:** 69232d0

## OVERVIEW
Provider layer: `dispatch()` selects a key, calls OpenAI-compatible or native clients, handles 429 rotation, and normalizes rate-limit headers.

## STRUCTURE
```
providers/
├── __init__.py          # empty
├── base.py              # CompletionResult dataclass
├── dispatch.py          # Retry loop, streaming path, token estimation
├── headers.py           # Rate-limit header extraction and cooldown parsing
├── openai_compat.py     # AsyncOpenAI client, think-token strip
├── cloudflare.py        # Cloudflare Workers AI native REST
├── cohere.py            # Cohere native API
└── *.bak                # Local backup files; do not merge/delete without instruction
```

## WHERE TO LOOK
| Task | File | Notes |
|------|------|-------|
| Add OpenAI-compatible provider | `config/providers.json`, `dispatch.py:_call_complete` | Most providers route automatically through `openai_compat.complete()` |
| Add native provider | `cloudflare.py`, `cohere.py`, `dispatch.py:_call_complete` | Implement `complete(key_data, messages, stream=False, **kwargs)` |
| Non-streaming retry | `dispatch.py:complete` | 10 attempts max; immediate capped backoff on `was_429` |
| Streaming retry policy | `dispatch.py:_stream_complete` | Single attempt; no 429 retry |
| Provider errors | `providers/base.py`, `openai_compat.py`, `cohere.py`, `cloudflare.py` | Return `CompletionResult` or OpenAI error chunk |
| Rate-limit headers | `headers.py:extract_remaining_requests`, `extract_cooldown` | Groq/Cerebras/Mistral/GitHub/Interfaze parsers |
| Token estimation | `dispatch.py:_estimate_tokens` | `tiktoken` first; char/4 fallback |
| Provider config | `config/providers.json` | 41 providers; 35 OpenAI-compatible, 6 native/endpoint |

## CONVENTIONS
- **Dispatch input**: provider functions receive `key_data`, not raw `api_key`/`base_url`.
- **Non-streaming output**: `CompletionResult(text, tokens_used, was_429, error, remaining_requests, rate_limit_headers)`.
- **Streaming output**: async generator of OpenAI chunk dicts with `id`, `created`, `model`, `choices`, and optional `x_tokens_used`.
- **429 contract**: set `was_429=True`; `dispatch()` calls `rotator.handle_429()` and rotates.
- **Provider config**: `openai_compatible`, `limits`, `quota_api`, `quota_headers`, `cooldown_fallback`, `default_model`, `models`, `capabilities`.
- **Native provider**: add module, implement `async def complete(...)`, register in `dispatch.py:_call_complete`, add tests.

## ANTI-PATTERNS (THIS MODULE)
- Do not add a new provider by subclassing a non-existent `OpenAICompatibleProvider`; OpenAI-compatible providers use `openai_compat.complete()`.
- Broad `except Exception` remains in `dispatch.py`, `openai_compat.py`, `cohere.py`, and `cloudflare.py`; narrow new catches.
- Do not leak API keys in error strings; use `_mask_key()` for URLs/keys.
- Do not truncate errors without provider/status context.
- `openai_compat.py:258` currently has an f-string quoting syntax error; fix/verify provider code before tests.
- Streaming must not silently retry; if retry is added, update proxy/TUI expectations.

## PROVIDER CONFIG SHAPE
```json
{
  "groq": {
    "base_url": "https://api.groq.com/openai/v1",
    "openai_compatible": true,
    "free_tier": true,
    "limits": { "rpm": 30, "tpm": 6000, "rpd": 14400 },
    "quota_api": "headers",
    "quota_headers": {
      "remaining_requests": "x-ratelimit-remaining-requests",
      "remaining_tokens": "x-ratelimit-remaining-tokens"
    },
    "cooldown_fallback": { "strategy": "daily_utc_midnight" },
    "default_model": "llama-3.3-70b-versatile",
    "models": ["llama-3.3-70b-versatile"],
    "capabilities": ["general_purpose", "fast"]
  }
}
```

## EXTENDING
1. Add provider entry to `config/providers.json`.
2. If `openai_compatible: true`, no new client module is needed unless custom behavior is required.
3. If native, add `providers/<name>.py` and wire `dispatch.py:_call_complete()`.
4. Add header parsing in `headers.py` when rate-limit headers exist.
5. Add tests in `tests/test_providers.py` and `tests/test_streaming.py`.

## GOTCHAS
- `key_data["base_url"]` may include `{account_id}`; fill from `key_data["extra_params"]`.
- Cohere/Cloudflare streaming is simulated as one OpenAI-format chunk.
- `dispatch()` expects native providers to accept `stream=True` even if they return a single-chunk generator.
- Rate-limit cooldown can come from headers; fallback strategy lives in provider config.
