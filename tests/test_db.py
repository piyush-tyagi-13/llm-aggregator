from __future__ import annotations

from unittest.mock import MagicMock


from llm_apipool.db.queries import (
    get_active_key_count,
    get_key_health_summary,
    get_provider_breakdown,
    get_recent_usage,
    get_strategy_settings,
)
from llm_apipool.db.schema import (
    ApiKeyRow,
    AuditLogRow,
    DDL_STATEMENTS,
    FallbackConfigRow,
    ModelRow,
    ProfileRow,
    RequestLogRow,
    SettingRow,
    StickySessionRow,
)


class TestSchema:
    def test_api_key_row_defaults(self):
        row = ApiKeyRow()
        assert row.provider == ""
        assert row.is_active == 1
        assert row.priority == 100

    def test_audit_log_row_defaults(self):
        row = AuditLogRow()
        assert row.status == "success"
        assert row.tokens_used == 0

    def test_model_row_defaults(self):
        row = ModelRow()
        assert row.context_window == 8192
        assert row.supports_tools == 1

    def test_fallback_config_row_defaults(self):
        row = FallbackConfigRow()
        assert row.priority == 100
        assert row.enabled == 1

    def test_profile_row_defaults(self):
        row = ProfileRow()
        assert row.is_active == 1

    def test_setting_row_defaults(self):
        row = SettingRow()
        assert row.key == ""
        assert row.value == ""

    def test_sticky_session_row_defaults(self):
        row = StickySessionRow()
        assert row.session_id == ""

    def test_request_log_row_defaults(self):
        row = RequestLogRow()
        assert row.status == "success"
        assert row.latency_ms == 0

    def test_ddl_statements_count(self):
        assert len(DDL_STATEMENTS) > 5


class TestQueries:
    def test_get_active_key_count(self):
        store = MagicMock()
        store.get_all_keys.return_value = [
            {"is_active": 1, "cooldown_until": None},
            {"is_active": 1, "cooldown_until": None},
            {"is_active": 0, "cooldown_until": None},
        ]
        assert get_active_key_count(store) == 2

    def test_get_provider_breakdown(self):
        store = MagicMock()
        store.get_all_keys.return_value = [
            {"provider": "groq", "is_active": 1},
            {"provider": "groq", "is_active": 1},
            {"provider": "cerebras", "is_active": 1},
            {"provider": "cerebras", "is_active": 0},
        ]
        result = get_provider_breakdown(store)
        assert result["groq"] == 2
        assert result["cerebras"] == 1

    def test_get_key_health_summary(self):
        store = MagicMock()
        store.get_all_keys.return_value = [
            {"is_active": 1, "cooldown_until": None},
            {"is_active": 1, "cooldown_until": "2099-01-01T00:00:00"},
            {"is_active": 0, "cooldown_until": None},
        ]
        result = get_key_health_summary(store)
        assert result["total"] == 3
        assert result["active"] == 2
        assert result["inactive"] == 1

    def test_get_recent_usage(self):
        store = MagicMock()
        store.get_audit_summary.return_value = []
        result = get_recent_usage(store)
        assert isinstance(result, list)

    def test_get_strategy_settings(self):
        store = MagicMock()
        result = get_strategy_settings(store)
        assert "strategy" in result
        assert "penalty_count" in result
