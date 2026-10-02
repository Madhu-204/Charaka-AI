"""Ground-truth quality of the chapter-level eval sets.

The eval credits one expected chapter per question. That is brittle in a text
like the Charaka Samhita, where a topic is legitimately treated in several
chapters, and the brittleness is invisible: a correct retrieval gets reported as
a failure and the metric blames the retriever for a labelling mistake.

``acceptable_chapters`` exists for the genuine cases. The risk it introduces is
that it becomes a way to make a failing item pass, so these tests hold the line:
an alternative chapter must exist, must have a real title, and must be
justified in the item's own notes.
"""

import json
import re
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


@pytest.fixture(scope="module")
def core_items():
    path = BACKEND / "reference" / "eval_set.json"
    if not path.is_file():
        pytest.skip("eval set missing")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def titles():
    path = BACKEND / "reference" / "chapter_titles.json"
    if not path.is_file():
        pytest.skip("chapter titles missing")
    return json.loads(path.read_text(encoding="utf-8"))


def test_sets_are_present_and_populated(core_items):
    assert len(core_items) >= 28


def test_no_duplicate_ids(core_items):
    ids = [i["eval_id"] for i in core_items]
    assert len(set(ids)) == len(ids)


def test_every_item_names_a_question_and_a_target(core_items):
    for item in core_items:
        assert item.get("question"), item["eval_id"]
        assert item.get("expected_sthana"), item["eval_id"]
        assert item.get("expected_chapter") is not None, item["eval_id"]


def test_expected_chapters_exist_in_the_corpus(core_items, corpus):
    for item in core_items:
        key = (item["expected_sthana"], item["expected_chapter"])
        present = any(
            (r.get("sthana"), r.get("chapter")) == key for r in corpus.values()
        )
        assert present, f"{item['eval_id']}: expected chapter {key} is not in the corpus"


class TestAcceptableChapters:
    def test_alternatives_are_well_formed(self, core_items):
        for item in core_items:
            for entry in item.get("acceptable_chapters") or []:
                assert re.fullmatch(r"[a-z]+/\d+", entry), (
                    f"{item['eval_id']}: {entry!r} must be 'sthana/chapter'"
                )

    def test_alternatives_are_not_the_primary_expectation(self, core_items):
        """A duplicate primary would make it look like two independent credits."""
        for item in core_items:
            primary = f"{item['expected_sthana']}/{item['expected_chapter']}"
            assert primary not in (item.get("acceptable_chapters") or []), item["eval_id"]

    def test_alternatives_exist_in_the_corpus(self, core_items, corpus):
        for item in core_items:
            for entry in item.get("acceptable_chapters") or []:
                sthana, chapter = entry.split("/", 1)
                present = any(
                    (r.get("sthana"), r.get("chapter")) == (sthana, int(chapter))
                    for r in corpus.values()
                )
                assert present, f"{item['eval_id']}: {entry} is not in the corpus"

    def test_alternatives_have_a_real_title(self, core_items, titles):
        """No crediting a chapter that has no name in this corpus.

        This is the cheap check against an alternative being invented to rescue a
        failing item: a real chapter here always has a title.
        """
        for item in core_items:
            for entry in item.get("acceptable_chapters") or []:
                assert entry in titles, (
                    f"{item['eval_id']}: {entry} has no title; if it is genuinely "
                    f"acceptable it needs a real chapter, not a speculative one"
                )

    def test_alternatives_are_justified_in_the_item_notes(self, core_items):
        """Every relaxation must say why, in the item itself.

        Otherwise there is no way to tell a considered second reading of the
        text from a label bent to make a number look better.
        """
        for item in core_items:
            if item.get("acceptable_chapters"):
                assert (item.get("notes") or "").strip(), (
                    f"{item['eval_id']}: accepts "
                    f"{item['acceptable_chapters']} but records no reason"
                )

    def test_relaxations_stay_rare(self, core_items):
        """If this spreads, the eval has stopped discriminating.

        A high rate of multi-accepted chapters means the questions are ambiguous
        and should be rewritten instead of the labels widened.
        """
        relaxed = sum(1 for i in core_items if i.get("acceptable_chapters"))
        assert relaxed <= len(core_items) * 0.15, (
            f"{relaxed}/{len(core_items)} items accept an alternative chapter; "
            f"the questions are probably ambiguous rather than the labels wrong"
        )


def test_the_known_false_negative_is_still_credited(titles):
    """eval_18 regression guard.

    Both vimanasthana/1 and sutrasthana/26 are titled on tastes/rasa. Scoring
    only the first reported a correct retrieval as a failure, which read as a
    retriever defect when it was a labelling error. If someone narrows this
    back to one chapter, the eval will start blaming retrieval again.
    """
    for chapter in ("vimanasthana/1", "sutrasthana/26"):
        assert chapter in titles, chapter
        assert "taste" in titles[chapter].lower() or "rasa" in titles[chapter].lower(), (
            f"{chapter} is no longer titled on tastes/rasa: {titles[chapter]}"
        )