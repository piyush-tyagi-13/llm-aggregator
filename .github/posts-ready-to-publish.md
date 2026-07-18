# Launch Posts - Ready to Publish

## 1. Hacker News (Show HN)

URL: https://news.ycombinator.com/submit
Title: Show HN: llm-apipool – 40+ free LLM APIs behind one OpenAI-compatible endpoint
URL: https://github.com/GFardad/llm-apipool

No body needed (Show HN uses URL + optional text)

## 2. Reddit - r/LocalLLaMA

Title: llm-apipool – one proxy to rule all 40+ free LLM API tiers (Groq, Cerebras, Mistral, Google, etc.)

Post:
I was tired of juggling a dozen free API keys across different providers, each with its own SDK, its own rate-limit behavior, and its own auth format. One 429 in the middle of a streaming response and you're out of luck.

So I built an open-source tool that aggregates every free-tier LLM into a single OpenAI-compatible endpoint. You install it, drop in your free keys, and point anything at localhost:8000/v1.

What it does under the hood:

- 4-tier routing with automatic fallback. If Groq 429s, it falls to Cerebras, then Mistral, then OpenRouter — all transparent to your app.
- Cooldown tracking per key, with round-robin rotation across multiple keys per provider.
- Unified effort/thinking config. One POST maps low/medium/high to OpenAI reasoning_effort, Anthropic thinking+budget_tokens, DeepSeek thinking toggle, Google thinking. Works across all providers.
- Real SSE streaming for OpenAI-compatible providers. Simulated streaming for the rest.
- Think-token stripping so reasoning output stays clean.
- Audit log with subscriber tracking (tag calls as hermes.main or whatever).

Supported providers: Groq, Cerebras, Mistral, OpenRouter, Google, SambaNova, GitHub, Hugging Face, DeepSeek, Anthropic, OpenAI, xAI, Together, Fireworks, Cohere, Replicate, Lepton, Infermatic, and 25+ more. All free tiers.

It comes with a Textual TUI (5 tabs), a React dashboard, a LangChain AggregatorChat drop-in, and Docker compose. 522 tests passing.

Drop-in compatible with Hermes Agent, OpenCode, Claude Code, Cursor, Continue.dev, LangChain, and the OpenAI SDK. No code changes. Just swap the base URL.

```
pip install "llm-apipool[all]"
llm-apipool proxy --port 8000
export OPENAI_API_BASE="http://localhost:8000/v1"
```

https://github.com/GFardad/llm-apipool

## 3. Reddit - r/selfhosted

Title: llm-apipool – self-hosted AI gateway for 40+ free LLM APIs, Docker-ready

Post:
If you're running local AI tools and want to skip the $200/month API bills, the free tiers are great — until you hit a rate limit in the middle of a long-running batch and have to restart.

I built llm-apipool, a self-hosted proxy that sits between your apps and 40+ free LLM providers. Docker compose with healthcheck, persistent SQLite, environment config. Designed to run 24/7.

```
docker compose up -d
# Proxy at http://localhost:8000/v1
export OPENAI_API_BASE="http://localhost:8000/v1"
```

What makes it different from a simple round-robin script:

- Rate-limit handling with cooldowns. When a key 429s, it goes on cooldown, and the rotator selects the next best key from the next tier. No dropped requests.
- 4 quality tiers for smart fallback. Your Tier 1 queries fall to Tier 2, 3, or 4 as needed, so requests always get served.
- Key rotation across multiple keys per provider. Register 5 Groq keys and it round-robins through them.
- React dashboard and Textual TUI for managing keys, viewing analytics, and checking the audit log.
- LangChain AggregatorChat wrapper if you want direct integration.
- 522 passing tests. Alembic migrations for proper schema versioning.

It's 100% open source (MIT). You own your data, your keys, your infra.

Point any OpenAI-compatible tool at it: Hermes Agent, OpenCode, Claude Code, Cursor, Continue.dev, LangChain, or just curl.

```
pip install "llm-apipool[all]"
llm-apipool proxy --port 8000
```

https://github.com/GFardad/llm-apipool

## 4. Reddit - r/Python

Title: llm-apipool – 40+ free LLM APIs, one OpenAI-compatible proxy (Python, 522 tests, MIT)

Post:
Decided to scratch an itch. Managing 40+ free LLM API keys across different providers is a mess of inconsistent SDKs, ad-hoc retry logic, and brittle rate-limit handling. So I built a unified proxy in Python.

```
pip install "llm-apipool[all]"
llm-apipool add --provider groq --key gsk_... --model llama-3.3-70b-versatile
llm-apipool proxy --port 8000
```

The stack: Typer (CLI), Textual (TUI), FastAPI (proxy), SQLite + Alembic (persistence), AsyncOpenAI (provider clients), LangChain Core (wrapper).

Key implementation details:

- Provider dispatch is async with configurable retry logic (10 attempts for non-streaming, single attempt for streaming with transparent fallback).
- The rotator uses a tier-based selection algorithm with per-key cooldown slots and round-robin rotation. When a key 429s, it's marked with a timestamp and skipped until the cooldown expires.
- Unified effort configuration maps a single low/medium/high level to provider-specific parameters — OpenAI's reasoning_effort, Anthropic's thinking+budget_tokens, DeepSeek's thinking toggle, Google's thinking mode. All through one POST.
- Connection pooling caches AsyncOpenAI clients by connection params, reusing HTTP keep-alive across requests.
- Think-token stripping removes  and {outline-style} artifacts from reasoning model outputs.
- The LangChain integration is a single BaseChatModel subclass — AggregatorChat — that takes capabilities and quality tier params and hands off to the rotator.

The codebase: ~825 source files across Python + TypeScript/React frontend. 522 passing tests with pytest-asyncio. Ruff + mypy + bandit in CI. Well-typed with modern Python type hints throughout.

40+ providers supported out of the box (Groq, Cerebras, Mistral, OpenRouter, Google, SambaNova, GitHub, Hugging Face, DeepSeek, Anthropic, OpenAI, xAI, Together, Fireworks, Replicate, Cohere, and more). All free tiers.

```
from llm_apipool import AggregatorChat

llm = AggregatorChat(capabilities=["general_purpose"], quality_tier=1)
response = llm.invoke("Explain quantum computing")
```

MIT license. Contributions welcome.

https://github.com/GFardad/llm-apipool

## 5. Twitter/X Thread (6 tweets)

Tweet 1:
The free LLM tiers are incredible — Groq, Cerebras, Mistral, Google, OpenRouter, 40+ providers. But managing 40 API keys with 40 SDKs and 40 rate-limit behaviors is a nightmare. I built the thing I wanted: llm-apipool. One pip install, one endpoint.

Tweet 2:
llm-apipool sits on your machine (or in Docker) and aggregates every free-tier LLM provider behind a single OpenAI-compatible endpoint. Point any tool at http://localhost:8000/v1 and it works. Hermes Agent, Claude Code, Cursor, LangChain, curl — zero code changes.

Tweet 3:
The proxy handles rate limits automatically. When Groq 429s, it falls back to Cerebras, then Mistral, then OpenRouter across 4 quality tiers. Keys go on cooldown with timestamps. Round-robin rotation across multiple keys per provider. Your app never sees a 429.

Tweet 4:
Unified effort/thinking config. One API call sets low/medium/high across all providers — maps to OpenAI reasoning_effort, Anthropic thinking+budget_tokens, DeepSeek thinking toggle, Google thinking mode. Real SSE streaming. Think-token stripping. Audit log with per-subscriber tracking.

Tweet 5:
Comes with a Textual TUI (5 tabs), a React dashboard with analytics, a LangChain AggregatorChat drop-in, and Docker compose with healthcheck. 522 passing tests. MIT license. Written in Python 3.11+. 100% free and open source.

Tweet 6:
pip install "llm-apipool[all]"
llm-apipool proxy --port 8000
https://github.com/GFardad/llm-apipool

Zero API bills. One format. 40+ providers. Try it.

## 6. LinkedIn Post

The free tiers for LLM APIs are generous and getting better. Groq, Cerebras, Mistral, Google, OpenRouter, Hugging Face, DeepSeek — together they offer production-grade models at zero cost. The problem is you end up managing 40+ API keys, each with its own SDK, auth format, and rate-limit behavior.

I built llm-apipool to solve this. It's an open-source proxy that aggregates every free-tier LLM provider into a single OpenAI-compatible endpoint.

Install it with `pip install "llm-apipool[all]"`, register your keys, and point any tool at `localhost:8000/v1`. The proxy handles rate-limit cooldowns with fallback across 4 quality tiers, rotates keys round-robin, provides a unified effort/thinking config across providers, and logs every call with subscriber attribution.

It comes with a Textual terminal UI, a React dashboard, a LangChain drop-in wrapper, and Docker compose. 522 tests. MIT license.

No API bills. One integration. Every free tier.

https://github.com/GFardad/llm-apipool
