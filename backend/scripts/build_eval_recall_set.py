"""Generate the verse-level recall probe: ``reference/eval_recall_cases.json``.

Why this exists
---------------
``eval_set.json`` and ``eval_corner_cases.json`` score *chapter* resolution.
That is the right granularity for "did we look in the right book and chapter",
but it cannot see a change that only reorders verses inside the correct
chapter: swapping the resolved verse for a sibling in the same chapter scores
identically. Any experiment about which verse wins -- reranking, candidate-pool
width, fusion weights -- is therefore unmeasurable against the existing sets.

What these cases measure
------------------------
Recall: can the retriever surface a *specific known* verse at all? Each case
pins one verse by a term that occurs in exactly one verse of the whole corpus,
so the correct answer is provable rather than judged. That makes the ground
truth as certain as it can be, and it isolates recall from ranking quality --
which is exactly the axis the pending rerank-pool work needs.

This is deliberately a **needle probe, not a measure of user-facing answer
quality.** The questions are synthetic and centred on one rare term, so they are
far more lexical than real traffic. Read them as a recall floor and nothing
more; the chapter-level sets remain the quality signal.

Sampling is systematic (every Nth surviving term, alphabetical), never filtered
by whether retrieval currently succeeds. Cherry-picking terms the system
already finds would turn the probe into a ceiling and hide the very failures it
exists to expose.
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

CORPUS = BACKEND / "processed" / "charaka_structured.json"
OUT = BACKEND / "reference" / "eval_recall_cases.json"

# Terms are drawn from a length band that skews domain vocabulary over common
# English. Below ~12 chars the band fills with verbs and function words
# ("absolute", "actually"); above ~16 it is nearly empty in this corpus.
MIN_LEN = 12
MAX_LEN = 16

# Source-translation artifacts: the upstream English drops a space, so these
# appear concatenated in the verse text. An automatic "does this split into two
# corpus words" test was tried and rejected -- it also removed bloodletting,
# genitourinary and hypochondriac, which are genuine terms. Excluded explicitly
# so the list is auditable and no real vocabulary is lost to a heuristic.
ARTIFACT_TERMS = {
    "applicationscan", "bodychannels", "bodysustaining", "catechudecoction",
    "chymedisorder", "chymemorbidity", "coughdisorder", "dhanustambha",
    "immersionbath", "kaphadisorders", "lifecontrolling", "lifepromoter",
    "plantproducts", "shellcreeper", "waterchestnut", "waterstorage",
}

# How many cases to emit, how many to advance through the sorted candidate list
# to pick each one, and how many cases one chapter may contribute. The chapter
# cap stops a single dense chapter from dominating the score.
TARGET_CASES = 40
SAMPLE_STRIDE = 5
MAX_PER_CHAPTER = 2


def build() -> dict:
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))

    df = Counter()
    for record in corpus:
        text = (record.get("text_english") or "").lower()
        df.update(set(re.findall(r"[a-z]+", text)))

    # A term in exactly one verse pins that verse with certainty.
    home = {}
    for record in corpus:
        text = (record.get("text_english") or "").lower()
        for term in set(re.findall(r"[a-z]+", text)):
            if df[term] == 1:
                home[term] = record

    candidates = sorted(
        term
        for term in home
        if MIN_LEN <= len(term) <= MAX_LEN and term not in ARTIFACT_TERMS
    )

    cases = []
    per_chapter = Counter()
    used_verses = set()
    for term in candidates[::SAMPLE_STRIDE]:
        if len(cases) >= TARGET_CASES:
            break
        record = home[term]
        chapter_key = f"{record.get('sthana')}/{record.get('chapter')}"
        if per_chapter[chapter_key] >= MAX_PER_CHAPTER:
            continue
        # Two hapax terms can sit in one verse. Keeping both would double-count
        # a single retrieval, so each case targets a distinct verse and every
        # hit is independent.
        if record["verse_id"] in used_verses:
            continue
        per_chapter[chapter_key] += 1
        used_verses.add(record["verse_id"])
        cases.append(
            {
                "eval_id": f"rc_{len(cases) + 1:02d}",
                "recall": True,
                "question": f"What does Charaka say about {term}?",
                "expected_verse_id": record["verse_id"],
                "expected_sthana": record.get("sthana"),
                "expected_chapter": record.get("chapter"),
                "probe_term": term,
                "notes": (
                    "Recall probe. The probe term occurs in exactly one verse of "
                    "the corpus, so this verse is the provable answer. Not a "
                    "natural-language quality question."
                ),
            }
        )

    OUT.write_text(json.dumps(cases, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {
        "cases": len(cases),
        "candidates": len(candidates),
        "chapters": len(per_chapter),
        "out": str(OUT),
    }


if __name__ == "__main__":
    info = build()
    print(
        f"[eval-recall] wrote {info['cases']} cases across {info['chapters']} "
        f"chapters ({info['candidates']} candidate terms) to {info['out']}"
    )