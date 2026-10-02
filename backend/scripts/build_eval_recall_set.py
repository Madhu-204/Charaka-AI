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
pins one verse by a phrase that occurs in exactly one verse of the whole corpus,
so the correct answer is provable rather than judged. That makes the ground
truth as certain as it can be, and it isolates recall from ranking quality --
which is exactly the axis the pending fusion work needs.

This is deliberately a **needle probe, not a measure of user-facing answer
quality.** The questions are synthetic and centred on one rare phrase, so they
are far more lexical than real traffic. Read them as a recall floor and nothing
more; the chapter-level sets remain the quality signal.

Why phrases, not single words
-----------------------------
An earlier version drew single words that occur exactly once in the corpus.
That does not scale. In a 2,490-verse corpus a hapax *word* is only weakly
evidence of domain vocabulary: "actually", "absolute", "abilities" and
"abruptly" each occur in exactly one verse. The old version dodged them with a
12-character minimum length, which is a crude proxy for "domain-specific" and
caps the pool at a few hundred terms.

Two-word phrases inverts that: 17,991 hapax bigrams survive after dropping
function words, and phrases like "abdominal distension" or "abscess giddiness"
are self-evidently domain vocabulary with no length heuristic needed. Both
tokens must be substantive, which removes the "a ..." long tail.

Correlation, honestly stated
----------------------------
The corpus has only 20 chapters, so cases are clustered and cases within a
chapter are not independent -- adjacent verses share topic and phrasing. The
generator caps cases per chapter and spreads them evenly, but the effective
sample size is closer to the chapter count than the case count. Treat small
differences in this probe as indicative, not conclusive.

Sampling is systematic and fixed in advance, never filtered by whether retrieval
currently succeeds. Cherry-picking terms the system already finds would turn the
probe into a ceiling and hide the very failures it exists to expose.
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

CORPUS = BACKEND / "processed" / "charaka_structured.json"
OUT = BACKEND / "reference" / "eval_recall_cases.json"

# Function words are dropped rather than filtered by length: "abdomen false" and
# "about both" are hapax but useless as probe terms, and a length rule does not
# catch them.
STOPWORDS = set(
    "a an the of to in is and for with that this it as be by on or from at its "
    "which are was were has have had not but they their them his her you your "
    "i we us our can may will do does did no so than then there here when "
    "where while each every any some all one two he she him himself herself "
    "also very more most such into out up down over under again further once "
    "because while during before after above below between both same own too "
    "only just other another now even ever never always often sometimes"
    .split()
)

# Both tokens of a probe phrase must be at least this long. Keeps "abhi uka"
# (transliteration debris) and "about both" out without a whole-corpus stoplist.
MIN_TOKEN_LEN = 5

# Source-translation artifacts: the upstream English drops a space. An automatic
# "does this split into two corpus words" test was tried and rejected -- it also
# removed bloodletting, genitourinary and hypochondriac, which are genuine
# terms. Excluded explicitly so the list stays auditable.
ARTIFACT_TERMS = {
    "applicationscan", "bodychannels", "bodysustaining", "catechudecoction",
    "chymedisorder", "chymemorbidity", "coughdisorder", "dhanustambha",
    "immersionbath", "kaphadisorders", "lifecontrolling", "lifepromoter",
    "plantproducts", "shellcreeper", "waterchestnut", "waterstorage",
}

# How many cases to emit and how many a single chapter may contribute. 20
# chapters x 6 keeps every chapter equally represented.
TARGET_CASES = 120
MAX_PER_CHAPTER = 6

# Rotated by index so the probe is not a single repeated sentence pattern.
TEMPLATES = (
    "What does Charaka say about {phrase}?",
    "In the Charaka Samhita, what is said about {phrase}?",
    "Which part of Charaka discusses {phrase}?",
    "What does Charaka teach regarding {phrase}?",
    "Charaka's account of {phrase}?",
)


def _phrases(corpus):
    """Hapax, stopword-free bigrams keyed by the verse that uniquely holds them."""
    held = defaultdict(set)
    for record in corpus:
        words = re.findall(r"[a-z]+", (record.get("text_english") or "").lower())
        for i in range(len(words) - 1):
            held[" ".join(words[i : i + 2])].add(record["verse_id"])

    by_id = {r["verse_id"]: r for r in corpus}
    usable = []
    for phrase, verses in held.items():
        if len(verses) != 1:
            continue
        left, right = phrase.split()
        if left in STOPWORDS or right in STOPWORDS:
            continue
        if len(left) < MIN_TOKEN_LEN or len(right) < MIN_TOKEN_LEN:
            continue
        if left in ARTIFACT_TERMS or right in ARTIFACT_TERMS:
            continue
        record = by_id[next(iter(verses))]
        usable.append(
            (
                (record.get("sthana"), record.get("chapter")),
                phrase,
                record,
            )
        )
    return usable


def build() -> dict:
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))

    by_chapter = defaultdict(list)
    for chapter, phrase, record in _phrases(corpus):
        by_chapter[chapter].append((phrase, record))
    for pool in by_chapter.values():
        pool.sort()

    # Round-robin the chapters so coverage is even before it is capped, rather
    # than letting whichever chapters sort first take every slot.
    chapters = sorted(by_chapter, key=lambda c: str(c))

    cases = []
    used_verses = set()
    count = defaultdict(int)
    cursor = defaultdict(int)

    for _ in range(MAX_PER_CHAPTER):
        for chapter in chapters:
            if len(cases) >= TARGET_CASES:
                break
            if count[chapter] >= MAX_PER_CHAPTER:
                continue
            pool = by_chapter[chapter]
            start = cursor[chapter]
            # Walk forward from the cursor to the next verse this chapter has
            # not already contributed, so a thin chapter still yields its slot
            # instead of being dropped from the probe.
            for offset in range(len(pool)):
                index = (start + offset) % len(pool)
                phrase, record = pool[index]
                if record["verse_id"] in used_verses:
                    continue
                cursor[chapter] = index + 1
                count[chapter] += 1
                used_verses.add(record["verse_id"])
                index_in_cases = len(cases)
                cases.append(
                    {
                        "eval_id": f"rc_{index_in_cases + 1:03d}",
                        "recall": True,
                        "question": TEMPLATES[index_in_cases % len(TEMPLATES)].format(
                            phrase=phrase
                        ),
                        "expected_verse_id": record["verse_id"],
                        "expected_sthana": record.get("sthana"),
                        "expected_chapter": record.get("chapter"),
                        "probe_term": phrase,
                        "notes": (
                            "Recall probe. The two-word phrase occurs in exactly "
                            "one verse of the corpus, so this verse is the "
                            "provable answer. Not a natural-language quality "
                            "question."
                        ),
                    }
                )
                break

    OUT.write_text(
        json.dumps(cases, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return {
        "cases": len(cases),
        "chapters": len(count),
        "pool": sum(len(v) for v in by_chapter.values()),
        "out": str(OUT),
    }


if __name__ == "__main__":
    info = build()
    print(
        f"[eval-recall] wrote {info['cases']} cases across {info['chapters']} "
        f"chapters (pool {info['pool']} hapax phrases) to {info['out']}"
    )