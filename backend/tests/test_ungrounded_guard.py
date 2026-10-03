"""An answer that cites nothing must not read as authoritative.

Grounding checks citation *structure*. When it finds no usable marker it asks for
a rewrite, but the retry has a budget, and once that budget is spent the draft
ships regardless. Before this guard, that produced the worst output the system can
emit: fluent prose in Charaka's voice, asserting what the text says, pointing at
nothing — a failure a reader has no way to detect.

These tests pin the contract:

* the answer still ships, because the retrieved context was usually relevant and
  discarding it helps nobody;
* it is marked `is_ungrounded`, and `confidence` is forced to "low" whatever the
  drafting claimed;
* the flag describes the answer the user receives, so a rewrite that cites
  properly clears it;
* terminal paths that never retrieved anything are not mislabelled as ungrounded.
"""

import pytest

from app.main import build_response
from app.nodes.grounding import grounding


def _state(**over):
    base = {
        "final_answer": "Charaka describes this pattern as requiring oleation and sudation.",
        "retrieved": [{"verse_id": "cs_x_1_1-2", "text": "verse one"}, {"verse_id": "cs_x_2_3", "text": "verse two"}],
        "confidence": "high",
        "trace": [],
    }
    base.update(over)
    return base


# --- the grounding node reports the condition -------------------------------


def test_reports_ungrounded_when_the_draft_cites_nothing():
    out = grounding(_state(final_answer="Charaka says this plainly, with no marker."))
    assert out["grounding_ungrounded"] is True
    assert out["grounding_retry_instruction"]  # a rewrite is still worth trying


def test_not_ungrounded_when_a_citation_resolves():
    out = grounding(_state(final_answer="Verse one says so [1]."))
    assert out["grounding_ungrounded"] is False


def test_out_of_range_markers_do_not_count_as_grounded():
    """A marker pointing past the retrieved set is an invented citation.

    It is the worst case rather than a missing one: the answer looks cited, and
    the number resolves to a verse the reader cannot check.
    """
    out = grounding(_state(final_answer="Charaka says so [9]."))
    assert out["grounding_ungrounded"] is True
    assert out["grounding_cited"] == []


def test_ungrounded_when_nothing_was_retrieved_at_all():
    out = grounding(_state(retrieved=[], final_answer="Charaka says so."))
    assert out["grounding_ungrounded"] is True


def test_does_not_override_a_rewrite_that_fixed_the_citations():
    """The flag describes the shipped answer, not the first attempt.

    Grounding runs again after the retry, so a corrected draft reports its own
    result. This is what stops every retried answer from being permanently
    branded ungrounded by its first draft's failure.
    """
    out = grounding(_state(final_answer="Now correctly cited [1]."))
    assert out["grounding_ungrounded"] is False
    assert out["grounding_retry_instruction"] is None


# --- the response reflects it ----------------------------------------------


def _response(**over):
    base = {
        "final_answer": "Charaka describes this pattern as requiring oleation and sudation.",
        "is_emergency": False,
        "is_out_of_scope": False,
        "is_direct_answer": False,
        "is_clarification": False,
        "confidence": "high",
        "resolved_chapter": {"meta": {"chapter": "15", "category_tag": "grahani"}},
        "safety_flags": [],
        "dosha": "vata",
        "grounding_ungrounded": True,
    }
    base.update(over)
    return build_response(base)


def test_ungrounded_answer_is_flagged_and_confidence_is_forced_low():
    response = _response()
    assert response["is_ungrounded"] is True
    # The drafting asked for "high". That claim is exactly what failed.
    assert response["confidence"] == "low"
    assert response["grounding"]["ungrounded"] is True


def test_the_answer_is_still_returned():
    """Discarding a weakly-grounded draft throws away real retrieved context.

    The failure was in the drafting, not the retrieval, and the user is better
    served by an honest weak answer than by nothing.
    """
    assert _response()["answer"].startswith("Charaka describes")


@pytest.mark.parametrize("confidence", ["high", "medium"])
def test_confidence_is_forced_low_whatever_the_draft_claimed(confidence):
    assert _response(confidence=confidence)["confidence"] == "low"


def test_a_well_grounded_answer_is_untouched():
    response = _response(grounding_ungrounded=False)
    assert response["is_ungrounded"] is False
    assert response["confidence"] == "high"


@pytest.mark.parametrize(
    "over",
    [
        pytest.param({"is_emergency": True}, id="emergency"),
        pytest.param({"is_out_of_scope": True}, id="scope_refusal"),
        pytest.param({"is_direct_answer": True}, id="direct_answer"),
    ],
)
def test_terminal_paths_are_not_branded_ungrounded(over):
    """A greeting never retrieves a verse, so "cites nothing" is not a defect.

    Without this the new flag would fire on every direct reply and every refusal,
    training users to ignore the one signal that should be rare.
    """
    response = _response(**over)
    assert response["is_ungrounded"] is False