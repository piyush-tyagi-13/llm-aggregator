# Test Suite

**Generated:** 2026-06-26 22:55:00
**Commit:** bbf48fa

## OVERVIEW
515 pytest tests (42 added June 2026) for the API routes, CLI, key store, rotator, providers, proxy, streaming, TUI, LangChain wrapper, bulk import, and settings save-all. Tests mock HTTP/TUI and avoid real API keys.

## STRUCTURE
```
tests/
├── __init__.py
├── test_api_routes.py            # FastAPI TestClient: settings, effort set-all, health, models, analytics
├── test_bulk_import.py           # POST /api/keys/auto-import and commit-import (17 tests)
├── test_catalog.py               # Model catalog queries (get_model_info, list_models, list_providers)
├── test_cli.py                   # Typer CLI, import parsing, add/import flows
├── test_core_model.py            # Model ingestion and free-model detection
├── test_db.py                    # Database query helpers
├── test_fallback.py              # Fallback config (max attempts, cooldown)
├── test_handoff.py               # Context handoff between models
├── test_headers.py               # Rate-limit header parsing
├── test_health.py                # Health check service
├── test_key_detection.py         # Key format classification (75 tests)
├── test_key_store.py             # KeyStore CRUD, cooldown, legacy migration
├── test_key_store_extended.py    # DB path resolution, capability parsing, edge cases
├── test_langchain_wrapper.py     # AggregatorChat sync/async wrapper tests
├── test_providers.py             # Provider clients, dispatch helpers, errors
├── test_proxy.py                 # FastAPI TestClient proxy endpoints
├── test_registry.py              # Provider registry (capabilities-based key filtering)
├── test_rotator.py               # Rotator selection, 429, cooldown strategies
├── test_rotator_extended.py      # Tier filtering, model quality, scoring
├── test_save_all.py              # POST /api/settings/save-all with 25 test cases
├── test_sticky.py                # Sticky session routing
└── test_streaming.py             # OpenAI chunk format, dispatch streaming path
```

## WHERE TO LOOK
| Task | File | Pattern |
|------|------|---------|
| CLI isolated DB | `test_cli.py` | `CliRunner`, autouse `isolated_db` fixture |
| API route tests | `test_api_routes.py` | `make_app(_configs=...)` + `TestClient`; `_reset_effort_state` autouse |
| Bulk import | `test_bulk_import.py` | `patch("llm_apipool.api.routes.bulk_import.check_key_against_provider")` with `AsyncMock` |
| Save-all settings | `test_save_all.py` | `make_app(_configs=...)` + `TestClient`; verify by reading back via GET endpoints |
| KeyStore tests | `test_key_store.py`, `test_key_store_extended.py` | `tmp_path`, SQLite fixture, legacy path copy |
| Rotator tests | `test_rotator.py`, `test_rotator_extended.py` | `Rotator` fixture, provider config dict |
| Provider tests | `test_providers.py` | `unittest.mock.patch`, `AsyncMock`, `MagicMock` |
| Proxy tests | `test_proxy.py` | FastAPI `TestClient`, monkeypatched DB |
| Streaming tests | `test_streaming.py` | Mock `AsyncOpenAI` stream and dispatch generators |
| TUI tests | `test_tui_ui.py` | `LLMKeyPoolApp().run_test(size=(80, 24))` |
| Header parsing | `test_headers.py` | `extract_remaining_requests()` edge cases |
| Key detection | `test_key_detection.py` | `detect_candidates()`, `analyse_bulk()` with various key formats |

## CONVENTIONS
- **Async**: mark async tests with `@pytest.mark.asyncio`.
- **Fixtures**: no `conftest.py`; fixtures are local to test files.
- **DB isolation**: use `tmp_path` + `monkeypatch.setenv("LLM_APIPOOL_DB", ...)`.
- **HTTP**: mock `AsyncOpenAI`/provider clients; do not call real APIs.
- **TUI**: use Textual `run_test()` for headless UI flows.
- **Secrets**: test keys are dummy strings; never add real credentials.
- **Cleanup**: autouse fixtures like `_reset_effort_state` and `_clear_cache` ensure test isolation.
- **Connection pool**: test files mock `_clear_client_cache()` to prevent test pollution.

## KEY FIXTURES / HELPERS
| Helper | Location | Purpose |
|--------|----------|---------|
| `app` / `client` | `test_api_routes.py` | `make_app(_configs=...)` + `TestClient` |
| `authenticated_client` | `test_api_routes.py` | Creates admin session via login |
| `_reset_effort_state` | `test_api_routes.py`, `test_save_all.py` | Clears global + per-model effort configs |
| `_patch_bulk_probing` | `test_bulk_import.py` | Mocks `check_key_against_provider` with configurable `side_effect` |
| `isolated_db` | `test_cli.py` | Autouse fixture; points DB at `tmp_path` |
| `db_path` | Various | Per-file SQLite path fixture |
| `store` / `rotator` | Rotation tests | Local KeyStore/Rotator fixtures |
| `key_data` | Provider/streaming tests | Minimal provider key dict |
| `runner = CliRunner()` | CLI tests | Typer CLI invocation helper |

## RUN
```bash
pytest -xvs                        # All tests, verbose
pytest --cov=llm_apipool           # Coverage report
uv run pytest -q --tb=short        # Quick run
uv run pytest tests/test_save_all.py  # Single file
pytest -k "not extended"           # Skip extended suites
```

## GOTCHAS
- `test_tui_ui.py` is large and uses real Textual app state; prefer helper tests for pure parsing.
- `test_providers.py` patches `llm_apipool.providers.openai_compat.AsyncOpenAI`.
- `test_streaming.py` validates OpenAI SSE chunk shapes, not live provider behavior.
- Pydantic/LangChain deprecation warnings may appear in wrapper tests (325 warnings total).
- No `conftest.py` — every file defines its own fixtures; duplicate `_reset_effort_state` exists in both `test_api_routes.py` and `test_save_all.py`.
- Bulk-import tests mock probing at the `check_key_against_provider` level; `sk-proj-*` keys are auto-classified as `openai` (unique prefix).
- `TestClient` shutdown may hang due to background asyncio tasks (HealthCheckService, ModelSyncService); tests use `timeout` wrapper as workaround.
