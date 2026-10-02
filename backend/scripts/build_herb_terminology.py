"""Classify every herb in ``reference/herbs.json`` against the actual corpus.

Why this exists
---------------
``herbs.json`` is keyed by Sanskrit/modern names (``shatavari``, ``bibhitaki``,
``pippali``) but the corpus is an English translation that names plants in
common English (``asparagus``, ``long pepper``, ``ginger``). The two vocabularies
are largely disjoint, so a user asking about "shatavari" retrieves nothing:

    71 of 93 herbs are genuinely discussed (detected in herb_mentions.json)
    22 appear zero times under any name or alias

Retrieving weakly for those 22 produces a low-confidence answer that reads as
grounded but is not. This script makes that state explicit and machine-checkable
instead of leaving it implicit in a zero-hit search.

How a herb is classified
------------------------
``discussed``
    Name or at least one alias occurs in the corpus under a word-boundary match.
    Verse count is recorded as evidence.

``recovered``
    The herb is absent by name, but ``reference/botanical_names.json`` gives it a
    Latin binomial whose genus occurs in the corpus. Two independent sources must
    agree: the corpus contains the genus, and the existing project reference says
    which plant the modern name denotes. The corpus is never asked to confirm a
    name it does not contain -- it supplies the genus, the reference supplies the
    identity.

``not_in_corpus``
    Neither the name, any alias, nor a Latin genus occurs anywhere in the
    corpus. The herb is simply not discussed by this translation.

Deliberate limitation: no mapping is written by hand. Every ``recovered`` entry
falls out of the genus test below. In practice that yields one herb
(``shatavari`` -> ``asparagus``), because only 3 of the 39 Latin genera in
``botanical_names.json`` occur in the corpus at all. Adding a mapping for the
remaining absent herbs would mean supplying botanical knowledge the corpus does
not contain, which is exactly the hand-written, unsourced input this project
excludes.

Usage
-----
    python scripts/build_herb_terminology.py
"""

import json
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
PROCESSED = BACKEND / "processed" / "charaka_structured.json"
REFERENCE = BACKEND / "reference"
OUT = REFERENCE / "herb_terminology.json"

# Genus length floor. Latin binomials have a genus of >=3 characters, but short
# ones collide with ordinary English words ("aps", "mal"), which would produce
# the same false matches that sank a first attempt at this script.
MIN_GENUS_LEN = 4


def corpus_verse_index(verses):
    """Lowercased verse text per verse_id, for word-boundary matching."""
    return {
        v["verse_id"]: (v.get("text_english") or "").lower() for v in verses
    }


def occurrences(term: str, index) -> list:
    """Verse IDs where ``term`` occurs as a whole word.

    Word boundaries matter: "mriya" must not match inside "guduchi", and "pipe"
    must not match inside "piper". A plain substring test silently inflates
    coverage and would make this classification wrong.
    """
    t = (term or "").strip().lower()
    if len(t) < 3:
        return []
    pat = re.compile(r"(?<![a-z])" + re.escape(t) + r"(?![a-z])")
    return [vid for vid, text in index.items() if pat.search(text)]


def genus_of(latin: str) -> str:
    """First word of a Latin binomial, lowercased."""
    parts = (latin or "").split()
    return parts[0].lower() if parts else ""


def classify(herb, index, botanical):
    name = herb["name"]
    aliases = [a for a in herb.get("aliases", []) if a and a.strip().lower() != name.strip().lower()]

    name_hits = occurrences(name, index)
    alias_hits = {a: occurrences(a, index) for a in aliases}
    matched_aliases = {a: v for a, v in alias_hits.items() if v}

    if name_hits or matched_aliases:
        evidence = sorted({v for v in name_hits} | {v for vs in matched_aliases.values() for v in vs})
        return {
            "status": "discussed",
            "corpus_terms": ([name] if name_hits else [])
            + sorted(matched_aliases, key=lambda a: -len(matched_aliases[a])),
            "verse_count": len(evidence),
            "evidence_verses": evidence[:5],
            "note": "Name or alias occurs in the corpus.",
        }

    latin = botanical.get(name, "")
    genus = genus_of(latin)
    if genus and len(genus) >= MIN_GENUS_LEN:
        genus_hits = occurrences(genus, index)
        if genus_hits:
            return {
                "status": "recovered",
                "corpus_terms": [genus],
                "verse_count": len(genus_hits),
                "evidence_verses": genus_hits[:5],
                "latin": latin,
                "basis": (
                    f"'{name}' does not occur in the corpus, but botanical_names.json "
                    f"gives it as {latin}, and the genus '{genus}' occurs in the corpus "
                    f"in {len(genus_hits)} verse(s)."
                ),
            }

    return {
        "status": "not_in_corpus",
        "corpus_terms": [],
        "verse_count": 0,
        "evidence_verses": [],
        "note": (
            f"Neither '{name}', its aliases, nor a Latin genus for it occur anywhere "
            f"in the corpus. This translation does not discuss it."
        ),
    }


def main() -> int:
    if not PROCESSED.exists():
        print(f"error: {PROCESSED} missing; run scripts/transform.py first", file=sys.stderr)
        return 1

    verses = json.load(open(PROCESSED, encoding="utf-8"))
    herbs = json.load(open(REFERENCE / "herbs.json", encoding="utf-8"))["herbs"]
    botanical = json.load(open(REFERENCE / "botanical_names.json", encoding="utf-8"))

    index = corpus_verse_index(verses)
    print(f"corpus: {len(verses)} verses, {len(index)} indexed")

    table = {h["name"]: classify(h, index, botanical) for h in herbs}

    counts = {}
    for entry in table.values():
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1

    out = {
        "_comment": (
            "Generated by scripts/build_herb_terminology.py. Do not hand-edit. "
            "Classifies each herb in herbs.json against the corpus: 'discussed', "
            "'recovered' (absent by name, genus present per botanical_names.json), "
            "or 'not_in_corpus'."
        ),
        "_corpus_verses": len(verses),
        "_counts": counts,
        "herbs": table,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False, sort_keys=True)

    print(f"wrote {OUT.relative_to(BACKEND)}")
    for status, n in sorted(counts.items()):
        print(f"  {status:15} {n}")
    for name, e in table.items():
        if e["status"] == "recovered":
            print(f"  recovered: {name} -> {e['corpus_terms']} ({e['verse_count']} verses)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())