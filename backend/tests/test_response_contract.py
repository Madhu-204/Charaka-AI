"""`build_response` must not claim work that never happened.

`synthesis_attempts` is the field that reports how many drafts the synthesize
node produced, so a terminal path that skips that node has to report 0. Getting
this wrong is worse than omitting it: the frontend and the traces read it as a
real cost signal, and a greeting that reported "1 attempt" would look like it
burned a Groq call.

The distinction these tests pin is between the two conditions the function keeps
separate:

* `no_context` - nothing was retrieved, so chapter/category/dosha must be null.
  Emergency, scope refusal and a direct reply.
* `no_synthesis` - nothing was drafted. Those three, plus clarification.

Clarification is the interesting case because it can fire either side of
retrieval. Ahead of it (`route_after_tools`) nothing was retrieved. Behind it
(`route_after_retrieve`, on low confidence) a chapter really was resolved and
should still be shown - but the branch runs ahead of check_safety and
synthesize, so no draft was ever produced.
"""

import pytest

from app.main import build_response


def _result(**overrides):
    """A grounded, fully populated result; override only what a case exercises."""
    base = {
        "final_answer": "Take the warm infusion.",
        "is_emergency": False,
        "is_out_of_scope": False,
        "is_direct_answer": False,
        "is_clarification": False,
        "confidence": "high",
        "resolved_chapter": {"meta": {"chapter": "15", "category_tag": "grahani"}},
        "safety_flags": [],
        "dosha": "vata",
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"is_emergency": True}, id="emergency"),
        pytest.param({"is_out_of_scope": True}, id="scope_refusal"),
        pytest.param({"is_direct_answer": True}, id="direct_answer"),
        pytest.param({"is_clarification": True}, id="clarification"),
    ],
)
def test_paths_that_never_draft_report_zero_attempts(overrides):
    assert build_response(_result(**overrides))["synthesis_attempts"] == 0


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"is_emergency": True}, id="emergency"),
        pytest.param({"is_out_of_scope": True}, id="scope_refusal"),
        pytest.param({"is_direct_answer": True}, id="direct_answer"),
    ],
)
def test_paths_without_retrieval_null_the_citation_fields(overrides):
    response = build_response(_result(**overrides))
    assert response["chapter"] is None
    assert response["category_tag"] is None
    assert response["dosha"] is None
    assert "attribution" not in response


def test_post_retrieval_clarification_keeps_chapter_but_reports_no_draft():
    """The case that separates the two conditions.

    `route_after_retrieve` sends a low-confidence question to `clarify` with a
    real chapter already resolved. That chapter is genuine and must survive;
    the draft it never produced must not be counted.
    """
    response = build_response(
        _result(is_clarification=True, confidence="low", synthesis_attempts=None)
    )
    assert response["chapter"] == "15"
    assert response["category_tag"] == "grahani"
    assert response["is_clarification"] is True
    assert response["synthesis_attempts"] == 0


def test_grounded_answer_defaults_to_one_attempt():
    assert build_response(_result())["synthesis_attempts"] == 1


def test_grounded_answer_reports_the_attempt_node_recorded():
    """A rewritten draft is the only path that may exceed 1."""
    assert build_response(_result(synthesis_attempts=2))["synthesis_attempts"] == 2


def test_direct_answer_never_claims_a_retrieval_backed_confidence():
    response = build_response(_result(is_direct_answer=True, confidence="high"))
    assert response["is_direct_answer"] is True
    assert response["synthesis_attempts"] == 0
    assert "reasoning_trace" not in response