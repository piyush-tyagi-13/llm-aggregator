# Alembic Migrations

**Generated:** 2026-06-22 03:30:08
**Commit:** 69232d0

## OVERVIEW
Schema evolution for the SQLite key-pool database: keys, rotation state, audit log, capabilities, and base URL overrides.

## STRUCTURE
```
alembic/
├── env.py                         # Dynamic DB path from env vars
└── versions/
    ├── 0001_initial_schema.py      # api_keys, rotation_state, rotation_slot_counts
    ├── 0002_add_base_url_override.py
    ├── 0003_add_model_and_capabilities.py
    ├── 0004_rename_rotation_category.py
    └── 0005_create_audit_log.py
```

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| DB path resolution | `alembic/env.py:_resolve_db_path()` | `LLM_APIPOOL_DB` or `LLM_APIPOOL_DB_LEGACY`, else `~/.llm-apipool/keys.db` |
| Initial schema | `versions/0001_initial_schema.py` | Base tables and indexes |
| Base URL override | `versions/0002_add_base_url_override.py` | Adds `base_url_override` to `api_keys` |
| Capabilities migration | `versions/0003_add_model_and_capabilities.py` | Adds `model`, `capabilities` |
| Legacy rename | `versions/0004_rename_rotation_category.py` | `rotation_state.category` → `cap_key` |
| Audit log | `versions/0005_create_audit_log.py` | Subscriber/provider/model/tokens/status tracking |

## CONVENTIONS
- **Env path**: `alembic/env.py` overrides `alembic.ini` with the resolved SQLite URL.
- **Migration order**: use zero-padded numeric prefixes (`0006_...`).
- **SQLite**: prefer `op.add_column`, `op.alter_column`, `op.create_table`; avoid destructive downgrades in production.
- **Schema alignment**: keep `key_store.SCHEMA` and Alembic migrations aligned.
- **Legacy data**: preserve compatibility with old `category` where existing DBs may still have it.

## ANTI-PATTERNS
- Do not assume `alembic.ini`'s placeholder URL is the real DB path.
- Do not add migrations that silently swallow errors.
- Do not rename/drop columns without a tested upgrade/downgrade path.
- Do not store raw API keys in new schema fields; existing `api_keys.api_key` is plaintext.
- Do not rely on `key_store.MIGRATIONS` as the canonical migration source.

## COMMANDS
```bash
alembic upgrade head
alembic current
alembic history
alembic revision -m "description"
```

## GOTCHAS
- `key_store.py` still runs inline `MIGRATIONS` for legacy DB compatibility; Alembic is the deploy path.
- `rotation_state.cap_key` is JSON-sorted capabilities joined by `,`.
- `api_keys.capabilities` is JSON text, not a native SQLite JSON column.
- Downgrades may be unsafe once real user keys exist.
