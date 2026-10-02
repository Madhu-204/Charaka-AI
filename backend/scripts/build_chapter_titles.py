"""Extract one chapter title per chapter into ``reference/chapter_titles.json``.

Why this exists
---------------
Several Charaka chapters open with a bare title verse --

    "We shall now expound the chapter entitled 'The Quest for Longevity.'"

-- that names the chapter's subject without stating any of its content. A
question like "how can one live a long, healthy life?" is semantically about
chapter 1, yet the *only* verse in that chapter whose text mentions longevity is
this title line. Without it, embedding ``text_english`` alone leaves short
title-like verses with almost no topical signal.

``build_vector_store.py`` prepends these titles as parent context when building
the index. They are derived from the corpus itself, so nothing here invents
Attribution: every title is verbatim source text.

The parser is deliberately conservative. It only accepts text that follows the
literal phrase "chapter entitled", so a chapter that opens with content (e.g.
sutrasthana/20, which opens with a numbered list) simply gets no title and falls
back to condition/category metadata.

Usage
-----
    python scripts/build_chapter_titles.py
"""

import json
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
PROCESSED = BACKEND / "processed" / "charaka_structured.json"
REFERENCE = BACKEND / "reference"
OUT = REFERENCE / "chapter_titles.json"

# The literal lead-in every generated title verse shares.
ENTITLED_RE = re.compile(r"chapter\s+entitled\s+", re.IGNORECASE)

# Left/curly quote forms that may introduce a generated title.
OPEN_QUOTES = "\u201c\u2018\"'"

# Right/curly quote forms that may terminate one. Both sets matter: the corpus
# mixes 'the entitled "..."' and 'the entitled '...'' styles, so a parser that
# only knows the left forms never finds its terminator and leaks the quote into
# the stored title.
CLOSE_QUOTES = "\u201d\u2019\"'"

# Trailing noise to drop once the title is isolated.
_TRAILING_JUNK_RE = re.compile(r"[\s.]+$")


def _is_closing_quote(ch: str, i: int, s: str) -> bool:
    """True when the quote char at ``s[i]`` ends the title rather than being an
    in-word apostrophe.

    A title can contain possessives ("one's Lineage"), and in both that case and
    the real terminator case ("...of Vata\\u201d") the quote follows a letter, so
    "preceded by a letter" cannot separate them. The discriminator is what
    follows: an apostrophe sits between two letters, whereas a closing quote is
    followed by end-of-string or punctuation.
    """
    if ch not in CLOSE_QUOTES:
        return False
    if not (i > 0 and s[i - 1].isalpha()):
        return True
    return not (i + 1 < len(s) and s[i + 1].isalpha())


def parse_title(text: str) -> str | None:
    """Return the quoted chapter title in ``text``, or None if it is not a title.

    Example:
        >>> parse_title('We shall now expound the chapter entitled \\u201cThe Quest for Longevity.\\u201d')
        'The Quest for Longevity'
    """
    if not text:
        return None
    match = ENTITLED_RE.search(text)
    if not match:
        return None

    rest = text[match.end():]
    # Drop the opening quote, if present.
    rest = rest[1:] if rest[:1] in OPEN_QUOTES else rest
    rest = rest.lstrip()

    # Find the closing quote, skipping any in-word apostrophe.
    end = None
    for i, ch in enumerate(rest):
        if _is_closing_quote(ch, i, rest):
            end = i
            break

    if end is not None:
        rest = rest[:end]
    else:
        # Unbalanced quotes: fall back to the first sentence boundary so a
        # malformed line cannot swallow the rest of the verse.
        sentence = re.split(r"(?<=[.!?])\s", rest, maxsplit=1)[0]
        rest = sentence

    title = _TRAILING_JUNK_RE.sub("", rest).strip()
    if len(title) < 4:
        return None
    return title


def main() -> int:
    if not PROCESSED.is_file():
        sys.exit(f"missing {PROCESSED} -- run `python scripts/transform.py` first")

    records = json.loads(PROCESSED.read_text(encoding="utf-8"))

    titles: dict[str, str] = {}
    chapters: dict[tuple[str, int], str] = {}
    for rec in records:
        key = (rec["sthana"], int(rec["chapter"]))
        # Keep the lexicographically first verse_id: transform.py emits verses
        # in source order, so this is the opening verse of the chapter.
        vid = rec["verse_id"]
        if key not in chapters or vid < chapters[key]:
            chapters[key] = vid

    by_id = {rec["verse_id"]: rec for rec in records}
    for key, vid in chapters.items():
        parsed = parse_title(by_id[vid].get("text_english") or "")
        if parsed:
            titles[f"{key[0]}/{key[1]}"] = parsed

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(
        json.dumps(titles, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    missing = [f"{k[0]}/{k[1]}" for k in sorted(chapters) if f"{k[0]}/{k[1]}" not in titles]
    print(f"[titles] parsed {len(titles)}/{len(chapters)} chapters -> {OUT.name}")
    for key in missing:
        print(f"[titles]   no title verse: {key} (falls back to condition/category)")
    return 0


if __name__ == "__main__":
    sys.exit(main())