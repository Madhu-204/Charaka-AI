import json
import math
import os
import re
from collections import Counter
from pathlib import Path

import chromadb
import numpy as np
from sentence_transformers import SentenceTransformer

BACKEND = Path(__file__).resolve().parents[2]

client = chromadb.PersistentClient(path=str(BACKEND / "chroma_db"))
collection = client.get_collection(name="charaka_ai_corpus")
model = SentenceTransformer("all-MiniLM-L6-v2")

_ALL = collection.get(include=["documents"])

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
        restrict = set(restrict) if restrict is not None else None
        scored = []
        for idx in range(self.N):
            if restrict is not None and self.ids[idx] not in restrict:
                continue
            s = self._score_doc(qtok, self.tokens[idx])
            if s > 0:
                scored.append((self.ids[idx], s))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top]


BM25_INDEX = _BM25(_ALL["ids"], _ALL["documents"])

_RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
_reranker = None
# Eval-gated: ms-marco rerank regressed chapter disambiguation on the 28-question
# set (23/28 hybrid-only → 20/28 reranked), so it stays optional/off by default.
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
    reranker = _get_reranker()
    if reranker is None:
        return None
    try:
        texts = [c["text"][:800] for c in hybrid[:14]]
        pairs = [(query, t) for t in texts]
        scores = reranker.predict(pairs, show_progress_bar=False)
        return list(zip(hybrid[:14], [float(s) for s in scores]))
    except Exception as e:  # noqa: BLE001
        print(f"[retriever] rerank failed ({e}) → hybrid ranking used")
        return None

with open(BACKEND / "reference" / "mappings.json", encoding="utf-8") as f:
    mappings = json.load(f)

with open(BACKEND / "reference" / "herbs.json", encoding="utf-8") as f:
    herbs_data = json.load(f)["herbs"]

with open(BACKEND / "processed" / "herb_mentions.json", encoding="utf-8") as f:
    herb_mentions = json.load(f)

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

VERSES_BY_HERB = {}
for row in herb_mentions:
    VERSES_BY_HERB.setdefault(row["herb"], []).append(row["verse_id"])


def _chapter_key(candidate):
    return f"{candidate['meta']['sthana']}/{candidate['meta']['chapter']}"


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
            r = collection.query(query_embeddings=[model.encode([sub]).tolist()[0]], n_results=6)
            absorb(r["ids"][0], r["documents"][0], r["metadatas"][0])
        except Exception as e:
            print(f"[retriever] subquery '{sub}' failed: {e}")

    cand_ids = list(candidates)
    for vid, bscore in BM25_INDEX.search(query, top=12, restrict=cand_ids):
        if vid in candidates:
            candidates[vid]["_bm25"] = bscore

    if not cand_ids:
        return []

    emb_get = collection.get(ids=cand_ids, include=["embeddings"])
    emb_map = dict(zip(emb_get["ids"], emb_get["embeddings"]))

    have = []
    for vid in cand_ids:
        cand = candidates[vid]
        cos = _cosine(emb_map[vid], q_emb)
        cand["_cos"] = cos
        cand["_bm25"] = cand.get("_bm25", 0.0)
        cand["_emb"] = emb_map[vid]
        cand["verse_id"] = vid
        have.append(cand)

    cos_norm = _minmax([c["_cos"] for c in have])
    bm_norm = _minmax([c["_bm25"] for c in have])
    for c, cn, bn in zip(have, cos_norm, bm_norm):
        c["_fused"] = 0.5 * cn + 0.5 * bn

    have.sort(key=lambda c: c["_fused"], reverse=True)

    reranked = _apply_reranker(have, query)
    if reranked:
        rerank_vals = [s for _, s in reranked]
        norm = _minmax(rerank_vals)
        for (c, _s), n in zip(reranked, norm):
            c["_fused"] = n
        have.sort(key=lambda c: c["_fused"], reverse=True)

    return have


def _herb_retrieve(herb_name, expanded_query, query_embedding):
    verse_ids = VERSES_BY_HERB.get(herb_name, [])
    if not verse_ids:
        return None

    unique_ids = list(dict.fromkeys(verse_ids))

    results = collection.get(
        ids=unique_ids, include=["documents", "metadatas", "embeddings"]
    )

    if not results["ids"]:
        return None

    embeddings = np.array(results["embeddings"])
    q_emb = np.array(query_embedding).flatten()
    similarities = [_cosine(e, q_emb) for e in embeddings]

    ranked = sorted(
        zip(results["ids"], results["documents"], results["metadatas"], similarities),
        key=lambda x: x[3],
        reverse=True,
    )

    pool = [
        {"text": doc, "meta": meta, "score": float(score), "verse_id": vid}
        for vid, doc, meta, score in ranked
    ]

    resolved = pool[0]

    confidence = _confidence_band(resolved["score"])

    return {
        "retrieved": pool[:3],
        "resolved_chapter": resolved,
        "confidence": confidence,
        "confidence_score": float(resolved["score"]),
    }


def search_verses(query, limit=8):
    """Expose ranked hybrid results as plain text (used by the corpus search page)."""
    q_emb = model.encode([query]).tolist()[0]
    pool = _hybrid_pool(query, q_emb)
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

    herb = _detect_herb(query)
    if herb:
        herb_result = _herb_retrieve(herb, query, q_emb)
        if herb_result:
            resolved = herb_result["resolved_chapter"]
            step = (
                f"retrieval: herb path via '{herb}' verse index → "
                f"resolved {resolved['verse_id']} "
                f"(score {herb_result['confidence_score']:.3f}, {herb_result['confidence']})"
            )
            return {**herb_result, "trace": trace + [step]}

    hybrid = _hybrid_pool(query, q_emb, where=state.get("metadata_filter"))

    if not hybrid:
        step = "retrieval: hybrid pool empty → no match returned"
        return {
            "retrieved": [],
            "resolved_chapter": None,
            "confidence": "low",
            "confidence_score": 0.0,
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
    step = (
        f"retrieval: algorithm='hybrid' vector+BM25 + MMR rerank → "
        f"resolved {resolved['verse_id']} (cos {float(resolved['score']):.3f}, {confidence})"
    )

    return {
        "retrieved": selected,
        "resolved_chapter": resolved,
        "confidence": confidence,
        "confidence_score": float(resolved["score"]),
        "trace": trace + [step],
    }
