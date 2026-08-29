import json
import re
from pathlib import Path

import chromadb
import numpy as np
from sentence_transformers import SentenceTransformer

BACKEND = Path(__file__).resolve().parents[2]

client = chromadb.PersistentClient(path=str(BACKEND / "chroma_db"))
collection = client.get_collection(name="charaka_ai_corpus")
model = SentenceTransformer("all-MiniLM-L6-v2")

with open(BACKEND / "reference" / "mappings.json", encoding="utf-8") as f:
    mappings = json.load(f)

with open(BACKEND / "reference" / "herbs.json", encoding="utf-8") as f:
    herbs_data = json.load(f)["herbs"]

with open(BACKEND / "processed" / "herb_mentions.json", encoding="utf-8") as f:
    herb_mentions = json.load(f)

chapter_meta = mappings["chapter_meta"]

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

    results = collection.query(query_embeddings=[q_emb], n_results=6)

    ids = results["ids"][0]
    docs = results["documents"][0]
    metas = results["metadatas"][0]
    dists = results["distances"][0]

    emb_get = collection.get(ids=ids, include=["embeddings"])
    emb_map = dict(zip(emb_get["ids"], emb_get["embeddings"]))

    cosines = []
    for vid in ids:
        cosines.append(_cosine(emb_map[vid], q_emb))

    pool = [
        {"text": doc, "meta": meta, "score": cos, "verse_id": vid}
        for doc, meta, cos, vid in zip(docs, metas, cosines, ids)
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

    confidence = _confidence_band(resolved["score"])
    step = (
        f"retrieval: generic vector search + metadata disambiguation → "
        f"resolved {resolved['verse_id']} (score {float(resolved['score']):.3f}, {confidence})"
    )

    return {
        "retrieved": pool[:3],
        "resolved_chapter": resolved,
        "confidence": confidence,
        "confidence_score": float(resolved["score"]),
        "trace": trace + [step],
    }
