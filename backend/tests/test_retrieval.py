"""Tests for the retrieval internals: BM25 scoring, metadata filters, fusion.

These guard the behaviour that was measured rather than assumed, including one
real trap: on Chroma 1.5.9 a ``$contains`` clause against a *string* metadata
field does not raise -- it silently returns an empty result set. Herb filtering
that leans on it would look correct in tests and return nothing in production,
so the boolean-key approach is asserted explicitly.
"""

import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.nodes.tool_router import _and_clauses, _topic_clauses, detect_topic  # noqa: E402


class TestBM25:
    def test_ranks_the_document_containing_the_term_first(self, retriever):
        results = retriever.BM25_INDEX.search("purgative preparations", top=5)
        assert results, "no BM25 hits for a term known to be in the corpus"
        top_doc = retriever.BM25_INDEX.tokens[retriever.BM25_INDEX.ids.index(results[0][0])]
        assert any("purg" in tok for tok in top_doc)

    def test_scores_are_non_increasing(self, retriever):
        scores = [s for _, s in retriever.BM25_INDEX.search("taste rasa", top=10)]
        assert scores == sorted(scores, reverse=True)

    def test_unknown_term_yields_nothing(self, retriever):
        assert retriever.BM25_INDEX.search("zzzqqxnotaterm", top=5) == []

    def test_restrict_narrows_to_the_given_ids(self, retriever):
        allowed = retriever.BM25_INDEX.ids[:5]
        results = retriever.BM25_INDEX.search("taste", top=10, restrict=allowed)
        assert {vid for vid, _ in results} <= set(allowed)

    def test_restrict_to_empty_set_returns_nothing(self, retriever):
        assert retriever.BM25_INDEX.search("taste", top=10, restrict=[]) == []

    def test_index_is_built_over_context_enriched_text(self, retriever):
        """BM25 must see the same text the vector index was built from.

        Otherwise the lexical half of hybrid search scores bare verse text while
        the vector half scores text-plus-chapter-context, and fusion mixes two
        different notions of relevance.
        """
        # Find a chapter title that BM25 should now match.
        hits = retriever.BM25_INDEX.search("Quest for Longevity", top=50)
        assert hits, "chapter title is absent from the BM25 corpus"

    def test_title_verse_text_is_still_clean_in_the_index(self, retriever):
        """The stored document must NOT carry the 'Charaka Samhita, ...' prefix.

        The prefix is for matching only. Citation cards, attribution and the
        synthesis prompt read the stored text, so a leaked prefix would show up
        in the UI as if it were part of the verse.
        """
        docs = retriever._ALL["documents"]
        leaked = [d for d in docs if isinstance(d, str) and d.startswith("Charaka Samhita,")]
        assert not leaked, f"{len(leaked)} stored documents carry the index-time prefix"


class TestMetadataFilters:
    def test_single_clause_is_a_bare_dict(self):
        """Chroma rejects an $and holding fewer than two clauses."""
        assert _and_clauses([{"category_tag": "fever_acute"}]) == {"category_tag": "fever_acute"}

    def test_two_clauses_are_wrapped_in_and(self):
        out = _and_clauses([{"a": 1}, {"b": 2}])
        assert out == {"$and": [{"a": 1}, {"b": 2}]}

    def test_empty_clause_list_is_an_empty_dict(self):
        assert _and_clauses([]) == {}
        assert _and_clauses([None, None]) == {}

    def test_one_top_level_operator_only(self):
        """Nesting two $ands is invalid; the clauses must be flattened."""
        out = _and_clauses([{"$and": [{"a": 1}]}, {"b": 2}])
        assert "$and" in out
        inner = out["$and"]
        assert all("$and" not in clause for clause in inner)

    def test_topic_clauses_constrain_condition_when_present(self):
        clauses = _topic_clauses("fever_acute")
        assert {"category_tag": "fever_acute"} in clauses
        assert any("traditional_condition" in c for c in clauses)

    def test_filter_is_chroma_accepted(self, retriever):
        """The generated filter must actually be accepted by the live store."""
        from app.nodes.tool_router import _topic_filter

        where = _topic_filter("fever_acute")
        found = retriever.collection.get(where=where, limit=5)
        assert found["ids"], "filter matched nothing against the real corpus"


class TestChromaContainsTrap:
    def test_contains_on_string_metadata_returns_empty(self, retriever):
        """Documents the Chroma 1.5.9 behaviour that makes $contains unusable.

        String `$contains` neither raises nor matches, so herb filtering written
        against a comma-joined ``herbs_mentioned`` string would silently degrade
        to zero results. Boolean metadata keys are the supported alternative and
        are asserted to work right after.
        """
        col = retriever.collection
        # Scan for a verse that actually names herbs; verse #1 usually has none.
        sample = col.get(limit=200, include=["metadatas"])
        herbs = ""
        for meta in sample["metadatas"]:
            value = (meta.get("herbs_mentioned") or "").strip()
            if value and value != "none":
                herbs = value
                break
        if not herbs:
            pytest.skip("no verse with herbs found in the corpus sample")

        by_contains = col.get(where={"herbs_mentioned": {"$contains": herbs}}, limit=5)
        assert by_contains["ids"] == [], (
            "expected the documented $contains limitation on string metadata; "
            "if this now matches, Chroma behaviour changed and herb filtering "
            "should be revisited"
        )


class TestFusion:
    def test_minmax_is_bounded(self, retriever):
        out = retriever._minmax([0.1, 0.5, 0.9])
        assert out == pytest.approx([0.0, 0.5, 1.0])

    def test_minmax_handles_identical_values(self, retriever):
        assert retriever._minmax([0.7, 0.7, 0.7]) == pytest.approx([0.5, 0.5, 0.5])

    def test_minmax_of_single_value(self, retriever):
        assert retriever._minmax([0.3]) == pytest.approx([0.5])

    def test_cosine_of_identical_vectors_is_one(self, retriever):
        vec = [0.3, 0.4, 0.5]
        assert retriever._cosine(vec, vec) == pytest.approx(1.0)

    def test_cosine_of_orthogonal_vectors_is_zero(self, retriever):
        assert retriever._cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_confidence_band_thresholds(self, retriever):
        assert retriever._confidence_band(0.9) == "high"
        assert retriever._confidence_band(0.5) == "medium"
        assert retriever._confidence_band(0.1) == "low"


class TestCompoundDecomposition:
    def test_splits_on_and(self, retriever):
        subs = retriever._decompose_compound("bloating and insomnia")
        assert subs and len(subs) >= 2

    def test_single_clause_yields_none(self, retriever):
        assert retriever._decompose_compound("bloating only") is None

    def test_needs_two_known_terms(self, retriever):
        assert retriever._decompose_compound("foo and bar") is None