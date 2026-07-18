# PROJECT KNOWLEDGE BASE

**Generated:** 2026-06-26 22:55:00
**Commit:** bbf48fa
**Branch:** main

## OVERVIEW
Python 3.11 CLI/TUI/Proxy/LangChain key-pool manager for 40+ free-tier LLM APIs with tier-based routing, cooldown tracking, audit logging, and OpenAI-compatible proxy access. Stack: Typer, Textual, FastAPI, SQLite, Alembic, OpenAI SDK, LangChain Core.

## STRUCTURE
```
llm-apipool/
├── llm_apipool/              # Core package (see llm_apipool/AGENTS.md)
│   ├── __init__.py           # Exports AggregatorChat
│   ├── __main__.py           # Script entry
│   ├── cli.py                # Typer CLI: import/add/deactivate/logs/proxy/gui
│   ├── key_checker.py        # Provider probing for bulk-import auto-detect
│   ├── key_store.py          # SQLite WAL DB, audit log, rotation counters
│   ├── rotator.py            # Tier routing, cooldowns, balanced rotation
│   ├── proxy.py              # FastAPI OpenAI-compatible proxy
│   ├── tui.py                # Textual app, 5 tabs
│   ├── providers/            # Provider dispatch and clients (see AGENTS.md)
│   ├── config/               # providers.json + model_quality.json
│   ├── api/                  # FastAPI app, routes, middleware (make_app)
│   └── core/                 # Router, affinity, handoff, sticky, effort, etc.
├── frontend/                 # React dashboard (see frontend/AGENTS.md)
├── tests/                    # 515 pytest tests (see tests/AGENTS.md)
├── alembic/                  # Migration env + 9 schema versions
├── docs/                     # Screenshots and Hermes integration notes
├── scripts/                  # Benchmarks, utilities (bench_ttft.py)
├── .github/workflows/        # CI/CD (test.yml, publish.yml)
├── pyproject.toml            # Package metadata, deps, console script
├── README.md                 # User guide
├── CONTRIBUTING.md           # Dev setup and provider extension guide
└── .pre-commit-config.yaml   # pre-commit hooks (ruff, mypy, bandit)
```

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| CLI entry point | `__main__.py`, `cli.py` | `llm-apipool` script → `main()` → Typer `app` |
| Import formats | `cli.py:_parse_import_entry()`, `tui.py:_resolve_import_entries()` | key-per-line, `provider:key`, `---` blocks, NDJSON |
| Key persistence | `key_store.py` | SQLite WAL, parameterized queries, plaintext keys |
| Model routing | `rotator.py`, `config/model_quality.json` | 4 quality tiers, cooldown, slot rotation |
| Provider dispatch | `providers/dispatch.py` | 10 non-streaming retries, streaming single attempt |
| OpenAI-compatible providers | `providers/openai_compat.py` | `AsyncOpenAI.with_raw_response`, think-token stripping, connection pooling |
| Rate-limit headers | `providers/headers.py` | Groq/Cerebras/Mistral/GitHub/Interfaze parsers |
| OpenAI proxy | `proxy.py:make_app()` | `/v1/chat/completions`, `/v1/models`, `/health`, `/audit`, `/logs/*` |
| FastAPI app builder | `api/app.py:make_app()` | Composes all routers, middleware, background services |
| TUI | `tui.py`, local `tui_logs.py` | Textual `run_test()` coverage; local untracked log viewer exists |
| LangChain wrapper | `langchain_wrapper.py` | `AggregatorChat` bridges sync/async calls |
| Migrations | `alembic/env.py`, `alembic/versions/` | Dynamic DB path from env; 0001-0009 |
| API routes | `api/routes/` | keys, settings, models, chat, health, analytics, effort, bulk-import, tiers |
| Settings save-all | `api/routes/settings.py:save_all_settings` | POST /api/settings/save-all — 12 fields, error collection |
| Bulk import (probe) | `api/routes/bulk_import.py:auto_import` | POST /api/keys/auto-import — analyse + probe ambiguous keys |
| Effort/thinking config | `core/model_effort.py` | Per-model + global effort levels, injection priority (per-model ≻ global ≻ preset) |
| Affinity routing | `core/affinity.py` | UID-based key+model pinning, busy/semi-busy tracking |
| Test patterns | `tests/test_*.py` | No `conftest.py`; local fixtures/mocks |
| Frontend | `frontend/` | React dashboard with 5 pages, Vitest tests, routing |
| CI/CD | `.github/workflows/test.yml` | Ruff, mypy, bandit, pytest + coverage, frontend build + test + tsc |
| Benchmarks | `scripts/bench_ttft.py` | Cold vs warm connection pool TTFT measurement, --ci mode |

## CODE MAP
| Symbol | Type | Location | Role |
|--------|------|----------|------|
| `KeyStore` | class | `key_store.py:129` | DB CRUD, audit log, cooldown/counters |
| `Rotator` | class | `rotator.py:119` | Best-key selection, tier filtering, 429 handling |
| `AggregatorChat` | class | `langchain_wrapper.py:79` | LangChain `BaseChatModel` wrapper |
| `complete()` | func | `providers/dispatch.py:52` | Dispatch, retry, rotate, audit usage |
| `extract_remaining_requests()` | func | `providers/headers.py:215` | Normalize remaining-request headers |
| `make_app()` | func | `api/app.py:41` | Build FastAPI proxy app with all routes |
| `_get_client()` | func | `providers/openai_compat.py` | Cached `AsyncOpenAI` client (connection pooling) |
| `LLMKeyPoolApp` | class | `tui.py:596` | Main Textual TUI app |
| `ProxyLogsApp` | class | `tui_logs.py:147` | Local untracked TUI log viewer |
| `analyse_bulk()` | func | `core/key_detection.py:113` | Bulk-import text classification |
| `check_key_against_provider()` | func | `key_checker.py` | Probe a key against a provider |
| `set_global_effort_level()` | func | `core/model_effort.py` | Apply unified effort level across all providers |
| `get_state_snapshot()` | func | `core/affinity.py:205` | Affinity routing introspection for dashboard |

## CONVENTIONS
- **Imports**: new Python files start with `from __future__ import annotations`; older files are mixed.
- **Types**: prefer modern `list[str]`, `dict[str, Any]`, and `X | Y`; avoid `typing.List`/`Optional`.
- **Async**: provider calls are `async`; CLI/TUI bridge with `asyncio.run()` or Textual workers.
- **Config**: provider metadata lives in `llm_apipool/config/providers.json`; model tiers in `model_quality.json`.
- **DB**: SQLite WAL; `LLM_APIPOOL_DB` overrides `~/.llm-apipool/keys.db`; SQL should stay parameterized.
- **Capabilities**: use `capabilities: list[str]`; `category` is legacy/migration-only.
- **Tests**: `pytest-asyncio`; mock external HTTP and TUI; no real API keys.
- **Provider contract**: return `CompletionResult` for non-streaming or an async generator of OpenAI chunk dicts for streaming.
- **Settings error handling**: `save_all_settings` collects errors per-field; invalid values never cause a 500.

## ANTI-PATTERNS (THIS PROJECT)
- Broad `except Exception` catches remain in provider, TUI, and local log modules; narrow new catches.
- Plaintext API keys are stored in SQLite; mask keys in logs and avoid printing raw values.
- Legacy `category` appears in migrations, docs, and tests; new APIs should use `capabilities`.
- Silent migration/index suppression in `key_store.py:148-153`; new migrations should fail loudly.
- Token estimation falls back to `len(content)//4` only when tiktoken fails; prefer tiktoken.
- Non-streaming 429 retries are immediate/capped in `dispatch.py`; streaming makes one attempt and does not retry.
- `affinity.get_state_snapshot()` previously deadlocked (threading.Lock not re-entrant) — fixed by inlining slot count.

## UNIQUE STYLES
- **4-tier model quality**: Tier 1 Frontier → Tier 4 Fallback (`model_quality.json`).
- **Subscriber tracking**: every call/audit entry includes `subscriber_id` (e.g. `hermes.main`, `mdcore.ingest`).
- **Think-token stripping**: removes `` and `{...}}` style reasoning artifacts.
- **Provider auto-detect**: key prefixes map imports to providers (e.g. `gsk_`, `sk-`, `cs_`, `AIza`, `hf_`).
- **Proxy model alias**: `LLM-Apipool` is exposed by `/v1/models`.
- **Effort level mapping**: unified low/medium/high maps to reasoning_effort (OpenAI), thinking+budget_tokens (Anthropic), thinking (DeepSeek), etc.
- **Connection pooling**: `_get_client()` caches `AsyncOpenAI` by connection params to reuse HTTP keep-alive.

## COMMANDS
```bash
# Install
pip install -e ".[all]"        # TUI + proxy
pip install -e ".[dev,all]"    # dev + optional deps
pip install -e .               # core only
uv sync --group dev --all-extras  # uv install with all extras

# Dev (Python)
pytest -xvs                    # all tests, verbose
pytest --cov=llm_apipool       # coverage
uv run pytest -q --tb=short    # quick run
ruff check .                   # lint
ruff format --check .          # format check
mypy llm_apipool               # type check
bandit -r llm_apipool -x tests # security scan

# Dev (Frontend)
cd frontend
npm ci                         # install deps
npm run build                  # tsc + vite build
npm test                       # vitest run
npx tsc --noEmit               # type check only

# Pre-commit
pre-commit install             # enable hooks
pre-commit run --all-files     # run once

# Run
llm-apipool status             # show key pool
llm-apipool gui                # Textual TUI
llm-apipool proxy --port 8000  # OpenAI-compatible proxy
alembic upgrade head           # apply DB migrations

# Benchmark
uv run python scripts/bench_ttft.py --provider groq --ci
```

## NOTES
- Current working tree is dirty; do not assume a clean repo or commit generated docs without checking diffs.
- `.github/workflows/test.yml` runs ruff, mypy, bandit (continue-on-error), pytest with coverage, frontend build + test + tsc.
- `pyproject.toml` had a bug where `dependencies` was nested under `[project.urls]` — fixed June 2026.
- DB default: `~/.llm-apipool/keys.db`; legacy path `~/.llm-aggregator/keys.db` is copied forward if present.
- Version: `1.0.0`; GitHub remote: `https://github.com/GFardad/llm-apipool`.
- No `.bak` files remain; untracked local modules (`proxy_logger.py`, `tui_logs.py`) exist but are not committed.
