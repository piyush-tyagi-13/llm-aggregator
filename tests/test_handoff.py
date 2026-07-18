from __future__ import annotations

from llm_apipool.core.handoff import (
    clear_all,
    get_all_sessions,
    get_handoff_mode,
    has_prior_model,
    maybe_inject,
    record_incoming,
    record_successful,
)


def test_handoff_get_mode():
    mode = get_handoff_mode()
    assert mode in ("on_model_switch", "off")


def test_handoff_record_and_has_prior():
    record_incoming("s1", [{"role": "user", "content": "hi"}])
    record_successful("s1", "model_x")
    assert has_prior_model("s1")


def test_handoff_has_prior_no_session():
    assert not has_prior_model("nonexistent_session")


def test_handoff_maybe_inject():
    mode = get_handoff_mode()
    messages = [{"role": "user", "content": "hi"}]
    record_incoming("inj1", messages)
    record_successful("inj1", "old_model")
    result, injected, tokens = maybe_inject("inj1", messages, "new_model")
    # When handoff is on_model_switch and models differ, injection must occur
    assert injected == (mode == "on_model_switch")
    assert isinstance(result, list)


def test_handoff_get_all_sessions():
    sessions = get_all_sessions()
    assert isinstance(sessions, list)


def test_handoff_clear_all():
    record_incoming("clear_test", [{"role": "user", "content": "x"}])
    clear_all()
    sessions = get_all_sessions()
    assert len(sessions) == 0
