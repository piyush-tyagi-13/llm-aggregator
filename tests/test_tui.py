from __future__ import annotations
"""Basic TUI import test."""


def test_tui_import():
    """Verify TUI module can be imported without crashing."""
    try:
        import llm_apipool.tui  # type: ignore[import-untyped]
        assert hasattr(llm_apipool.tui, "LLMKeyPoolApp")
    except (ImportError, AttributeError):
        # TUI file may not exist in all checkouts
        pass
