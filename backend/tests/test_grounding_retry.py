"""The grounding retry edge: when a rejected draft is rewritten, and when it isn't.

Split into two groups. The first exercises app.nodes.grounding on its own, which is
pure Python and stays fast. The second drives route_after_grounding inside a real
LangGraph loop with a stub synthesizer, because the thing worth proving is that the
loop *terminates* — a retry edge that can re-enter itself forever would be worse than
no retry at all.

Nothing here imports the retriever, so the suite does not pay the corpus load for it.
"""

import sys
from pathlib import Path
from typing import List, Optional, TypedDict

import pytest

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.nodes.grounding import grounding  # noqa: E402


def _verses(n):
    return [
        {"verse_id": f"sutrasthana/{i}", "text": f"verse {i}", "meta": {}}
        for i in range(1, n + 1)
    ]


# A real TypedDict, not `dict`. StateGraph(dict) collapses to a single channel whose
# value is whatever the last node returned, so each node silently discards the rest
# of the state — grounding then sees no `retrieved`, takes the n == 0 path, and the
# retry never fires. The test would pass against a broken loop while proving nothing.
# AgentState works because it declares one channel per key.
class _RetryState(TypedDict, total=False):
    final_answer: str
    retrieved: List[dict]
    confidence: str
    trace: List[str]
    grounding_score: Optional[float]
    grounding_cited: List[int]
    grounding_notes: List[str]
    grounding_retry_instruction: Optional[str]
    synthesis_attempts: int
    attribution: List[dict]


# --- what earns a retry -------------------------------------------------------


def test_no_citations_at_all_triggers_retry():
    out = grounding({"final_answer": "Triphala is widely used.", "retrieved": _verses(3)})
    assert out["grounding_retry_instruction"] is not None
    assert "[1]" in out["grounding_retry_instruction"]


def test_out_of_range_citation_triggers_retry():
    out = grounding({"final_answer": "As described [7].", "retrieved": _verses(2)})
    instr = out["grounding_retry_instruction"]
    assert instr is not None
    # Must tell the model which markers actually exist, not just that it was wrong.
    assert "7" in instr and "[1], [2]" in instr


def test_both_faults_reported_together():
    out = grounding({"final_answer": "No marker here and [9].", "retrieved": _verses(2)})
    assert out["grounding_retry_instruction"] is not None


# --- what deliberately does not ------------------------------------------------


def test_full_coverage_does_not_retry():
    out = grounding({"final_answer": "A [1] and B [2].", "retrieved": _verses(2)})
    assert out["grounding_retry_instruction"] is None
    assert out["grounding_score"] == 1.0


def test_partial_coverage_does_not_retry():
    """One honest citation out of three is not a defect.

    An answer that draws on a single verse and says so is correct behaviour. Retrying
    here would spend a synthesis call to satisfy a coverage metric rather than to fix
    an error, which is the opposite of what a self-check loop is for.
    """
    out = grounding({"final_answer": "Only [1] applies here.", "retrieved": _verses(3)})
    assert out["grounding_retry_instruction"] is None
    assert out["grounding_score"] == pytest.approx(1 / 3, abs=0.001)


def test_nothing_retrieved_does_not_retry():
    """A retrieval failure is not a drafting failure — the retry would see the same
    empty context and produce the same uncited answer."""
    out = grounding({"final_answer": "Something.", "retrieved": []})
    assert out["grounding_retry_instruction"] is None


def test_retry_is_recorded_in_trace_for_the_reasoning_panel():
    out = grounding(
        {"final_answer": "uncited", "retrieved": _verses(2), "trace": ["earlier step"]}
    )
    assert any("retrying synthesis" in step for step in out["trace"])
    assert out["trace"][0] == "earlier step"


# --- the routing decision ------------------------------------------------------


def test_router_retries_when_instruction_present_and_budget_left():
    from app.graph import route_after_grounding

    assert (
        route_after_grounding(
            {"grounding_retry_instruction": "cite [1]", "synthesis_attempts": 1}
        )
        == "synthesize"
    )


def test_router_stops_at_attempt_cap():
    from app.graph import MAX_SYNTHESIS_ATTEMPTS, route_after_grounding

    assert MAX_SYNTHESIS_ATTEMPTS == 2
    assert (
        route_after_grounding(
            {"grounding_retry_instruction": "cite [1]", "synthesis_attempts": 2}
        )
        == "attribution"
    )


def test_router_proceeds_when_answer_was_acceptable():
    from app.graph import route_after_grounding

    assert (
        route_after_grounding(
            {"grounding_retry_instruction": None, "synthesis_attempts": 1}
        )
        == "attribution"
    )


# --- termination, proven in a real loop ---------------------------------------


def test_retry_loop_terminates_and_second_draft_is_accepted():
    """Wire the real grounding node and the real router into a LangGraph loop.

    The stub synthesizer plays the part of a model that ignores the feedback the
    first time and complies the second. Asserting the loop halts after two passes is
    the point: a self-check edge that cannot prove it terminates is not shippable.
    """
    from langgraph.graph import END, StateGraph

    from app.graph import route_after_grounding
    from app.nodes.grounding import grounding as grounding_node

    calls = {"n": 0}

    def fake_synthesize(state):
        calls["n"] += 1
        # First attempt ignores instructions and cites nothing; second complies.
        answer = "uncited claim" if calls["n"] == 1 else "cited claim [1]"
        return {"final_answer": answer, "synthesis_attempts": calls["n"]}

    b = StateGraph(_RetryState)
    b.add_node("synthesize", fake_synthesize)
    b.add_node("grounding", grounding_node)
    b.add_node("attribution", lambda s: {"attribution": []})
    b.set_entry_point("synthesize")
    b.add_edge("synthesize", "grounding")
    b.add_conditional_edges(
        "grounding",
        route_after_grounding,
        {"synthesize": "synthesize", "attribution": "attribution"},
    )
    b.add_edge("attribution", END)
    graph = b.compile()

    out = graph.invoke(
        {
            "final_answer": "",
            "retrieved": _verses(3),
            "confidence": "high",
            "trace": [],
        },
        config={"recursion_limit": 25},
    )

    assert calls["n"] == 2, "expected exactly one retry"
    assert out["final_answer"] == "cited claim [1]"
    assert out["grounding_cited"] == [1]
    assert out["grounding_score"] == pytest.approx(1 / 3, abs=0.001)


def test_loop_stops_even_when_every_draft_is_bad():
    """The pathological case: the model never cites. It must still halt."""
    from langgraph.graph import END, StateGraph

    from app.graph import route_after_grounding
    from app.nodes.grounding import grounding as grounding_node

    calls = {"n": 0}

    def always_bad(state):
        calls["n"] += 1
        return {
            "final_answer": "still uncited",
            "synthesis_attempts": calls["n"],
        }

    b = StateGraph(_RetryState)
    b.add_node("synthesize", always_bad)
    b.add_node("grounding", grounding_node)
    b.add_node("attribution", lambda s: {"attribution": []})
    b.set_entry_point("synthesize")
    b.add_edge("synthesize", "grounding")
    b.add_conditional_edges(
        "grounding",
        route_after_grounding,
        {"synthesize": "synthesize", "attribution": "attribution"},
    )
    b.add_edge("attribution", END)
    graph = b.compile()

    out = graph.invoke(
        {"final_answer": "", "retrieved": _verses(2), "confidence": "high", "trace": []},
        config={"recursion_limit": 25},
    )

    assert calls["n"] == 2, "loop must not run away"
    assert out["synthesis_attempts"] == 2