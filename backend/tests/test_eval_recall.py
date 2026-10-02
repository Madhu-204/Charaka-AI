"""Integrity of the verse-level recall probe (``reference/eval_recall_cases.json``).

The probe's whole value rests on its ground truth being *provable* rather than
judged: each case pins one verse by a term occurring in exactly one verse of the
corpus. If that stops being true the scores become meaningless while still
looking plausible, which is the worst failure mode an eval can have.

These tests are therefore mostly guards on the corpus, not on retrieval. A
corpus rebuild that starts mentioning a probe term somewhere else, or drops the
verse that contained it, must fail here rather than quietly re-baselining the
probe.
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

PROBE = BACKEND / "reference" / "eval_recall_cases.json"


@pytest.fixture(scope="module")
def probe():
    if not PROBE.is_file():
        pytest.skip("recall probe missing; run scripts/build_eval_recall_set.py")
    return json.loads(PROBE.read_text(encoding="utf-8"))


def test_probe_is_not_empty(probe):
    assert len(probe) >= 20, f"probe too small to measure anything: {len(probe)} cases"


def test_every_case_names_a_question_and_a_target(probe):
    for item in probe:
        assert item.get("question"), item
        assert item.get("expected_verse_id"), item
        assert item["probe_term"] in item["question"], (
            f"{item['eval_id']}: the probe term must appear in its own question"
        )


def test_eval_ids_are_unique(probe):
    ids = [item["eval_id"] for item in probe]
    assert len(set(ids)) == len(ids), "duplicate eval_id in the probe"


def test_each_case_targets_a_distinct_verse(probe):
    """Two hapax terms can share a verse; keeping both double-counts one hit."""
    targets = [item["expected_verse_id"] for item in probe]
    assert len(set(targets)) == len(targets), (
        f"cases share a target verse, so one retrieval would be scored twice: "
        f"{[t for t, c in Counter(targets).items() if c > 1]}"
    )


def test_probe_targets_spread_across_chapters(probe):
    chapters = {(item["expected_sthana"], item["expected_chapter"]) for item in probe}
    assert len(chapters) >= 8, (
        f"probe is too concentrated in one chapter to generalise: {len(chapters)}"
    )


def test_probe_term_still_identifies_exactly_one_verse(probe, corpus):
    """The load-bearing invariant: one term, one verse.

    This is what makes the expected answer certain instead of a judgement call.
    A corpus rebuild that makes a probe term ambiguous invalidates the case and
    must be caught here.
    """
    for item in probe:
        term = item["probe_term"]
        # Boundaries on BOTH sides. The generator counts whitespace-delimited
        # tokens, so a trailing \b is required to agree with it -- without it
        # this matches "transformation" inside "transformations" and reports a
        # term as ambiguous when the corpus is fine.
        pattern = re.compile(r"\b" + re.escape(term) + r"\b")
        hosts = [
            verse_id
            for verse_id, record in corpus.items()
            if pattern.search((record.get("text_english") or "").lower())
        ]
        assert hosts == [item["expected_verse_id"]], (
            f"{item['eval_id']}: probe term '{term}' now occurs in {hosts}, "
            f"expected only {item['expected_verse_id']}. Regenerate the probe "
            f"with scripts/build_eval_recall_set.py"
        )


def test_probe_cases_are_marked_as_recall(probe):
    for item in probe:
        assert item.get("recall") is True, (
            f"{item['eval_id']} must be flagged recall so summarize() buckets it apart "
            f"from the chapter-level quality sets"
        )


class TestLoader:
    def test_recall_set_is_excluded_by_default(self):
        from app.eval_suite import load_eval_items

        ids = {item["eval_id"] for item in load_eval_items(corner=True)}
        assert not any(i.startswith("rc_") for i in ids), (
            "the probe must be opt-in, or it silently changes the headline score"
        )

    def test_recall_set_loads_on_request(self):
        from app.eval_suite import load_eval_items

        ids = {item["eval_id"] for item in load_eval_items(recall=True)}
        assert any(i.startswith("rc_") for i in ids)

    def test_missing_probe_file_is_tolerated(self, tmp_path, monkeypatch):
        """A fresh clone without the generated probe must still run the eval."""
        import app.eval_suite as suite

        monkeypatch.setattr(suite, "BACKEND", tmp_path)
        (tmp_path / "reference").mkdir()
        (tmp_path / "reference" / "eval_set.json").write_text("[]", encoding="utf-8")
        assert suite.load_eval_items(recall=True) == []


class TestSummarizeBuckets:
    @staticmethod
    def _row(corner=False, recall=False, resolved_hit=True, top_n_hit=True,
             verse_hit=None, top_n_verse_hit=None):
        """A complete row: summarize() reads every one of these keys."""
        return {
            "corner": corner,
            "recall": recall,
            "known_gap": False,
            "resolved_hit": resolved_hit,
            "top_n_hit": top_n_hit,
            "verse_hit": verse_hit,
            "top_n_verse_hit": top_n_verse_hit,
            "emergency": False,
            "expected_emergency": False,
            "herbs_found": [],
            "safety_flags": [],
        }

    def _rows(self):
        return [
            self._row(),
            self._row(corner=True),
            self._row(recall=True, resolved_hit=False, verse_hit=False,
                      top_n_verse_hit=True),
        ]

    def test_probe_cases_are_counted_apart_from_the_quality_sets(self):
        """A probe failure must not read as a core-quality regression."""
        from app.eval_suite import summarize

        s = summarize(self._rows())
        assert s["core"]["total"] == 1
        assert s["corner"]["total"] == 1
        assert s["recall"]["total"] == 1

    def test_recall_reports_verse_level_separately(self):
        from app.eval_suite import summarize

        s = summarize(self._rows())
        assert s["recall"]["verse"] == 0
        assert s["recall"]["verse_top_n"] == 1
        assert s["recall"]["chapter_resolved"] == 0


class TestBM25UnionStaysOff:
    """Guards an unproven experiment, not the shipped behaviour.

    The recall probe exposed that BM25 is restricted to the vector candidates,
    so the lexical half can never contribute a candidate of its own. Letting it
    do so lifts needle recall (2/25 -> 7/25) but drops the core set from 27/28
    to 22/28, so it ships disabled. Neither a BM25-score floor nor a dense-cosine
    gate separates the two regimes -- their distributions overlap -- so the fix
    needs its own design rather than a threshold.

    This test exists so that flipping the flag is a deliberate, measured act
    rather than an environment-variable accident.
    """

    def test_union_is_disabled_by_default(self, retriever):
        import os

        assert "CHARAKA_BM25_UNION" not in os.environ or os.environ.get(
            "CHARAKA_BM25_UNION"
        ) == "0", (
            "CHARAKA_BM25_UNION regresses the core set; unset it"
        )
        assert retriever.BM25_UNION_ENABLED is False

    def test_lookups_exist_for_lexical_only_candidates(self, retriever):
        """BM25-union candidates arrive with no vector result, so they need text."""
        assert len(retriever._DOC_BY_ID) == len(retriever._EMBED)
        assert len(retriever._META_BY_ID) == len(retriever._EMBED)
        for verse_id in list(retriever._EMBED)[:5]:
            assert isinstance(retriever._DOC_BY_ID[verse_id], str)
            assert retriever._DOC_BY_ID[verse_id]
            assert "sthana" in retriever._META_BY_ID[verse_id]