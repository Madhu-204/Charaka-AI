"""Why `None` and `[]` must not be treated as the same thing.

`_resolve_history` loads the stored conversation thread when the caller sends no
history. The whole mechanism turns on one distinction:

* `None`  — "I have no opinion, load the thread."
* `[]`    — "this turn genuinely has no prior context."

Only `None` consults the store. A client that defaults an absent field to `[]`
therefore pins every turn to being the first one, and multi-turn memory looks
implemented while being unreachable. That is not hypothetical: the frontend did
exactly this for as long as the feature existed, and nothing failed loudly —
history was simply always empty.

These tests pin the contract from both ends, the server and the payload, so the
next client cannot reintroduce it silently.
"""

import pytest

from app import main as app_main


@pytest.fixture
def stored(monkeypatch):
    """A conversation holding one exchange, plus the dosha it recorded."""

    def _fake(cid, owner=None):
        if cid != "conv-1":
            return None
        return {
            "messages": [
                {"role": "user", "content": "what is grahani"},
                {"role": "assistant", "content": "a digestive weakness"},
            ],
            "dosha_profile": "vata",
        }

    monkeypatch.setattr(app_main.conversations, "get_conversation", _fake)
    return "conv-1"


def test_none_loads_the_stored_thread(stored):
    """The path the frontend fix re-enabled."""
    history, profile = app_main._resolve_history(None, stored)
    assert [m["role"] for m in history] == ["user", "assistant"]
    assert profile == "vata"


def test_empty_list_does_not_load_the_thread(stored):
    """An explicit empty history is an instruction, not an absence.

    Honouring it is what keeps "start a fresh question" possible inside a thread.
    Collapsing it into `None` would make it impossible to opt out of context.
    """
    history, profile = app_main._resolve_history([], stored)
    assert history == []
    assert profile is None


def test_caller_supplied_history_is_never_overwritten(stored):
    history, _ = app_main._resolve_history(
        [{"role": "user", "content": "explicit"}], stored
    )
    assert history == [{"role": "user", "content": "explicit"}]


def test_caller_supplied_dosha_wins_over_the_stored_one(stored):
    """A profile the caller stated outranks whatever the thread recorded."""
    _, profile = app_main._resolve_history(None, stored, None, "pitta")
    assert profile == "pitta"


def test_no_conversation_id_means_no_lookup(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("must not touch the store without a conversation id")

    monkeypatch.setattr(app_main.conversations, "get_conversation", _boom)
    assert app_main._resolve_history(None, None) == (None, None)
    assert app_main._resolve_history(None, "") == (None, None)


def test_unknown_conversation_yields_no_history(stored):
    """A thread that no longer exists must not raise or invent context."""
    history, profile = app_main._resolve_history(None, "conv-missing")
    assert history is None
    assert profile is None


def test_messages_without_content_are_skipped(monkeypatch, stored):
    """Streaming writes placeholder rows; those must not enter the prompt."""
    monkeypatch.setattr(
        app_main.conversations,
        "get_conversation",
        lambda cid, owner=None: {
            "messages": [
                {"role": "assistant", "content": ""},
                {"role": "user", "content": "real question"},
            ],
            "dosha_profile": None,
        },
    )
    history, _ = app_main._resolve_history(None, stored)
    assert history == [{"role": "user", "content": "real question"}]


# --- the payload contract the fix depends on -------------------------------


def test_frontend_does_not_default_history_to_an_empty_array():
    """Guard the client half of the contract without a JS test runner.

    The frontend has no test setup (no vitest, no runner in package.json), so
    there is nowhere to assert the payload shape for real. `JSON.stringify` omits
    an `undefined` property, which is what makes the fix work; what would undo it
    is a `?? []` reappearing on this line. A textual check is a poor substitute for
    a test runner and is labelled as one.
    """
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "frontend" / "src" / "api.ts").read_text(
        encoding="utf-8"
    )
    assert "history: opts.history ?? []" not in source, (
        "frontend defaults an absent history to [], which blocks the stored-thread "
        "fallback and silently disables multi-turn memory"
    )
    assert "history: opts.history," in source