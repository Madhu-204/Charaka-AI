"""Emergency gate regression tests.

The gate was English-only literal substring matching, so 16/16 realistic red-flag
phrasings (Hindi, Hinglish, clinical synonyms, punctuation variants) passed
straight through to verse retrieval. These tests lock in the fix and guard the
deliberate informational exemption so the fix cannot become over-eager.

Every probe here was an observed miss, not a hypothetical.
"""

import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.nodes.emergency import EMERGENCY_MESSAGE, check_emergency  # noqa: E402


def gate(q):
    return check_emergency({"query": q, "history": [], "trace": []})


# --- the 16 observed misses -------------------------------------------------
MUST_REDIRECT = [
    # Hindi
    ("दिल का दर्द", "chest pain"),
    ("सीने में दर्द हो रहा है", "chest pain"),
    ("सांस नहीं लग रही", "cannot breathe"),
    ("बेहोश हो गया", "unconscious"),
    ("मुझे आत्महत्या का विचार हो रहा है", "suicidal ideation"),
    ("मेरी सांस नहीं चल रही", "cannot breathe"),
    ("चेहरा टेढ़ा हो गया है", "facial droop"),
    # Hinglish
    ("mujhe dil dard ho raha hai", "chest pain"),
    ("saans nahi chal rahi", "cannot breathe"),
    ("main behosh ho gaya", "unconscious"),
    ("khoon beh raha hai bahut zyada", "severe bleeding"),
    # clinical synonyms that were missing
    ("I think I am having a cardiac arrest", "cardiac arrest"),
    ("he is having a heart attack", "heart attack"),
    ("I passed out this morning", "loss of consciousness"),
    ("the child is choking", "choking"),
    ("my friend took an overdose", "overdose"),
    ("I had an anaphylactic reaction", "anaphylaxis"),
    # punctuation variants
    ("I have chest-pain radiating to my arm", "hyphenated"),
    ("I can't feel my arm", "one-sided numbness"),
    ("I have chest pain", "plain English still works"),
]


class TestMustRedirect:
    @pytest.mark.parametrize("query,label", MUST_REDIRECT, ids=[m for _, m in MUST_REDIRECT])
    def test_red_flag_redirects(self, query, label):
        out = gate(query)
        assert out["is_emergency"] is True, f"failed to redirect: {label} ({query!r})"
        assert out["final_answer"] == EMERGENCY_MESSAGE
        assert out["emergency_reason"]

    def test_every_flag_has_a_reason(self):
        for query, _ in MUST_REDIRECT:
            assert gate(query)["emergency_reason"], query

    def test_trace_records_the_flag(self):
        out = gate("मुझे दिल का दर्द हो रहा है")
        assert any("RED_FLAG" in s for s in out["trace"])


class TestInformationalExemption:
    """Study questions must NOT redirect - over-triage is also a defect."""

    MUST_NOT_REDIRECT = [
        "What are the symptoms of a heart attack?",
        "How does Charaka describe stroke?",
        "What does chest pain mean in Ayurveda?",
        "What are the remedies for seizure according to Charaka?",
        "चरक संहिता में हृदयाघात के लक्षण क्या हैं?",
        "क्या दिल का दर्द आयुर्वेद में बताया गया है?",
        "What are the signs of unconsciousness in classical texts?",
    ]

    @pytest.mark.parametrize("query", MUST_NOT_REDIRECT)
    def test_informational_not_redirected(self, query):
        out = gate(query)
        assert out["is_emergency"] is False, f"over-triaged a study question: {query!r}"
        assert out["final_answer"] is None

    def test_first_person_defeats_exemption(self):
        """Interrogative + first person is a symptom report, not a study question."""
        out = gate("I have chest pain, what should I do?")
        assert out["is_emergency"] is True


class TestWellnessQueriesUnaffected:
    """The gate must not fire on ordinary Charaka questions."""

    SAFE = [
        "What does Charaka say about shatavari as a rejuvenator?",
        "Which herbs are used for purgation and emesis?",
        "What does rasa (taste) tell us about digestion?",
        "How is ashwagandha used in fever treatment?",
        "खांसी का उपचार",
        "ज्वर में अश्वगंधा का उपयोग कैसे करें?",
        "Explain the six tastes",
        "What is triphala?",
        "I have a mild cold, what does Charaka recommend?",
        "Tell me about guduchi benefits",
    ]

    @pytest.mark.parametrize("query", SAFE)
    def test_wellness_query_not_redirected(self, query):
        out = gate(query)
        assert out["is_emergency"] is False, f"false positive on: {query!r}"


class TestDualPurposeSymptoms:
    """Symptom nouns that are ALSO legitimate Charaka topic terms.

    topics.json maps 'shortness of breath', 'difficulty breathing', 'wheezing'
    and 'breathlessness' to the respiratory category (Hikka-Shwasa). Treating
    them as unconditional red flags refused a real category, so they gate only
    when a person is actually reporting the symptom.
    """

    TOPIC_TERMS = [
        "shortness of breath",
        "difficulty breathing",
        "breathlessness",
        "wheezing",
    ]

    @pytest.mark.parametrize("term", TOPIC_TERMS)
    def test_bare_topic_term_not_redirected(self, term):
        assert gate(term)["is_emergency"] is False, f"refused a topic term: {term!r}"

    @pytest.mark.parametrize("term", TOPIC_TERMS)
    def test_topic_framing_not_redirected(self, term):
        assert gate(f"herbs for {term}")["is_emergency"] is False
        assert gate(f"what does Charaka say about {term}")["is_emergency"] is False

    @pytest.mark.parametrize("term", TOPIC_TERMS)
    def test_first_person_report_redirects(self, term):
        out = gate(f"I have {term}")
        assert out["is_emergency"] is True, f"missed a reported symptom: {term!r}"

    def test_request_for_help_redirects(self):
        assert gate("my chest is hurting and I can't breathe")["is_emergency"] is True


class TestNormalization:
    def test_apostrophe_variants_equivalent(self):
        assert gate("I can't breathe")["is_emergency"]
        assert gate("I cant breathe")["is_emergency"]
        assert gate("I can\u2019t breathe")["is_emergency"]

    def test_punctuation_tolerated(self):
        assert gate("severe-bleeding!")["is_emergency"]
        assert gate("CHEST PAIN")["is_emergency"]

    def test_extra_whitespace_tolerated(self):
        assert gate("I  have   chest   pain")["is_emergency"]

    def test_empty_query_safe(self):
        out = gate("")
        assert out["is_emergency"] is False
        assert out["final_answer"] is None

    def test_trace_appended_to_existing(self):
        out = check_emergency({"query": "chest pain", "trace": ["step1"]})
        assert out["trace"][0] == "step1"
        assert len(out["trace"]) == 2

    def test_returns_expected_keys(self):
        """Callers depend on these keys; keep the contract stable."""
        for q in ("chest pain", "what is rasa"):
            out = gate(q)
            assert "is_emergency" in out
            assert "trace" in out


class TestNoDegenerateFlags:
    def test_no_empty_normalized_flag(self):
        """An empty flag would match every query."""
        from app.nodes.emergency import NORMALIZED_FLAGS

        for orig, norm in NORMALIZED_FLAGS:
            assert norm, f"flag normalizes to empty string: {orig!r}"

    def test_flags_are_normalized_consistently(self):
        from app.nodes.emergency import NORMALIZED_FLAGS, _norm

        for orig, norm in NORMALIZED_FLAGS:
            assert norm == _norm(orig), orig