# llm_apipool Core Package

**Generated:** 2026-06-26 22:55:00
**Commit:** bbf48fa

## OVERVIEW
Core package: Typer CLI, SQLite key store, tiered rotator, FastAPI proxy (with modular routes), Textual TUI, LangChain wrapper, provider dispatch, connection-pooled OpenAI clients.

## STRUCTURE
```
llm_apipool/
├── __init__.py           # Exports AggregatorChat
├── __main__.py           # `llm-apipool` script entry
├── cli.py                # Typer commands and import parsing
├── key_checker.py        # Provider config checker / auto-detect bridge
├── key_store.py          # SQLite CRUD, audit log, usage counters
├── rotator.py            # Quality tiers, cooldowns, slot rotation
├── langchain_wrapper.py  # AggregatorChat BaseChatModel wrapper
├── proxy.py              # FastAPI OpenAI-compatible proxy (legacy entry)
├── proxy_logger.py       # Untracked local proxy JSONL logger
├── tui.py                # Textual app
├── tui_logs.py           # Untracked local proxy log viewer
├── providers/            # Provider dispatch and clients
├── config/
│   ├── providers.json    # 42 provider definitions
│   └── model_quality.json # 4-tier model map
├── api/                  # Modular FastAPI application
│   ├── app.py            # make_app() — composes all routers
│   ├── errors.py         # Error response helpers
│   ├── middleware/       # Auth, logging, rate-limit middleware
│   └── routes/           # keys, settings, models, chat, health, analytics, effort, tiers, bulk-import, media, embeddings
├── core/                 # Routing logic modules
│   ├── affinity.py       # UID-based key+model pinning
│   ├── handoff.py        # Context handoff between models
│   ├── key_detection.py  # Key format classification (unique prefix / sk-* / unknown)
│   ├── model_effort.py   # Per-model + global effort presets
│   ├── model_ingestion.py # Sync models from provider /v1/models
│   ├── model_sync_service.py # Periodic background model sync
│   ├── ratelimiter.py    # Token-bucket rate limiter middleware
│   ├── router.py         # Thompson sampling / routing strategies
│   ├── sticky.py         # Sticky session routing
│   ├── tier_fallback.py  # Tier fallback on failure
│   └── ...               # Other core utilities
└── db/                   # Database layer
    ├── connection.py     # Connection management
    └── queries.py        # Aggregated query functions
```

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| Entry point | `__main__.py:6` | `main()` calls `cli.app()` |
| CLI add/import | `cli.py:add`, `cli.py:import_keys` | Typer commands; import parsing helpers below |
| Import parsing | `cli.py:_parse_import_entry`, `_resolve_import_entries` | key-per-line, `provider:key`, `---` blocks, NDJSON |
| TUI import parsing | `tui.py:_parse_import_entry`, `_resolve_import_entries` | Mirrors CLI, async unknown-provider checks |
| DB init/schema | `key_store.py:_init_db`, `SCHEMA` | SQLite WAL; inline migrations for legacy DBs |
| Key CRUD | `key_store.py:register_key`, `get_active_keys`, `get_all_keys` | Capabilities are JSON text in SQLite |
| Usage/audit | `key_store.py:record_usage`, `log_audit`, `get_audit_log` | Every call includes `subscriber_id` |
| Routing | `rotator.py:get_best_key`, `handle_429`, `handle_success` | Tier range, score, rotation state |
| Provider dispatch | `providers/dispatch.py:complete` | Non-streaming retries; streaming single attempt |
| Connection pooling | `providers/openai_compat.py:_get_client` | Cached AsyncOpenAI by (base_url, api_key, no_auth, stream) |
| Proxy endpoints | `proxy.py:make_app` | `/v1/chat/completions`, `/v1/models`, `/health`, `/audit`, `/logs/*` |
| FastAPI app builder | `api/app.py:make_app` | Composes all routers, adds middleware, registers lifecycle events |
| API routes | `api/routes/` | Modular routers: keys, settings, models, chat, health, analytics, effort, bulk-import, tiers, media, embeddings |
| Settings save-all | `api/routes/settings.py:save_all_settings` | 12-field bulk save with per-field error collection |
| Bulk auto-import | `api/routes/bulk_import.py:auto_import` | Analyse + probe ambiguous keys; commit-import persists them |
| Effort config | `core/model_effort.py` | Per-model overrides + global low/medium/high level; injection priority |
| Key detection | `core/key_detection.py` | Format-based classification (unique prefix → auto, sk-* → probe) |
| TUI app | `tui.py:LLMKeyPoolApp` | Keys, proxy logs, add key, audit, import tabs |
| LangChain | `langchain_wrapper.py:AggregatorChat` | `_generate()` calls `_agenerate()` via `asyncio.run` |

## CONVENTIONS
- **DB**: `LLM_APIPOOL_DB` overrides `~/.llm-apipool/keys.db`; `LLM_APIPOOL_DB_LEGACY` is copied forward if present.
- **SQL**: new SQL must be parameterized; avoid dynamic SET clauses or f-string SQL.
- **Capabilities**: prefer `capabilities: list[str]`; legacy positional `category` compatibility remains in tests/migrations.
- **Provider calls**: async; return `CompletionResult` unless `stream=True`, then async generator of OpenAI chunk dicts.
- **429 handling**: provider returns `was_429=True`; `dispatch()` calls `rotator.handle_429()` and retries non-streaming calls.
- **Token accounting**: prefer `tiktoken`; char/4 is only fallback.
- **Secrets**: mask API keys before logs; never print raw key material.

## ANTI-PATTERNS (THIS MODULE)
- `category` is legacy; do not add new public APIs around it.
- Broad `except Exception` exists in TUI/local logs; new code should catch specific exceptions.
- `_init_db()` suppresses duplicate migration/index errors; new Alembic migrations should fail loudly.
- Provider code truncates error messages; include provider/status where possible without leaking keys.
- Streaming path intentionally does not retry on 429; document this when changing proxy behavior.

## KEY FUNCTIONS
| Function | File | Purpose |
|----------|------|---------|
| `main()` | `__main__.py:6` | Console script entry |
| `_load_provider_configs()` | `cli.py:39`, `api/app.py:35` | Load `config/providers.json` |
| `KeyStore.register_key()` | `key_store.py:173` | Insert key with caps, model, base URL, extra params |
| `KeyStore.get_active_keys()` | `key_store.py:213` | Filter active, non-cooled-down keys by capabilities |
| `KeyStore.record_usage()` | `key_store.py:246` | Daily/monthly counters, cooldown, last_429 |
| `Rotator.get_best_key()` | `rotator.py:229` | Tier/score/order selection with `rotate_every` |
| `Rotator.handle_429()` | `rotator.py:331` | Cooldown from headers or provider fallback strategy |
| `dispatch.complete()` | `providers/dispatch.py:52` | Select key, call provider, rotate, audit |
| `make_app()` | `api/app.py:41` | Build FastAPI proxy app with all routes |
| `AggregatorChat._agenerate()` | `langchain_wrapper.py:103` | Async LangChain call path |
| `check_key_against_provider()` | `key_checker.py` | Probe a key against a specific provider (used by bulk-import) |
| `analyse_bulk()` | `core/key_detection.py:113` | Bulk-import text classification |
| `set_global_effort_level()` | `core/model_effort.py` | Apply unified low/medium/high across all providers |
| `get_state_snapshot()` | `core/affinity.py:205` | Affinity routing introspection for dashboard |

## ENTRY POINTS
- `llm-apipool` → `__main__.py:main()` → `cli.app()`
- `python -m llm_apipool` → same
- `llm_apipool.AggregatorChat` → LangChain wrapper around `providers.dispatch.complete()`

## GOTCHAS
- `cap_key` = JSON-sorted capabilities joined by `,` (e.g., `general_purpose,fast`).
- `extra_params` is stored as JSON string in DB and forwarded to providers.
- `base_url_override` wins over provider config; `{account_id}` is filled from `extra_params`.
- Proxy exposes `LLM-Apipool` as a selectable OpenAI-compatible model ID.
- Local untracked modules (`proxy_logger.py`, `tui_logs.py`) exist; do not assume they are part of the committed package.
- `get_state_snapshot()` uses `threading.Lock` (not RLock) — do not call `available_slots()` from inside the locked section.
- Background services in `make_app()` (HealthCheckService, ModelSyncService) create asyncio tasks on startup that can delay TestClient shutdown.
