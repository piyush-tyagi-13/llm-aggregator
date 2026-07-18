from __future__ import annotations

from llm_apipool.core.sticky import (
    clear_all,
    get_all_sessions,
    get_or_create,
    is_sticky_enabled,
    on_success,
    release,
    set_sticky_enabled,
)


def _create(session: str, model_db_id: int = 1, key_id: int = 1):
    return get_or_create(session, model_db_id, key_id)


def test_sticky_get_or_create():
    result = _create("session_1")
    assert result is not None
    assert result["model_db_id"] == 1
    assert result["key_id"] == 1


def test_sticky_get_or_create_returns_same():
    first = _create("test_same_session")
    second = _create("test_same_session")
    assert first == second


def test_sticky_release():
    _create("release_test")
    release("release_test")
    new_session = _create("release_test")
    assert new_session is not None


def test_sticky_on_success():
    _create("success_test")
    on_success("success_test")


def test_sticky_get_all():
    sessions = get_all_sessions()
    assert isinstance(sessions, list)


def test_sticky_clear():
    _create("clear_test")
    clear_all()
    sessions = get_all_sessions()
    assert len(sessions) == 0


def test_sticky_enabled_global():
    original = is_sticky_enabled()
    set_sticky_enabled(False)
    assert not is_sticky_enabled()
    set_sticky_enabled(True)
    assert is_sticky_enabled()
    set_sticky_enabled(original)
