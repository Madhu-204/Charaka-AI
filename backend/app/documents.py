"""Session-scoped ephemeral document ingest (task 39).

Uploaded files (txt / md / pdf) are chunked, embedded with the shared local
model and stored in a per-session Chroma collection that is clearly separate
from the trusted Charaka corpus (different persistent client + collection
namespace `user_doc_<session>`). Nothing here is ever blended into the
classical corpus retrieval path — user chunks surface only as an explicitly
labelled "USER-SUPPLIED DOCUMENT CONTEXT" block in synthesis.
"""

import hashlib
import io
import re
from pathlib import Path

import chromadb

BACKEND = Path(__file__).resolve().parents[1]
USER_DB = BACKEND / "user_chroma_db"
PREFIX = "user_doc_"
CHUNK_SIZE = 700
CHUNK_OVERLAP = 80
MIN_CHUNK = 40
SUPPORTED = (".txt", ".md", ".markdown", ".pdf")

_client = None


def _get_client():
    global _client
    if _client is None:
        USER_DB.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=str(USER_DB))
    return _client


def _coll(session_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_-]", "", session_id)[:48]
    return f"{PREFIX}{safe}"


def parse_file(name: str, data: bytes) -> str:
    lower = (name or "").lower()
    if not any(lower.endswith(ext) for ext in SUPPORTED):
        raise ValueError("unsupported file — upload a .txt, .md or .pdf")
    if lower.endswith(".pdf"):
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    return data.decode("utf-8", errors="ignore")


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP):
    words = re.findall(r"\S+", text)
    chunks, i = [], 0
    step = max(1, size - overlap)
    while i < len(words):
        chunks.append(" ".join(words[i : i + size]))
        i += step
    return [c for c in chunks if len(c) >= MIN_CHUNK]


def upload(session_id: str, name: str, data: bytes) -> dict:
    text = parse_file(name, data)
    if not text.strip():
        raise ValueError("no readable text found in this file")
    chunks = chunk_text(text)
    if not chunks:
        raise ValueError("file is too short to extract guidance from")

    from app.nodes.retriever import model

    coll = _get_client().get_or_create_collection(
        _coll(session_id), metadata={"hnsw:space": "cosine"}
    )
    ids = [
        f"{hashlib.sha1(f'{name}:{i}'.encode()).hexdigest()[:14]}_{i}"
        for i in range(len(chunks))
    ]
    coll.upsert(
        ids=ids,
        documents=chunks,
        embeddings=model.encode(chunks).tolist(),
        metadatas=[{"doc": name, "i": i} for i in range(len(chunks))],
    )
    return {"name": name, "chunks": len(chunks)}


def list_uploads(session_id: str) -> list:
    try:
        coll = _get_client().get_collection(_coll(session_id))
    except Exception:
        return []
    data = coll.get(include=["metadatas"]) or {}
    counts = {}
    for meta in data.get("metadatas") or []:
        name = (meta or {}).get("doc", "document")
        counts[name] = counts.get(name, 0) + 1
    return sorted(
        [{"name": n, "chunks": c} for n, c in counts.items()],
        key=lambda d: d["name"],
    )


def remove(session_id: str) -> bool:
    try:
        _get_client().delete_collection(_coll(session_id))
        return True
    except Exception:
        return False


def search(session_id: str, q_emb, top: int = 2) -> list:
    try:
        coll = _get_client().get_collection(_coll(session_id))
    except Exception:
        return []
    if coll.count() == 0:
        return []
    try:
        res = coll.query(
            query_embeddings=[q_emb],
            n_results=top,
            include=["documents", "metadatas", "distances"],
        )
    except Exception as e:  # noqa: BLE001
        print(f"[documents] user-doc query failed: {e}")
        return []
    out = []
    ids = res["ids"][0]
    docs = res["documents"][0]
    metas = res["metadatas"][0]
    dists = res["distances"][0]
    for i in range(len(ids)):
        out.append(
            {
                "text": docs[i],
                "doc": (metas[i] or {}).get("doc", "uploaded document"),
                "score": round(1 - float(dists[i]), 4),
            }
        )
    return out