import json
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

BACKEND = Path(__file__).resolve().parents[2]

client = chromadb.PersistentClient(path=str(BACKEND / "chroma_db"))
collection = client.get_collection(name="charaka_ai_corpus")
model = SentenceTransformer("all-MiniLM-L6-v2")

with open(BACKEND / "reference" / "mappings.json", encoding="utf-8") as f:
    mappings = json.load(f)

chapter_meta = mappings["chapter_meta"]


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


def retrieve(state):
    q_emb = model.encode([state["expanded_query"]]).tolist()
    results = collection.query(query_embeddings=q_emb, n_results=6)

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