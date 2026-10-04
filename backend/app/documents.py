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
import json
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import chromadb

from app import guardrails

BACKEND = Path(__file__).resolve().parents[1]
USER_DB = BACKEND / "user_chroma_db"
PREFIX = "user_doc_"
CHUNK_SIZE = 700
CHUNK_OVERLAP = 80
MIN_CHUNK = 40
SUPPORTED = (".txt", ".md", ".markdown", ".pdf")

_client = None
_scope_lock = threading.Lock()

# Scope activity is tracked in a sidecar rather than in Chroma collection
# metadata, because Chroma gives no dependable last-modified timestamp across
# the versions this app might run against. The sidecar is a few hundred bytes
# per scope and is pruned on every reap.
SCOPES_FILE = USER_DB / "scopes.json"


def _ttl_days():
    """Days of inactivity before a scope's vectors are reaped. None = disabled.

    Default is disabled on purpose. Deleting a user's uploaded documents is a
    data-loss action, and it is the operator's call when to take it - not
    something that should start happening because a new release shipped. Set
    CHARAKA_DOC_TTL_DAYS=30 (or any positive integer) to enable.
    """
    raw = (os.getenv("CHARAKA_DOC_TTL_DAYS") or "").strip()
    if not raw:
        return None
    try:
        days = int(raw)
    except ValueError:
        return None
    return days if days > 0 else None


def _now():
    return datetime.now(timezone.utc)


def _load_scopes():
    if not SCOPES_FILE.exists():
        return {}
    try:
        data = json.loads(SCOPES_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_scopes(scopes):
    try:
        SCOPES_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = SCOPES_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(scopes, indent=0, sort_keys=True), encoding="utf-8")
        tmp.replace(SCOPES_FILE)
    except OSError:
        # Activity tracking is an optimisation for the reaper, never a
        # correctness requirement for ingest or retrieval. Losing it must not
        # fail an upload.
        pass


def _touch(collection: str):
    """Record activity for a scope so the reaper can judge inactivity."""
    if _ttl_days() is None:
        return
    with _scope_lock:
        scopes = _load_scopes()
        scopes[collection] = _now().isoformat(timespec="seconds")
        _save_scopes(scopes)


def reap_expired(ttl_days=None):
    """Delete document collections idle for longer than the TTL.

    Returns the collection names actually deleted. This is a no-op while the
    TTL is unset, which is the shipped default.
    """
    days = _ttl_days() if ttl_days is None else ttl_days
    if not days or days <= 0:
        return []
    cutoff = _now() - timedelta(days=days)
    deleted = []
    with _scope_lock:
        scopes = _load_scopes()
        live = set()
        try:
            live = {
                c.name for c in _get_client().list_collections()
            }
        except Exception as e:  # noqa: BLE001
            print(f"[documents] cannot list collections for reap: {e}")
            return []
        for collection in sorted(scopes):
            if collection not in live:
                # Tracked but already gone; just forget it.
                scopes.pop(collection, None)
                continue
            stamp = scopes.get(collection)
            try:
                last = datetime.fromisoformat(stamp) if stamp else None
            except (TypeError, ValueError):
                last = None
            # An unparseable or missing stamp is treated as expired: the scope
            # predates this tracker, so we have no evidence it is still in use.
            if last is not None and last > cutoff:
                continue
            try:
                _get_client().delete_collection(collection)
                scopes.pop(collection, None)
                deleted.append(collection)
            except Exception as e:  # noqa: BLE001
                print(f"[documents] failed to reap {collection}: {e}")
        _save_scopes(scopes)
    return deleted


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

    # Sanitize at ingest as well as at synthesis time. Storing the raw chunk means
    # the injection payload also sits in the vector store, where it can be
    # retrieved by any later query in this session, not just the one that
    # uploaded it. Synthesis sanitizes again on the way into the prompt; this is
    # the earlier half of the same defence.
    safe_name = guardrails.safe_label(name)
    chunks = [guardrails.sanitize_untrusted(c) for c in chunks]
    chunks = [c for c in chunks if len(c) >= MIN_CHUNK]
    if not chunks:
        raise ValueError("no usable text after removing non-content")

    from app import embedder

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
        embeddings=embedder.encode(chunks),
        metadatas=[{"doc": safe_name, "i": i} for i in range(len(chunks))],
    )
    _touch(_coll(session_id))
    return {"name": safe_name, "chunks": len(chunks)}


def list_uploads(session_id: str) -> list:
    try:
        coll = _get_client().get_collection(_coll(session_id))
    except Exception:
        return []
    _touch(_coll(session_id))
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
    name = _coll(session_id)
    ok = False
    try:
        _get_client().delete_collection(name)
        ok = True
    except Exception:
        pass
    # Forget the scope either way: if the collection is already gone there is
    # nothing left for the reaper to act on, and leaving the entry behind would
    # make it churn on every pass.
    with _scope_lock:
        scopes = _load_scopes()
        if scopes.pop(name, None) is not None:
            _save_scopes(scopes)
    return ok


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