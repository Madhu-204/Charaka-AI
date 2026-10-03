"""`CHARAKA_MAX_HISTORY_TURNS` has to actually control something.

It was read from the environment into `MAX_HISTORY_TURNS` and then ignored: both
the synthesis prompt and the cache fingerprint sliced `history[-6:]` as a
literal. Setting the variable to anything other than 6 changed nothing, which is
worse than not having it — the setting looked like a working budget control.

Two places must agree on the window, and the cache fingerprint is the one that
turns disagreement into a wrong answer rather than a slightly longer prompt. If
the prompt carried ten turns while the fingerprint hashed six, a change confined
to turn seven would leave the cache key unchanged and a stale answer could be
served for a different question.

`/ask` is covered here too because it used to bypass the store entirely: a
caller sending only a `conversation_id` got first-turn behaviour there while the
streaming endpoint returned real multi-turn.
"""

import importlib

import pytest

from app import main as app_main
from app.nodes import synthesis


def _turns(n, marker="t"):
    return [{"role": "user", "content": f"{marker}{i}"} for i in range(n)]


# --- the setting is live ----------------------------------------------------


def test_default_window_is_six():
    assert synthesis.MAX_HISTORY_TURNS == 6


def test_prompt_window_follows_the_setting(monkeypatch):
    monkeypatch.setattr(synthesis, "MAX_HISTORY_TURNS", 3)
    block = synthesis._format_history(_turns(10))
    assert block.count("\n") == 2  # three turns -> two newlines
    assert "t9" in block and "t2" not in block


def test_window_larger_than_the_thread_is_harmless(monkeypatch):
    monkeypatch.setattr(synthesis, "MAX_HISTORY_TURNS", 50)
    block = synthesis._format_history(_turns(4))
    assert block.count("\n") == 3


def test_prompt_and_cache_fingerprint_agree_on_the_window(monkeypatch):
    """The invariant that matters: one window, not two.

    Checked through both modules because the mismatch is invisible from either
    side alone — each looks correct in isolation.
    """
    monkeypatch.setattr(synthesis, "MAX_HISTORY_TURNS", 4)
    monkeypatch.setattr(app_main, "MAX_HISTORY_TURNS", 4)
    history = _turns(10)

    prompt_window = synthesis._format_history(history).split("\n")
    assert len(prompt_window) == 4

    # A change to a turn the model cannot see must leave the key alone,
    # otherwise every answer gets a cache miss.
    changed_outside = [dict(m, content=m["content"] + "!") for m in history[:6]] + history[6:]
    assert app_main._history_fingerprint(history) == app_main._history_fingerprint(changed_outside)

    # A change to a turn the model *can* see must move the key, otherwise a
    # later turn in the thread gets answered from an earlier turn's result.
    changed_inside = history[:6] + [dict(m, content=m["content"] + "!") for m in history[6:]]
    assert app_main._history_fingerprint(history) != app_main._history_fingerprint(changed_inside)


def test_fingerprint_imports_the_same_constant():
    """Guard against the two drifting back apart on a later edit."""
    assert app_main.MAX_HISTORY_TURNS is synthesis.MAX_HISTORY_TURNS


# --- /ask resolves the stored thread ---------------------------------------


def _stored(monkeypatch, record):
    monkeypatch.setattr(
        app_main.conversations, "get_conversation", lambda cid, owner=None: record
    )


@pytest.mark.parametrize("sent", [None, []])
def test_ask_history_resolution_matches_the_streaming_path(monkeypatch, sent):
    """Same input, same answer, whichever endpoint is used."""
    _stored(
        monkeypatch,
        {
            "messages": [{"role": "user", "content": "earlier turn"}],
            "dosha_profile": "vata",
        },
    )
    history, profile = app_main._resolve_history(sent, "conv-1")
    assert history == ([{"role": "user", "content": "earlier turn"}] if sent is None else [])
    assert profile == ("vata" if sent is None else None)


def test_ask_cache_key_uses_resolved_history(monkeypatch):
    """A cache entry built for turn 1 must not answer turn 5.

    Regression guard for the ordering trap: the resolver has to run before the
    key is composed, or the key silently describes the unresolved request.
    """
    _stored(
        monkeypatch,
        {
            "messages": [
                {"role": "user", "content": "turn one"},
                {"role": "assistant", "content": "answer one"},
            ],
            "dosha_profile": "vata",
        },
    )
    resolved, _ = app_main._resolve_history(None, "conv-1")
    raw = None
    assert app_main._history_fingerprint(resolved) != app_main._history_fingerprint(raw)


def test_env_var_is_read_at_import(monkeypatch):
    """Reimporting with the variable set must change the constant.

    Documents that the value is captured once, which is why the ignored constant
    went unnoticed: nothing re-read it after startup.
    """
    monkeypatch.setenv("CHARAKA_MAX_HISTORY_TURNS", "9")
    reloaded = importlib.reload(synthesis)
    try:
        assert reloaded.MAX_HISTORY_TURNS == 9
    finally:
        monkeypatch.delenv("CHARAKA_MAX_HISTORY_TURNS", raising=False)
        importlib.reload(synthesis)
        importlib.reload(app_main)