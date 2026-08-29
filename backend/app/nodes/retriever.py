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


def _herb_retrieve(herb_name, expanded_query, query_embedding):
    verse_ids = VERSES_BY_HERB.get(herb_name, [])
    if not verse_ids:
        return None

    unique_ids = list(dict.fromkeys(verse_ids))
    fetch_ids = unique_ids[:10]

    results = collection.get(
        ids=fetch_ids, include=["documents", "metadatas", "embeddings"]
    )

    if not results["ids"]:
        return None

    embeddings = np.array(results["embeddings"])
    q_emb = np.array(query_embedding).flatten()
    similarities = embeddings @ q_emb

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

    return {"retrieved": pool[:3], "resolved_chapter": resolved, "confidence": "high"}


def retrieve(state):
    query = state.get("expanded_query", state.get("query", ""))

    q_emb = model.encode([query]).tolist()[0]

    herb = _detect_herb(query)
    if herb:
        herb_result = _herb_retrieve(herb, query, q_emb)
        if herb_result:
            return herb_result

    results = collection.query(query_embeddings=[q_emb], n_results=6)

    pool = [
        {"text": doc, "meta": meta, "score": 1 - dist, "verse_id": vid}
        for doc, meta, dist, vid in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
            results["ids"][0],
        )
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

    confidence = "high" if resolved["score"] > 0.5 else "low"

    return {
        "retrieved": pool[:3],
        "resolved_chapter": resolved,
        "confidence": confidence,
    }
