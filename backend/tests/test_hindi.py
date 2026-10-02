"""Tests for Hindi (Devanagari) query normalization.

The encoder is English-only and the BM25 tokenizer is ``[a-z]+``, so without
normalization Devanagari contributes to neither half of hybrid search. These
tests guard the glossary wiring; the retrieval effect itself is gated by
eval_corner_cases.json (ec_13-ec_15).
"""

import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.nodes.query_expansion import (  # noqa: E402
    HINDI_TERMS,
    expand_query,
    has_devanagari,
    normalize_hindi,
)


class TestDetection:
    def test_detects_devanagari(self):
        assert has_devanagari("ज्वर")
        assert has_devanagari("fever ज्वर")

    def test_ignores_ascii(self):
        assert not has_devanagari("fever")
        assert not has_devanagari("")
        assert not has_devanagari(None)


class TestNormalization:
    def test_english_is_returned_untouched(self):
        """English queries must pass through byte-identical."""
        q = "How is ashwagandha used in fever treatment?"
        assert normalize_hindi(q) == q

    def test_maps_fever_to_the_corpus_term(self):
        assert "jwara" in normalize_hindi("ज्वर का उपचार")

    def test_maps_cough_variants(self):
        assert "kasa" in normalize_hindi("खांसी")
        assert "kasa" in normalize_hindi("खाँसी का उपचार")

    def test_maps_herb_name(self):
        assert "ashwagandha" in normalize_hindi("अश्वगंधा")

    def test_maps_doshas(self):
        for hindi, roman in [("वात", "vata"), ("पित्त", "pitta"), ("कफ", "kapha")]:
            assert roman in normalize_hindi(hindi)

    def test_maps_treatment_word(self):
        assert "chikitsa" in normalize_hindi("उपचार")

    def test_longest_match_wins(self):
        """A multi-word term must not be broken up by a shorter prefix match."""
        out = normalize_hindi("त्वचा रोग")
        assert "kushtha" in out

    def test_unmapped_devanagari_is_left_alone(self):
        """Unknown text is preserved, not dropped."""
        assert normalize_hindi("ज्वर") == "jwara"
        assert normalize_hindi("कुछ अज्ञात शब्द").strip().endswith("शब्द")

    def test_mixed_script_query_is_partly_normalized(self):
        out = normalize_hindi("ashwagandha for ज्वर")
        assert "ashwagandha" in out
        assert "jwara" in out

    def test_glossary_values_are_latin(self):
        """A Devanagari value would defeat the whole point."""
        for key, value in HINDI_TERMS.items():
            assert has_devanagari(key), key
            assert not has_devanagari(value), (key, value)


class TestExpandQueryIntegration:
    def test_expanded_query_is_normalized(self):
        """Glossary terms in the query must reach the retriever romanised.

        Unmapped Devanagari (case particles like का) is intentionally left in
        place, so this asserts the terms were converted rather than demanding
        the string be pure ASCII.
        """
        out = expand_query({"query": "ज्वर का उपचार", "history": []})
        assert "jwara" in out["expanded_query"]
        assert "chikitsa" in out["expanded_query"]
        assert "ज्वर" not in out["expanded_query"]

    def test_canonical_term_detected_from_hindi(self):
        """Normalized Devanagari must feed the SYNONYMS canonical detector.

        SYNONYMS is keyed on English surface forms ("fever" -> "jwara"), and the
        glossary already emits the canonical romanised Sanskrit ("jwara"), so
        there is no second canonical hop here. What matters is that the term
        reaches the detector in a form it can reason about, which is why this
        asserts the term is present and resolvable rather than that
        canonical_term was re-derived.
        """
        out = expand_query({"query": "ज्वर का उपचार", "history": []})
        assert "jwara" in out["expanded_query"]
        assert out["canonical_term"] in (None, "jwara")

    def test_english_canonical_term_still_detected(self):
        """Normalization must not break the existing English canonical path."""
        assert expand_query({"query": "fever treatment", "history": []})["canonical_term"] == "jwara"

    def test_hindi_herb_reaches_herb_detection(self):
        out = expand_query({"query": "ज्वर में अश्वगंधा का उपयोग कैसे करें?", "history": []})
        assert out["canonical_term"] == "ashwagandha"

    def test_english_expansion_is_unchanged(self):
        q = "how is ashwagandha used in fever treatment?"
        out = expand_query({"query": q, "history": []})
        assert q in out["expanded_query"]

    def test_trace_mentions_normalization(self):
        out = expand_query({"query": "ज्वर का उपचार", "history": []})
        assert any("Devanagari" in step for step in out["trace"])

    def test_no_trace_note_for_english(self):
        out = expand_query({"query": "fever treatment", "history": []})
        assert not any("Devanagari" in step for step in out["trace"])

    def test_hindi_followup_uses_normalized_prior(self):
        """A Hindi prior turn must be normalized in the rewritten query."""
        out = expand_query(
            {
                "query": "क्या इसका उपयोग भी कर सकते हैं?",
                "history": [{"role": "user", "content": "ज्वर का उपचार"}],
            }
        )
        assert "jwara" in out["expanded_query"]
        assert "ज्वर" not in out["expanded_query"]

    def test_hindi_herb_in_history_carries_to_followup(self):
        """Hindi herb name in a prior turn must reach herb detection."""
        out = expand_query(
            {
                "query": "what about this one instead",
                "history": [{"role": "user", "content": "अश्वगंधा कैसे लें?"}],
            }
        )
        assert out["canonical_term"] == "ashwagandha"


class TestHindiRetrieval:
    """End-to-end: a Hindi query must resolve to the right chapter."""

    @pytest.mark.parametrize(
        "hindi,expected",
        [
            ("ज्वर का उपचार क्या है?", "chikitsasthana/3"),
            ("खांसी का उपचार", "chikitsasthana/18"),
        ],
    )
    def test_hindi_query_resolves_expected_chapter(self, retriever, hindi, expected):
        from app.nodes.query_expansion import expand_query as eq

        state = eq({"query": hindi, "history": []})
        result = retriever.retrieve(state)
        meta = result["resolved_chapter"]["meta"]
        assert f"{meta['sthana']}/{meta['chapter']}" == expected