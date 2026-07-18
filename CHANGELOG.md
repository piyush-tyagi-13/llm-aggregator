# Changelog

All notable changes to llm-apipool are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Effort/thinking parameter presets system with per-provider presets
- API routes for per-model effort config override (GET/PUT/DELETE)
- Frontend effort config modal on Models page
- GitHub Actions CI workflow (test/lint/typecheck)
- PyPI publishing workflow

### Changed
- Renamed project from `llm-keypool` to `llm-apipool`
- All imports, environment variables, CLI commands, and docs updated

## [1.0.0] — 2026-04-09

### Added
- React dashboard frontend (Vite + TypeScript + Tailwind)
- Alembic migrations 0006-0009
- Scoring system for model selection
- Sticky sessions / affinity support
- `model_override` per-key configuration
- `reasoning_content` passthrough for thinking models
- `no_auth` mode for local-only providers
- Structured error handling in provider dispatch
- FastAPI route infrastructure (`/api/*` endpoints)
- Provider checker utility
- Selectable proxy model alias (`LLM-Apipool`)

### Fixed
- Deprecated CLI entry point and old TUI removed
- Old test suite cleaned up

## [0.4.0] — 2026-01-22

### Added
- Capabilities system replacing legacy `category`
- Audit log with subscriber tracking
- Hermes Agent integration guide

## [0.3.1] — 2026-01-08

### Added
- `peek_current_key()` on Rotator
- `AggregatorChat.current_key()` for LangChain wrapper
- Quota state exposure to clients

## [0.3.0] — 2025-12-29

### Added
- Module rename from `llm_aggregator` to `llm_keypool`
- Rotation stress tester
- Header-driven cooldown system

### Fixed
- TUI banner updated to new branding
- All remaining `llm-aggregator` name remnants purged

## [0.2.1] — 2025-12-20

### Added
- TUI screenshots in README
- Proxy server roadmap

### Removed
- MCP server and optional dependency

## [0.2.0] — 2025-12-18

### Added
- CLI with Typer
- Textual TUI
- Rich console output
- Provider auto-detection by key prefix

### Changed
- MCP server demoted to optional extra
- DB path moved to `~/.llm-aggregator/keys.db`

## [0.1.0] — 2025-12-15

### Added
- Initial release: LLM aggregator MCP server
- LangChain wrapper (`AggregatorChat`)
- Basic key pool management
