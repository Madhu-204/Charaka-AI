"""Rebuild the persisted ChromaDB vector store from the processed corpus.

This is the missing, committed counterpart to ``transform.py``. The store lives
at ``backend/chroma_db`` (git-ignored, regenerable) under the collection
``charaka_ai_corpus`` and is served by ``app/nodes/retriever.py``.

Prerequisites
-------------
Run the data pipeline first so ``processed/charaka_structured.json`` exists::

    python scripts/transform.py
    python scripts/audit_ids.py
    python scripts/build_vector_store.py

The record schema written here must stay in sync with ``retriever.py``:
    document = verse ``text_english``, VERBATIM and clean
    embedding text = ``text_english`` preceded by parent chapter context
    id       = ``verse_id`` (``cs_<sthana>_<chapter>_<verse>``)
    metadata = source, herbs_mentioned, traditional_condition, sthana,
               verified, category_tag, chapter

The stored ``document`` is deliberately kept clean: it is what the citation
cards, the attribution node and the synthesis prompt read, so a "Chapter: ..."
header would surface in the UI as if it were part of the verse. The parent
context lives only in the embedded vector (and in what ``app/nodes/retriever.py``
BM25-indexes), both of which come from ``app.chunking.embed_document``. See that
module for why short title-like verses need it.

Prerequisites
-------------
Run the data pipeline first so ``processed/charaka_structured.json`` exists::

    python scripts/transform.py
    python scripts/audit_ids.py
    python scripts/build_chapter_titles.py
    python scripts/build_vector_store.py

Embeddings use ``sentence-transformers/all-MiniLM-L6-v2`` (CPU) — the same
model the retriever loads for query encoding.
"""

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.chunking import (  # noqa: E402
    TITLES_PATH,
    corpus_sha256,
    embed_document,
    herb_key,
)

import chromadb
from sentence_transformers import SentenceTransformer

BACKEND = Path(__file__).resolve().parents[1]
PROCESSED = BACKEND / "processed"
CHROMA_DIR = BACKEND / "chroma_db"
COLLECTION = "charaka_ai_corpus"
MODEL_NAME = "all-MiniLM-L6-v2"
BATCH = 64


def _metadata(record: dict) -> dict:
    """Serialize one corpus record into a Chroma-legal metadata dict.

    Chroma rejects ``None`` and list values, so nulls become ``"none"``
    (matching the historical store) and herb lists are comma-joined.

    Herbs are ALSO written as sparse boolean keys (``herb_ashwagandha: true``).
    That is what makes herb filtering possible: on Chroma 1.5.9 a ``$contains``
    clause against a *string* metadata field silently returns an empty result
    set rather than raising, so filtering the comma-joined ``herbs_mentioned``
    string would look like it worked and return nothing in production. Verified
    against the live store and pinned by tests/test_retrieval.py.

    Only the herbs a verse actually mentions are written. A missing key is
    equivalent to "false" for a ``{"key": True}`` filter, and sparseness keeps
    the store at ~1.4k extra fields instead of 93x2,490.
    """
    condition = record.get("traditional_condition")
    herbs = record.get("herbs_mentioned") or []
    if isinstance(herbs, str):
        herbs = [herbs] if herbs else []
    meta = {
        "source": record.get("source") or "",
        "herbs_mentioned": ", ".join(herbs),
        "traditional_condition": condition if condition else "none",
        "sthana": record.get("sthana") or "",
        "verified": bool(record.get("verified")),
        "category_tag": record.get("category_tag") or "none",
        "chapter": int(record.get("chapter") or 0),
    }
    for herb in herbs:
        key = herb_key(herb)
        if key:
            meta[key] = True
    return meta


def build(force: bool = False) -> dict:
    corpus_path = PROCESSED / "charaka_structured.json"
    if not corpus_path.is_file():
        sys.exit(
            f"missing {corpus_path} — run `python scripts/transform.py` first"
        )

    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    ids, docs, embeds_text, metas = [], [], [], []
    for record in corpus:
        text = (record.get("text_english") or "").strip()
        if not text or not record.get("verse_id"):
            continue
        ids.append(record["verse_id"])
        docs.append(text)
        embeds_text.append(embed_document(record))
        metas.append(_metadata(record))

    if not ids:
        sys.exit("no usable records in the processed corpus")

    if CHROMA_DIR.exists() and force:
        shutil.rmtree(CHROMA_DIR)
        print(f"[build] removed existing store at {CHROMA_DIR}")

    print(f"[build] encoding {len(docs)} verses with {MODEL_NAME} ...")
    model = SentenceTransformer(MODEL_NAME)
    embeddings = model.encode(
        embeds_text, batch_size=BATCH, show_progress_bar=True, convert_to_numpy=True
    ).tolist()

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    try:
        client.delete_collection(COLLECTION)
        print(f"[build] dropped stale collection '{COLLECTION}'")
    except Exception:  # noqa: BLE001 — collection may not exist yet
        pass
    # Record what this index was built from, so a later run can tell whether the
    # corpus has moved on. app.chunking.index_freshness() compares the two and
    # surfaces the result on /healthz. Also record the embedding model and the
    # chapter-title table, because changing either silently invalidates every
    # vector without changing the corpus hash.
    titles_sha = (
        hashlib.sha256(TITLES_PATH.read_bytes()).hexdigest()
        if TITLES_PATH.is_file()
        else ""
    )
    # Default L2 space (encoder emits L2-normalized vectors, so L2 and cosine
    # rankings coincide). High construction/search ef makes the approximate
    # index behave like exact search, so a rebuild is stable regardless of
    # insertion order and does not silently drop true neighbors.
    collection = client.create_collection(
        name=COLLECTION,
        metadata={
            "hnsw:construction_ef": 400,
            "hnsw:search_ef": 400,
            "hnsw:M": 32,
            "corpus_sha256": corpus_sha256(),
            "embedding_model": MODEL_NAME,
            "chapter_titles_sha256": titles_sha,
        },
    )

    for start in range(0, len(ids), BATCH):
        stop = start + BATCH
        collection.add(
            ids=ids[start:stop],
            documents=docs[start:stop],
            metadatas=metas[start:stop],
            embeddings=embeddings[start:stop],
        )

    count = collection.count()
    print(f"[build] wrote {count} vectors to {CHROMA_DIR} ('{COLLECTION}')")
    if count != len(ids):
        sys.exit(f"count mismatch: expected {len(ids)}, got {count}")
    return {"collection": COLLECTION, "count": count, "path": str(CHROMA_DIR)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="delete the existing chroma_db directory before rebuilding",
    )
    args = parser.parse_args()
    build(force=args.force)
