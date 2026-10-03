"""Router branches that skip retrieval: direct answers and pre-retrieval clarification.

The safety property under test is the important one. `direct_answer` lets a turn
bypass retrieval, and therefore also bypasses grounding, attribution and the safety
notes that ride along with a sourced answer. So the LLM's vote is never sufficient
on its own — a fixed pattern has to confirm it. These tests exist mainly to pin that
down: if someone widens the whitelist without thinking, the health-query cases below
are what should fail.

Nothing here imports the retriever except _has_anchor's own tests, which stub it.
"""

import sys
from pathlib import Path
from typing import List, Optional, TypedDict

import pytest

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.nodes.direct import direct_answer, _reply_for  # noqa: E402
from app.nodes.tool_router import _META_QUERY, route_tools  # noqa: E402

import re as _re

# Stands in for a whitelist that accepts the greeting under test, so the LLM
# confirmation path is exercised without loosening the real pattern.
_LOOSE_META = _re.compile(r"^\s*(thanks|thank you)\b", _re.IGNORECASE)


class _RouteState(TypedDict, total=False):
    query: str
    trace: List[str]
    tool_decision: str
    direct_answer: bool
    needs_clarification: bool
    clarification_hint: Optional[str]
    metadata_filter: Optional[dict]
    canonical_term: Optional[str]
    expanded_query: str


# --- the whitelist itself ------------------------------------------------------


@pytest.mark.parametrize(
    "q",
    ["hi", "Hello!", "hey there", "thanks", "Thank you.", "bye", "who are you",
     "what can you do", "how can you help"],
)
def test_meta_pattern_matches_conversation(q):
    assert _META_QUERY.match(q), q


@pytest.mark.parametrize(
    "q",
    [
        "what should I do",
        "my knee hurts",
        "is triphala safe",
        "headache since yesterday",
        "I have fever and rash",
        "help with digestion",  # starts with 'help' but names a complaint
    ],
)
def test_meta_pattern_rejects_health_questions(q):
    assert not _META_QUERY.match(q), q


# --- the direct-answer branch --------------------------------------------------


def test_greeting_short_circuits_before_any_llm_call():
    out = route_tools({"query": "hi", "trace": []})
    assert out["tool_decision"] == "direct_answer"
    assert out["direct_answer"] is True
    assert out["metadata_filter"] is None


def test_direct_answer_node_is_terminal_and_ungrounded():
    out = direct_answer({"query": "hi", "trace": []})
    assert out["is_direct_answer"] is True
    assert out["final_answer"]
    # Nothing was retrieved, so there is no citation check to report and no score.
    # Claiming a score here would be a fabricated verification.
    assert out["grounding_score"] is None
    assert out["grounding_notes"] == []


def test_direct_answer_never_invents_a_citation():
    """A greeting answer must not contain a [n] marker — nothing was retrieved, so
    any marker would point at a verse that does not exist."""
    for q in ["hi", "thanks", "who are you", "what can you do", "bye"]:
        assert "[" not in _reply_for(q), q


def test_reply_selection():
    assert "2,490 verses" in _reply_for("hello")
    assert "You're welcome" in _reply_for("thanks!")
    assert "not a clinician" in _reply_for("who are you")
    assert "citing the chapter" in _reply_for("what can you do")
    assert "Goodbye" in _reply_for("bye")


class _StubLLM:
    """Stands in for the module-level ChatGroq.

    Patching `tr.llm.invoke` does not work: ChatGroq is a pydantic model and
    rejects unknown attribute assignment, so the whole object must be replaced.
    """

    def __init__(self, calls):
        self._calls = calls

    def invoke(self, *a, **k):
        return type("R", (), {"tool_calls": self._calls})()


# --- the safety guard: the LLM cannot route a health query past retrieval -------


def test_llm_direct_answer_vote_is_overridden_for_health_query(monkeypatch):
    """The model claiming direct_answer must not be enough for a symptom question."""
    from app.nodes import tool_router as tr

    monkeypatch.setattr(tr, "llm", _StubLLM([{"name": "direct_answer", "args": {}}]))
    monkeypatch.setattr(tr, "_has_anchor", lambda *a, **k: True)

    out = route_tools({"query": "my knee hurts", "trace": []})
    assert out.get("direct_answer") is not True
    assert out["tool_decision"] != "direct_answer"


def test_llm_direct_answer_vote_confirmed_for_greeting(monkeypatch):
    from app.nodes import tool_router as tr

    # 'thanks so much' is not in the deterministic whitelist, so this reaches the
    # LLM and comes back through the confirmation path rather than the shortcut.
    monkeypatch.setattr(tr, "llm", _StubLLM([{"name": "direct_answer", "args": {}}]))
    monkeypatch.setattr(tr, "_META_QUERY", _LOOSE_META)
    out = route_tools({"query": "thanks so much", "trace": []})
    assert out["direct_answer"] is True


# --- ambiguity: ask before spending a retrieval --------------------------------


def test_underspecified_question_asks_instead_of_retrieving(monkeypatch):
    from app.nodes import tool_router as tr

    monkeypatch.setattr(
        tr,
        "llm",
        _StubLLM(
            [{"name": "plain_retrieval", "args": {"ambiguity": "no symptom named"}}]
        ),
    )
    monkeypatch.setattr(tr, "_has_anchor", lambda *a, **k: False)

    out = route_tools({"query": "what should I do", "trace": []})
    assert out["needs_clarification"] is True
    assert out["clarification_hint"] == "no symptom named"


def test_ambiguity_flag_ignored_when_the_query_names_something(monkeypatch):
    """Asking a user to clarify a question we could answer is a regression."""
    from app.nodes import tool_router as tr

    monkeypatch.setattr(
        tr,
        "llm",
        _StubLLM([{"name": "plain_retrieval", "args": {"ambiguity": "unspecified"}}]),
    )
    monkeypatch.setattr(tr, "_has_anchor", lambda *a, **k: True)

    out = route_tools({"query": "knee pain", "trace": []})
    assert not out.get("needs_clarification")


def test_router_failure_defaults_to_plain_retrieval(monkeypatch):
    """A dead LLM must not become a dead app."""
    from app.nodes import tool_router as tr

    class _Boom:
        def invoke(self, *a, **k):
            raise RuntimeError("provider down")

    monkeypatch.setattr(tr, "llm", _Boom())
    out = route_tools({"query": "fever treatment", "trace": []})
    assert out["tool_decision"] == "plain_retrieval"


# --- routing --------------------------------------------------------------------


def test_router_dispatch():
    from app.graph import route_after_tools

    assert route_after_tools({"direct_answer": True}) == "direct_answer"
    assert route_after_tools({"needs_clarification": True}) == "clarify"
    assert route_after_tools({}) == "retrieve"


def test_clarify_uses_the_router_hint_when_nothing_retrieved():
    from app.nodes.clarify import clarify

    out = clarify(
        {
            "query": "what should I do",
            "clarification_hint": "no symptom or topic named",
            "retrieved": [],
        }
    )
    assert out["is_clarification"] is True
    assert "no symptom or topic named" in out["final_answer"]


def test_clarify_hint_does_not_override_the_retrieved_path():
    """When verses were retrieved the nearby-chapter question is more useful, so a
    leftover hint must not hijack it."""
    from app.nodes.clarify import clarify

    out = clarify(
        {
            "query": "something vague",
            "clarification_hint": "unspecified",
            "retrieved": [
                {
                    "verse_id": "sutrasthana/1",
                    "text": "t",
                    "meta": {"sthana": "sutrasthana", "chapter": 1,
                             "traditional_condition": "fever", "category_tag": "fever"},
                }
            ],
        }
    )
    assert "Closest chapters were" in out["final_answer"]
