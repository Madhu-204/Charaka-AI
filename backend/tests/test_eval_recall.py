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
    assert len(probe) >= 100, f"probe too small to measure anything: {len(probe)} cases"


def test_probe_covers_every_chapter_evenly(probe, corpus):
    """Uneven coverage would weight dense chapters over the rest of the corpus."""
    from collections import Counter

    in_corpus = {
        (r["sthana"], r["chapter"]) for r in corpus.values()
    }
    counts = Counter((x["expected_sthana"], x["expected_chapter"]) for x in probe)
    missing = in_corpus - set(counts)
    assert not missing, f"chapters absent from the probe: {sorted(missing, key=str)}"
    assert len(set(counts.values())) == 1, (
        f"uneven chapter coverage: {sorted(set(counts.values()))}"
    )


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


def _token_bigrams(text: str) -> set:
    """Mirror the generator's tokenisation exactly.

    The generator splits on ``[a-z]+`` and rejoins with spaces, so a hyphenated
    compound like ``abdomen-misperistalsis`` becomes the phrase
    ``abdomen misperistalsis``. Checking for a literal substring instead would
    fail on those, and checking only the first word would not prove anything.
    Matching the generator's own tokenisation is what makes this a real test of
    the invariant rather than a test of punctuation.
    """
    words = re.findall(r"[a-z]+", text.lower())
    return {" ".join(words[i : i + 2]) for i in range(len(words) - 1)}


def test_probe_term_still_identifies_exactly_one_verse(probe, corpus):
    """The load-bearing invariant: one phrase, one verse.

    This is what makes the expected answer certain instead of a judgement call.
    A corpus rebuild that makes a probe phrase ambiguous invalidates the case
    and must be caught here.
    """
    for item in probe:
        term = item["probe_term"]
        hosts = [
            verse_id
            for verse_id, record in corpus.items()
            if term in _token_bigrams(record.get("text_english") or "")
        ]
        assert hosts == [item["expected_verse_id"]], (
            f"{item['eval_id']}: probe phrase '{term}' now occurs in {hosts}, "
            f"expected only {item['expected_verse_id']}. Regenerate the probe "
            f"with scripts/build_eval_recall_set.py"
        )


def test_probe_phrases_are_substantive(probe):
    """Two real words each.

    A single hapax *word* is not evidence of domain vocabulary in a 2,490-verse
    corpus -- "actually" and "absolute" each occur once. The phrase form is what
    makes the probe selective, so a regression to single words should fail here
    rather than quietly reintroduce common English.
    """
    for item in probe:
        words = item["probe_term"].split()
        assert len(words) == 2, f"{item['eval_id']}: probe term is not a bigram"
        assert all(len(w) >= 5 for w in words), (
            f"{item['eval_id']}: probe term {item['probe_term']!r} has a stub token"
        )


def test_probe_questions_are_not_one_repeated_template(probe):
    """Twenty question shapes over five templates, so phrasing is not a constant."""
    assert len({x["question"] for x in probe}) == len(probe), "duplicate question"
    shapes = {x["question"].split("?")[0] for x in probe}
    assert len(shapes) >= 5, f"only {len(shapes)} question shapes"


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

    def test_intervals_bracket_the_observed_rate(self):
        """The interval is what stops a small probe being over-read."""
        from app.eval_suite import summarize

        s = summarize(self._rows())
        for bucket, key in ((s["recall"], "verse_ci"), (s["recall"], "verse_top_n_ci")):
            low, high = bucket[key]
            assert low <= high
        low, high = s["recall"]["verse_ci"]
        assert low == 0.0 and high > 0.0, "0/1 must not collapse to a zero-width interval"


class TestWilson:
    def test_contains_the_point_estimate(self):
        from app.eval_suite import _wilson

        for hits, total in ((0, 10), (1, 10), (5, 10), (9, 10), (10, 10), (3, 25)):
            low, high = _wilson(hits, total)
            assert low <= 100 * hits / total <= high, (hits, total, low, high)

    def test_stays_nonzero_width_at_the_extremes(self):
        """Normal approximation collapses to [0,0] at 0/n, which is wrong."""
        from app.eval_suite import _wilson

        assert _wilson(0, 20)[0] == 0.0
        assert _wilson(0, 20)[1] > 0.0
        assert _wilson(20, 20)[1] == 100.0
        assert _wilson(20, 20)[0] < 100.0

    def test_narrows_as_the_sample_grows(self):
        from app.eval_suite import _wilson

        narrow_small = _wilson(2, 25)
        narrow_large = _wilson(200, 2500)
        assert (narrow_large[1] - narrow_large[0]) < (narrow_small[1] - narrow_small[0])

    def test_empty_sample_is_not_a_crash(self):
        from app.eval_suite import _wilson

        assert _wilson(0, 0) == (0.0, 0.0)

    def test_old_25_case_delta_would_have_been_unresolvable(self):
        """Why this was added: 2/25 vs 7/25 does not separate.

        The union experiment moved verse recall 2/25 -> 7/25 and looked like a
        20-point win. On 25 cases those intervals overlap heavily, so the win
        could not be claimed -- which is part of why the change stayed off.
        """
        from app.eval_suite import _wilson

        low_a, high_a = _wilson(2, 25)
        low_b, high_b = _wilson(7, 25)
        assert not (low_b > high_a), "intervals must overlap at n=25"


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