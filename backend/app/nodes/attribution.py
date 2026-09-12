"""Per-sentence token attribution (task 37).

Aligns every sentence of the final answer with the retrieved verse whose text
shares the most lexical tokens (after a small stopword list). This is a
transparent, dependency-free stand-in for token-level highlight alignment:
each sentence gets a 1-based source marker (matching the synthesis [n] markers)
and an overlap score in [0, 1].

Scoring is deliberately conservative:
  score >= 0.50  strong grounding     -> sentence closely echoes a verse
  score >= 0.25  partial              -> some shared vocabulary, stay cautious
  below          nominal / uncited    -> treat as paraphrase or off-source
"""

import re

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "nor", "so", "of", "in", "on", "at",
    "to", "for", "with", "by", "from", "as", "into", "than", "that", "this",
    "these", "those", "it", "its", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "should", "can", "could", "may", "might", "not", "no", "you", "your",
    "they", "them", "their", "we", "our", "other", "also", "only", "very",
    "most", "more", "some", "such", "all", "any", "each", "one", "two",
    "about", "up", "out", "off", "over", "under", "if", "then", "when", "how",
}

_WORD_RE = re.compile(r"[a-zA-Z']+")

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n{1,}|(?<=\n)\s*-\s+")


def _tokens(text: str) -> list:
    return [
        w.lower()
        for w in _WORD_RE.findall(text)
        if w.lower() not in _STOPWORDS
    ]


def _sentences(text: str) -> list:
    parts = [p.strip() for p in _SENTENCE_RE.split(text) if p and p.strip()]
    return parts or ([text] if text.strip() else [])


def attribution(state):
    answer = state.get("final_answer", "")
    retrieved = state.get("retrieved", [])
    if not answer or not retrieved:
        return {"attribution": []}

    verse_tokens = [_tokens(r.get("text") or "") for r in retrieved]

    segments = []
    for sentence in _sentences(answer):
        stok = _tokens(sentence)
        if not stok:
            continue
        best_idx, best_score = None, 0.0
        for i, vt in enumerate(verse_tokens):
            if not vt:
                continue
            vt_set = set(vt)
            hits = sum(1 for w in stok if w in vt_set)
            cov = hits / len(stok)
            if cov > best_score:
                best_score, best_idx = cov, i
        if best_idx is None:
            continue
        verse = retrieved[best_idx]
        segments.append(
            {
                "sentence": sentence,
                "verse_index": best_idx + 1,
                "score": round(best_score, 3),
                "verse_id": verse.get("verse_id") if verse else None,
            }
        )

    covered = sum(1 for s in segments if s["score"] >= 0.5)
    trace = state.get("trace", [])
    return {
        "attribution": segments,
        "trace": trace
        + [
            f"attribution: {len(segments)} sentence(s) aligned by token overlap, "
            f"{covered} strongly grounded (score >= 0.50)"
        ],
    }