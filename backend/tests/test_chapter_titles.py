"""Tests for chapter-title extraction and the parent-context prefix.

The regression cases here are the two real bugs found while building this:
a closing-quote set that only knew the *opening* forms leaked quote characters
into stored titles, and an apostrophe heuristic broad enough to treat the
terminator in ``...of Vata"`` as an in-word apostrophe.
"""

import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from scripts.build_chapter_titles import parse_title  # noqa: E402


class TestParseTitle:
    def test_curly_double_quotes(self):
        assert (
            parse_title(
                "We shall now expound the chapter entitled "
                "\u201cThe Quest for Longevity.\u201d"
            )
            == "The Quest for Longevity"
        )

    def test_curly_single_quotes(self):
        assert (
            parse_title(
                "We shall now expound the chapter entitled "
                "\u2018The therapeutics of Fever [jvara-cikitsa].\u2019"
            )
            == "The therapeutics of Fever [jvara-cikitsa]"
        )

    def test_regression_closing_quote_after_letter(self):
        """A terminator directly after a letter is still a terminator.

        This is the case an over-eager "quote after a letter means possessive"
        rule silently broke, leaving a stray quote glued to the title.
        """
        raw = (
            "We shall now expound the chapter entitled "
            "\u201cThe Salutary and the Unsalutary influences of Vata\u201d."
        )
        title = parse_title(raw)
        assert title == "The Salutary and the Unsalutary influences of Vata"
        assert "\u201d" not in title
        assert "\u201c" not in title

    def test_possessive_inside_title_is_preserved(self):
        """An apostrophe between two letters is content, not a terminator."""
        raw = (
            "We shall now expound the chapter entitled \u2018The Continuation of "
            "one\u2019s Lineage [i.e., jatisutriya/jati-sutra]\u2019 in the Section "
            "on Human Embodiment."
        )
        title = parse_title(raw)
        assert title.startswith("The Continuation of one\u2019s Lineage")
        # It must stop at the real terminator, not run on into the next clause.
        assert "Section on Human Embodiment" not in title

    def test_suffix_after_quote_is_excluded(self):
        raw = (
            "We shall now expound the chapter entitled \u2018The Continuation of "
            "one\u2019s Lineage\u2019 in the Section on Human Embodiment."
        )
        assert parse_title(raw) == "The Continuation of one\u2019s Lineage"

    def test_ascii_quotes(self):
        assert (
            parse_title('We shall now expound the chapter entitled "Six hundred purgative preparations".')
            == "Six hundred purgative preparations"
        )

    def test_non_title_verse_returns_none(self):
        """A chapter that opens with content has no title to extract."""
        assert parse_title("Inappetence, 2. Torpor 3. Hypersomnia 4. Stiffness") is None

    def test_missing_phrase_returns_none(self):
        assert parse_title("The earth is vast and provides the finest dwelling") is None

    def test_empty_input_returns_none(self):
        assert parse_title("") is None
        assert parse_title(None) is None

    def test_no_delimiter_leaks_at_the_edges(self):
        """Whatever comes back must be cleanly delimited.

        A cheap invariant that would have caught both original bugs without
        needing to know the specific corpus strings. Interior apostrophes are
        allowed, so only the edges are asserted.
        """
        samples = [
            "We shall now expound the chapter entitled \u201cA title.\u201d",
            "We shall now expound the chapter entitled \u2018Another one.\u2019",
            'We shall now expound the chapter entitled \u201cA third one"\u201d',
            "We shall now expound the chapter entitled \u2018Bob\u2019s chapter\u2019",
        ]
        delimiters = "\u201c\u201d\u2018\u2019\"'"
        for raw in samples:
            title = parse_title(raw)
            assert title, raw
            assert title[0] not in delimiters, (raw, title)
            assert title[-1] not in delimiters, (raw, title)


class TestChapterTitlesArtifact:
    def test_no_title_starts_or_ends_with_a_delimiter(self, titles):
        """A title must not begin or end on a quote character.

        Interior apostrophes are legitimate content ("one's Lineage"), so the
        invariant is about the edges, where a quote can only be a parsing
        artifact.
        """
        assert titles, "no chapter titles parsed"
        delimiters = "\u201c\u201d\u2018\u2019\"'"
        for key, title in titles.items():
            assert "/" in key, key
            assert title, key
            assert title[0] not in delimiters, (key, title)
            assert title[-1] not in delimiters, (key, title)
            assert len(title.strip()) >= 4, (key, title)

    def test_titles_cover_most_chapters(self, titles, corpus):
        chapters = {(r["sthana"], int(r["chapter"])) for r in corpus.values()}
        # One chapter (sutrasthana/20) legitimately opens with a numbered list
        # and has no title verse, so 19/20 is the expected ceiling.
        assert len(titles) >= len(chapters) - 1, (len(titles), len(chapters))


class TestChapterContext:
    def test_prefix_ends_with_a_space(self):
        from app.chunking import chapter_context

        rec = {
            "sthana": "chikitsasthana",
            "chapter": 3,
            "traditional_condition": "Jwara",
            "category_tag": "fever_acute",
        }
        prefix = chapter_context(rec)
        assert prefix.endswith(" "), repr(prefix)

    def test_prefix_names_the_chapter_and_title(self):
        from app.chunking import chapter_context

        rec = {
            "sthana": "sutrasthana",
            "chapter": 1,
            "traditional_condition": "foundational dosha",
            "category_tag": "foundational_dosha",
        }
        prefix = chapter_context(rec)
        assert "sutrasthana/1" in prefix
        assert "Longevity" in prefix

    def test_prefix_never_says_none(self):
        """Chroma stores missing enums as the string "none".

        That sentinel must not leak into the indexed text, or every verse in an
        untagged chapter gains a meaningless "none" token that BM25 will score.
        """
        from app.chunking import chapter_context

        rec = {
            "sthana": "sutrasthana",
            "chapter": 20,
            "traditional_condition": None,
            "category_tag": "none",
        }
        prefix = chapter_context(rec)
        assert "none" not in prefix.lower().replace("nonetheless", "")

    def test_missing_metadata_yields_empty_prefix(self):
        from app.chunking import chapter_context

        assert chapter_context({}) == ""
        assert chapter_context({"sthana": None, "chapter": None}) == ""

    def test_embed_document_keeps_verse_text_intact(self):
        """The prefix is prepended, and the verse text is still fully present."""
        from app.chunking import embed_document

        rec = {
            "sthana": "sutrasthana",
            "chapter": 1,
            "traditional_condition": "foundational dosha",
            "category_tag": "foundational_dosha",
            "text_english": "Samavaya is defined as that inseparable relationship.",
        }
        out = embed_document(rec)
        assert out.endswith(rec["text_english"])
        assert "Longevity" in out

    def test_embed_document_handles_blank_text(self, corpus):
        from app.chunking import embed_document

        out = embed_document({"sthana": "sutrasthana", "chapter": 1, "text_english": ""})
        assert isinstance(out, str)


class TestFreshness:
    """The index is regenerated, not committed, so staleness must be visible."""

    def test_corpus_hash_is_stable_and_nonempty(self):
        from app.chunking import corpus_sha256

        first = corpus_sha256()
        assert first, "corpus hash empty"
        assert first == corpus_sha256(), "hash is not deterministic"

    def test_missing_file_yields_empty_hash(self, tmp_path):
        from app.chunking import corpus_sha256

        assert corpus_sha256(tmp_path / "nope.json") == ""

    def test_hash_changes_when_bytes_change(self, tmp_path):
        from app.chunking import corpus_sha256

        target = tmp_path / "corpus.json"
        target.write_text('{"a": 1}', encoding="utf-8")
        first = corpus_sha256(target)
        target.write_text('{"a": 2}', encoding="utf-8")
        assert corpus_sha256(target) != first

    def test_index_reports_ok_when_it_matches(self, retriever):
        from app.chunking import index_freshness

        result = index_freshness(retriever.collection)
        assert result["status"] in {"ok", "unknown"}, result
        if result["status"] == "ok":
            assert result["corpus_sha256"] == result["index_sha256"]

    def test_index_carries_a_corpus_hash(self, retriever):
        stored = (retriever.collection.metadata or {}).get("corpus_sha256")
        assert stored, "index was built without stamping corpus_sha256"

    def test_index_detects_staleness(self, retriever):
        from app.chunking import index_freshness

        result = index_freshness(retriever.collection)
        if result["status"] == "stale":
            assert "build_vector_store" in result["detail"]
        else:
            assert result["status"] == "ok", result

    def test_freshness_never_raises_on_a_broken_collection(self):
        from app.chunking import index_freshness

        class Broken:
            @property
            def metadata(self):
                raise RuntimeError("boom")

            def count(self):
                raise RuntimeError("boom")

        assert index_freshness(Broken())["status"] == "unknown"

    def test_none_collection_is_handled(self):
        from app.chunking import index_freshness

        assert index_freshness(None)["status"] == "unknown"