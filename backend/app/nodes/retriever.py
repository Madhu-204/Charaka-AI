import json
import math
import os
import re
from collections import Counter
from pathlib import Path

import chromadb
import numpy as np
from sentence_transformers import SentenceTransformer

from app.chunking import EMBEDDING_MODEL, chapter_context, herb_key
from app.nodes.tool_router import _and_clauses

BACKEND = Path(__file__).resolve().parents[2]

client = chromadb.PersistentClient(path=str(BACKEND / "chroma_db"))
collection = client.get_collection(name="charaka_ai_corpus")
model = SentenceTransformer(EMBEDDING_MODEL)

_ALL = collection.get(include=["documents", "metadatas", "embeddings"])

# Verse embeddings are read on every retrieval, and they never change while the
# process is up -- the store is immutable between rebuilds. Fetching them per
# query meant a SQLite round-trip for a dozen vectors on every request, so they
# are loaded once here alongside the documents. ~4 MB for 2,490x384 float32.
# Values are the same arrays Chroma returned, so scoring is unchanged.
_EMBED = dict(zip(_ALL["ids"], _ALL["embeddings"]))

# BM25 must see the same text the vector index was built from, or the two halves
# of hybrid search disagree about what a verse says. The stored `documents` are
# kept clean for display, so the parent-chapter context is re-applied here from
# the metadata rather than read back out of the stored string.
_BM25_DOCS = [
    chapter_context(meta) + (doc or "")
    for doc, meta in zip(_ALL["documents"], _ALL["metadatas"])
]

_TITLE_CASEFOLD_RE = re.compile(r"[a-z]+")


class _BM25:
    """Classic BM25 (k1=1.5, b=0.75) over the full corpus, built once at load."""

    def __init__(self, ids, docs):
        self.ids = ids
        self.tokens = [_TITLE_CASEFOLD_RE.findall(d.lower()) for d in docs]
        self.N = len(self.tokens)
        self.dl = [len(t) for t in self.tokens]
        self.avgdl = sum(self.dl) / max(self.N, 1)
        df = Counter(t for toks in self.tokens for t in set(toks))
        self.idf = {
            term: math.log(1 + (self.N - n + 0.5) / (n + 0.5)) for term, n in df.items()
        }
        self.k1 = 1.5
        self.b = 0.75
        # id -> row, so a restricted search can jump straight to the allowed
        # rows instead of scanning all N and testing membership.
        self.row_of = {vid: i for i, vid in enumerate(ids)}

    def _score_doc(self, qtok, toks):
        dl = len(toks)
        freq = Counter(toks)
        denom = self.k1 * (1 - self.b + self.b * dl / self.avgdl)
        total = 0.0
        for term in qtok:
            tf = freq.get(term, 0)
            if not tf:
                continue
            total += self.idf.get(term, 0.0) * (tf * (self.k1 + 1)) / (tf + denom)
        return total

    def search(self, query, top=12, restrict=None):
        qtok = [t for t in _TITLE_CASEFOLD_RE.findall(query.lower()) if t in self.idf or t]
        # A restricted search is the hot path: retrieval always passes the
        # Chroma candidate list, so walking that list directly avoids scanning
        # all N rows for membership. Same rows scored, same scores returned.
        if restrict is None:
            rows = range(self.N)
        else:
            rows = []
            for vid in restrict:
                idx = self.row_of.get(vid)
                if idx is not None:
                    rows.append(idx)
        scored = []
        for idx in rows:
            s = self._score_doc(qtok, self.tokens[idx])
            if s > 0:
                scored.append((self.ids[idx], s))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top]


BM25_INDEX = _BM25(_ALL["ids"], _BM25_DOCS)

_RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
_reranker = None
# Eval-gated and left off by default. Measured, not assumed:
#   - The cross-encoder itself is healthy: on a 12-candidate pool it produces
#     well-separated scores (spread 8.33, 12/12 distinct) in the right order.
#   - Reordering cannot fix most of the remaining misses because the correct
#     verse is never a candidate. Of the four chapter misses, two are recall
#     failures (the right chapter is absent from the pool entirely), so no
#     reranker can reach them.
#   - Widening the pool to admit those verses makes top-1 accuracy worse
#     (20/24 at n=12 falling to 16/24 at n=80): the correct verse for eval_18
#     only enters at rank 17, where it dilutes the fused score instead of
#     leading it. The narrow pool is load-bearing, not a limitation.
# Re-enable only with a reranker that beats hybrid-only on scripts/eval_run.py.
_rerank_enabled = os.getenv("CHARAKA_RERANKER", "0") == "1"


def _get_reranker():
    global _reranker
    if _reranker is None and _rerank_enabled:
        try:
            from sentence_transformers import CrossEncoder

            _reranker = CrossEncoder(_RERANK_MODEL)
        except Exception as e:  # noqa: BLE001
            print(f"[retriever] cross-encoder unavailable ({e}) → hybrid-only fallback")
            _reranker = False
    return _reranker or None


def _apply_reranker(hybrid, query):
    """Rerank a candidate pool with the cross-encoder.

    Returns ``(pairs_or_None, status)`` where status is one of:
      "off"     the cross-encoder is disabled or unavailable
      "applied" scores were produced and the pool was reordered
      "failed"  the model raised; hybrid ranking stands

    The status is returned rather than inferred so the trace can name what
    actually ran. Reporting "rerank" unconditionally made every trace line
    claim a stage that is off by default.
    """
    reranker = _get_reranker()
    if reranker is None:
        return None, "off"
    try:
        texts = [c["text"][:800] for c in hybrid[:14]]
        pairs = [(query, t) for t in texts]
        scores = reranker.predict(pairs, show_progress_bar=False)
        return list(zip(hybrid[:14], [float(s) for s in scores])), "applied"
    except Exception as e:  # noqa: BLE001
        print(f"[retriever] rerank failed ({e}) → hybrid ranking used")
        return None, "failed"

with open(BACKEND / "reference" / "mappings.json", encoding="utf-8") as f:
    mappings = json.load(f)

with open(BACKEND / "reference" / "herbs.json", encoding="utf-8") as f:
    herbs_data = json.load(f)["herbs"]

chapter_meta = mappings["chapter_meta"]

DECOMPOSITION_TERMS = [
    "bloating", "constipation", "acidity", "diarrhea", "diarrhoea", "cough",
    "cold", "fever", "insomnia", "sleep", "anxiety", "joint", "stiffness",
    "headache", "fatigue", "weight", "gas", "indigestion", "heartburn",
    "congestion", "phlegm", "appetite", "itching", "acne", "rash",
    "vata", "pitta", "kapha",
]

ALIAS_TO_HERB = {}
for herb in herbs_data:
    for alias in herb["aliases"]:
        ALIAS_TO_HERB[alias.lower()] = herb["name"]

HERB_PATTERNS = []
for herb in herbs_data:
    escaped = [re.escape(a) for a in herb["aliases"]]
    pattern = r"\b(?:" + "|".join(escaped) + r")\b"
    HERB_PATTERNS.append((herb["name"], re.compile(pattern, re.IGNORECASE)))

def _chapter_key(candidate):
    return f"{candidate['meta']['sthana']}/{candidate['meta']['chapter']}"


# Reciprocal Rank Fusion constant. The standard value; k dampens the influence of
# the very top ranks so a single #1 hit cannot outvote a broad consensus.
RRF_K = 60


def _chapter_scores(pool, k=RRF_K):
    """Reciprocal-rank-fusion vote over chapters present in ``pool``.

    A question about a subject ("which herbs for purgation", "shatavari as a
    rejuvenator") is answered by a chapter, not by whichever single verse
    happens to share the most words. Measured on the eval set, taking the
    top-fused verse outright let one verse win on a lone BM25 hit while the
    correct chapter filled most of the pool:

        "Which herbs are used for purgation and emesis?"
            #0 sutrasthana/25  cos=0.615 bm25=4.29 fused=0.678   <- won
            #1 sutrasthana/4   cos=0.611 bm25=4.30 fused=0.631
            ... 8 more sutrasthana/4 verses in the top 10

    Ten verses from the right chapter lost to one that merely contained the
    word "emesis". Fusing by rank rather than by raw score makes the breadth of
    agreement count for something, which is what the user actually asked about.

    Returns ``{chapter_key: rrf_score}``.
    """
    scores: dict[str, float] = {}
    for rank, cand in enumerate(pool):
        key = _chapter_key(cand)
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
    return scores


def _resolve_by_chapter_vote(pool, k=RRF_K):
    """Pick the verse to resolve to, by chapter-level consensus.

    Returns ``(verse, chapter_scores)``. Falls back to the top-fused verse when
    the pool is empty. Within the winning chapter the best-fused verse wins, so
    this only changes *which chapter* is answered from -- it never promotes a
    weak verse over a strong one inside the chapter the pool already agreed on.
    """
    if not pool:
        return None, {}
    scores = _chapter_scores(pool, k=k)
    # Ties (and an all-one-verse-per-chapter pool) fall back to pool order, so
    # the top-fused verse still wins. Python's max is stable on the first
    # maximum, and dicts preserve insertion order = first-seen rank.
    best_chapter = max(scores, key=lambda key: scores[key])
    best = next((c for c in pool if _chapter_key(c) == best_chapter), None)
    return best, scores


def _resolve_chapter_key(canonical_term):
    for key, info in chapter_meta.items():
        condition = (info.get("condition") or "").lower()
        category = (info.get("category") or "").lower()
        if canonical_term in condition or canonical_term in category:
            return key
    return None


def _resolve_via_metadata(candidates, canonical_term):
    for c in candidates:
        cond = (c["meta"].get("traditional_condition") or "").lower()
        cat = (c["meta"].get("category_tag") or "").lower()
        if canonical_term in cond or canonical_term in cat:
            return c
    return None


def _detect_herb(query):
    for herb_name, pattern in HERB_PATTERNS:
        if pattern.search(query):
            return herb_name
    return None


# Provisional cosine anchors derived from the 28-question eval on the unified
# (pure cosine) scale, 2026-08-29. Deliberately conservative:
#   high   >= 0.60 : strong overlap (10/11 = 91% correct in eval)
#   medium 0.45-0.60: moderate overlap (12/15 = 80% correct in eval)
#   low    < 0.45  : weak overlap — always disclosed as uncertain
# Caveats: n=28, provisional until Phase 9 / real usage adds data. Similarity
# alone cannot separate hits from misses (eval_18 missed at 0.782, eval_25 hit
# at 0.540), so these bands bound OVERCLAIMING, they do not promise correctness.
HIGH_SCORE = 0.60
MEDIUM_SCORE = 0.45

# Blend weight for the semantic (cosine) signal against the lexical (BM25)
# signal. Raised from 0.5/0.5 after measuring the eval set.
#
# The balanced blend buried correct answers under short verses. eval_28
# ("What does Charaka say about shatavari as a rejuvenator?") resolves to
# cs_sutra_4_18, which reads "...cork swallow wort, climbing asparagus,
# Indian pennywort... these ten are rejuvenators" -- the exact answer. It carries
# the highest cosine of all 15 shatavari verses (0.3547 vs 0.1341 for the winner)
# yet BM25 scored it 0.0002 against 3.0609 for cs_chikitsa_3_250-251 and it lost.
#
# Cause: BM25's length normalisation. The correct verse is 26 words, and none of
# the query's rare terms appear literally in it -- the corpus says "climbing
# asparagus", never "shatavari", and "rejuvenator" vs "rejuvenators". So the one
# term it does win on is invisible to the lexical scorer, which then promotes a
# longer, lexically louder, topically wrong verse.
#
# Measured on the 28 core eval cases, 0.5/0.5 -> 0.6/0.4:
#   resolved 25/28 -> 27/28  (fixes eval_28 and eval_11, no regressions)
#   top-3    27/28 -> 27/28  (unchanged)
# 0.65 and above score identically, so the mildest sufficient change is used.
COSINE_WEIGHT = float(os.getenv("CHARAKA_COSINE_WEIGHT", "0.6"))


def _confidence_band(score) -> str:
    if score > HIGH_SCORE:
        return "high"
    if score > MEDIUM_SCORE:
        return "medium"
    return "low"


def _cosine(emb_a, emb_b) -> float:
    a = np.asarray(emb_a, dtype=float).flatten()
    b = np.asarray(emb_b, dtype=float).flatten()
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def _minmax(vals):
    lo, hi = min(vals), max(vals)
    if hi - lo < 1e-9:
        return [0.5] * len(vals)
    return [(v - lo) / (hi - lo) for v in vals]


def _decompose_compound(query):
    low = query.lower()
    if " and " not in low:
        return None
    clauses = [c.strip() for c in low.split(" and ") if c.strip()]
    subs, seen = [], set()
    for clause in clauses:
        for term in DECOMPOSITION_TERMS:
            if term in clause and term not in seen:
                seen.add(term)
                subs.append(clause)
                break
    return subs if len(subs) >= 2 else None


def _mmr_pick(pool, selected, lmda=0.7):
    best = None
    best_score = -1.0
    for cand in pool:
        redundancy = max(_cosine(cand["_emb"], s["_emb"]) for s in selected)
        mmr = lmda * cand["_fused"] - (1 - lmda) * redundancy
        if mmr > best_score:
            best_score = mmr
            best = cand
    return best


def _enrich(c, hybrid):
    source = next(x for x in hybrid if x["verse_id"] == c["verse_id"])
    return {**c, "_emb": source["_emb"], "_fused": source["_fused"]}


def _hybrid_pool(query, q_emb, where=None):
    """Fuse vector and lexical candidates into one ranked pool.

    Returns ``(pool, rerank_status)``; see ``_apply_reranker`` for the status
    values.
    """
    query_kwargs = {"query_embeddings": [q_emb], "n_results": 12}
    if where:
        query_kwargs["where"] = where

    candidates = {}

    def absorb(ids, docs, metas):
        for vid, doc, meta in zip(ids, docs, metas):
            if vid not in candidates:
                candidates[vid] = {"text": doc, "meta": meta}

    try:
        results = collection.query(**query_kwargs)
        absorb(results["ids"][0], results["documents"][0], results["metadatas"][0])
    except Exception as e:
        print(f"[retriever] chroma query failed: {e}")

    for sub in _decompose_compound(query) or []:
        try:
            sub_kwargs = {"query_embeddings": [model.encode([sub]).tolist()[0]], "n_results": 6}
            # Subqueries must honor the same filter as the main query, otherwise
            # a scoped request silently pulls unfiltered results into the pool
            # and the scope stops constraining anything.
            if where:
                sub_kwargs["where"] = where
            r = collection.query(**sub_kwargs)
            absorb(r["ids"][0], r["documents"][0], r["metadatas"][0])
        except Exception as e:
            print(f"[retriever] subquery '{sub}' failed: {e}")

    cand_ids = list(candidates)
    for vid, bscore in BM25_INDEX.search(query, top=12, restrict=cand_ids):
        if vid in candidates:
            candidates[vid]["_bm25"] = bscore

    if not cand_ids:
        return [], "off"

    have = []
    for vid in cand_ids:
        cand = candidates[vid]
        cos = _cosine(_EMBED[vid], q_emb)
        cand["_cos"] = cos
        cand["_bm25"] = cand.get("_bm25", 0.0)
        cand["_emb"] = _EMBED[vid]
        cand["verse_id"] = vid
        have.append(cand)

    cos_norm = _minmax([c["_cos"] for c in have])
    bm_norm = _minmax([c["_bm25"] for c in have])
    for c, cn, bn in zip(have, cos_norm, bm_norm):
        c["_fused"] = COSINE_WEIGHT * cn + (1.0 - COSINE_WEIGHT) * bn

    have.sort(key=lambda c: c["_fused"], reverse=True)

    reranked, rerank_status = _apply_reranker(have, query)
    if reranked:
        rerank_vals = [s for _, s in reranked]
        norm = _minmax(rerank_vals)
        for (c, _s), n in zip(reranked, norm):
            c["_fused"] = n
        have.sort(key=lambda c: c["_fused"], reverse=True)

    return have, rerank_status


def search_verses(query, limit=8):
    """Expose ranked hybrid results as plain text (used by the corpus search page)."""
    q_emb = model.encode([query]).tolist()[0]
    pool, _rerank_status = _hybrid_pool(query, q_emb)
    pool.sort(key=lambda c: c["_fused"], reverse=True)
    out = []
    for c in pool[:limit]:
        meta = c["meta"]
        out.append(
            {
                "verse_id": c["verse_id"],
                "text": c["text"],
                "score": round(float(c["_cos"]), 4),
                "chapter": f"{meta['sthana']}/{meta['chapter']}",
                "condition": meta.get("traditional_condition"),
                "category": meta.get("category_tag"),
            }
        )
    return out


def retrieve(state):
    query = state.get("expanded_query", state.get("query", ""))
    trace = state.get("trace", [])

    q_emb = model.encode([query]).tolist()[0]

    user_docs = []
    doc_session = state.get("doc_session")
    if doc_session:
        try:
            from app import documents

            user_docs = documents.search(doc_session, q_emb, top=2)
        except Exception as e:  # noqa: BLE001
            print(f"[retriever] user-doc search failed: {e}")
    used_documents = bool(user_docs)
    if used_documents:
        trace = trace + [
            f"documents: {len(user_docs)} chunk(s) retrieved from your uploaded files "
            f"(top score {user_docs[0]['score']:.3f})"
        ]

    herb = _detect_herb(query)
    where = state.get("metadata_filter")

    # A named herb is a *filter* on the ordinary hybrid path, not a separate
    # retrieval mode. The previous `_herb_retrieve` bypass ranked every verse
    # mentioning the herb by similarity alone and returned early, which meant
    # the rest of the question never got a vote: "How is ashwagandha used in
    # fever treatment?" answered from a verse that matched the herb but not the
    # complaint. Filtering keeps the hybrid ranking intact while still
    # guaranteeing the resolved verse actually mentions the herb.
    herb_filter = None
    if herb:
        key = herb_key(herb)
        if key:
            herb_filter = {key: True}
            where = _and_clauses([where, herb_filter]) if where else herb_filter

    hybrid, rerank_status = _hybrid_pool(query, q_emb, where=where)

    if not hybrid and herb_filter:
        # An over-narrow filter (an alias that matched but whose verses were
        # removed by a scope clause) must not leave the user with nothing:
        # retry on the scoped pool alone and say so in the trace.
        trace = trace + [
            f"retrieval: herb filter {herb_filter} matched nothing → "
            f"retried with the requested scope only"
        ]
        hybrid, _rerank_status = _hybrid_pool(query, q_emb, where=state.get("metadata_filter"))
        herb_filter = None

    if not hybrid:
        step = "retrieval: hybrid pool empty → no match returned"
        return {
            "retrieved": [],
            "resolved_chapter": None,
            "confidence": "low",
            "confidence_score": 0.0,
            "user_docs": user_docs,
            "used_documents": used_documents,
            "trace": trace + [step],
        }

    pool = [
        {
            "text": c["text"],
            "meta": c["meta"],
            "score": float(c["_cos"]),
            "verse_id": c["verse_id"],
        }
        for c in hybrid
    ]

    resolved = pool[0]
    canonical = state.get("canonical_term")
    if canonical:
        key = _resolve_chapter_key(canonical)
        if key:
            for c in pool:
                if _chapter_key(c) == key:
                    resolved = c
                    break
        else:
            hit = _resolve_via_metadata(pool, canonical)
            if hit:
                resolved = hit

    # Chapter-consensus voting (see _chapter_scores) was implemented and then
    # removed: on the 40-question eval it fixed eval_11/eval_21 but broke
    # eval_12/eval_14, netting 36/40 against a 37/40 baseline. A chapter vote
    # rewards breadth, so a pool that is broad but shallow (several chapters
    # each contributing one loosely-related verse) can outvote the one chapter
    # that is genuinely on topic. The helpers are kept because the diagnosis is
    # worth preserving; they are not called on any retrieval path.

    selected = [resolved]
    remaining = [c for c in pool if c["verse_id"] != resolved["verse_id"]]
    while len(selected) < 3 and remaining:
        el = {c["verse_id"]: _enrich(c, hybrid) for c in remaining}
        picked = _mmr_pick(list(el.values()), [_enrich(r, hybrid) for r in selected])
        if picked is None:
            break
        selected.append(el[picked["verse_id"]])
        remaining = [c for c in remaining if c["verse_id"] != picked["verse_id"]]

    confidence = _confidence_band(resolved["score"])
    scope = f" + herb filter '{herb}'" if herb_filter else ""
    # MMR below is diversity selection over the 3 verses kept, not a rerank of
    # the pool. The cross-encoder gets its own label so a trace never implies a
    # stage ran when the reranker is disabled, which is the default.
    rerank_note = {
        "applied": "cross-encoder rerank applied",
        "failed": "cross-encoder rerank failed, hybrid order kept",
        "off": "cross-encoder rerank disabled",
    }[rerank_status]
    step = (
        f"retrieval: algorithm='hybrid' vector+BM25; {rerank_note}; "
        f"MMR diversification over top 3{scope} → "
        f"resolved {resolved['verse_id']} (cos {float(resolved['score']):.3f}, {confidence})"
    )
    

    return {
        "retrieved": selected,
        "resolved_chapter": resolved,
        "confidence": confidence,
        "confidence_score": float(resolved["score"]),
        "user_docs": user_docs,
        "used_documents": used_documents,
        "trace": trace + [step],
    }
