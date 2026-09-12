import asyncio
import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Literal, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv

from app.graph import charaka_agent
from app import cache, conversations, ratelimit, stats, trace
from app.nodes.summarize import build_summary

BACKEND = Path(__file__).resolve().parents[1]
FEEDBACK_LOG = BACKEND / "feedback_log.jsonl"
REFERENCE = BACKEND / "reference"
PROCESSED = BACKEND / "processed"
TRACES_DIR = BACKEND / "traces"
EVAL_RESULTS = BACKEND / "eval_results.json"

load_dotenv()
app = FastAPI()

API_KEY = os.getenv("CHARAKA_API_KEY")
_QUERY_CACHE = cache.LRUCache(
    capacity=int(os.getenv("CHARAKA_CACHE_SIZE", "64")),
    ttl=int(os.getenv("CHARAKA_CACHE_TTL", "3600")),
)
_LIMITER = ratelimit.RateLimiter(
    per_minute=int(os.getenv("CHARAKA_RATE_LIMIT", "30")),
    burst=int(os.getenv("CHARAKA_RATE_BURST", "60")),
)
_FEEDBACK_STATS = stats.FeedbackStats(FEEDBACK_LOG)


def guard_ask(
    request: Request, x_api_key: Optional[str] = Header(default=None)
) -> None:
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="invalid or missing API key")
    client_id = x_api_key or (
        request.client.host if request.client else "local"
    )
    if not _LIMITER.allow(client_id):
        raise HTTPException(
            status_code=429,
            detail="rate limit exceeded — slow down and retry shortly",
            headers={"Retry-After": "5"},
        )


STHANA_ORDER = ["sutrasthana", "vimanasthana", "sharirasthana", "chikitsasthana"]
STHANA_TITLES = {
    "sutrasthana": "Sutra Sthana — General Principles",
    "vimanasthana": "Vimana Sthana — Assessment & Physiology",
    "sharirasthana": "Sharira Sthana — Body & Embryology",
    "chikitsasthana": "Chikitsa Sthana — Therapeutics",
}

try:
    _CORPUS = json.loads((PROCESSED / "charaka_structured.json").read_text(encoding="utf-8"))
except Exception:  # noqa: BLE001
    _CORPUS = []
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

HIGH_SCORE = 0.60
MEDIUM_SCORE = 0.45
VERSE_TEXT_CHARS = 280

STAGE_LABELS = {
    "check_emergency": "Checking for red flags",
    "tag_dosha": "Analyzing dosha pattern",
    "expand_query": "Expanding query",
    "route_tools": "Choosing retrieval strategy",
    "retrieve": "Searching 2,490 verses",
    "clarify": "Asking to disambiguate",
    "check_safety": "Checking herb safety",
    "synthesize": "Grounding answer in classical texts",
    "grounding": "Verifying citations",
}


class AskRequest(BaseModel):
    query: str
    history: Optional[List[dict]] = None
    conversation_id: Optional[str] = None
    dosha_profile: Optional[str] = None


class FeedbackRequest(BaseModel):
    query: str
    rating: Literal["up", "down"]
    message_id: Optional[str] = None
    answer: Optional[str] = None
    trace: Optional[List[str]] = None
    dosha: Optional[str] = None
    category_tag: Optional[str] = None
    chapter: Optional[str] = None


def _confidence_band(score) -> str:
    if score > HIGH_SCORE:
        return "high"
    if score > MEDIUM_SCORE:
        return "medium"
    return "low"


def _verse_summary(candidate: dict) -> dict:
    score = float(candidate["score"])
    return {
        "verse_id": candidate["verse_id"],
        "chapter": f"{candidate['meta']['sthana']}/{candidate['meta']['chapter']}",
        "score": round(score, 4),
        "text": candidate.get("text", "")[:VERSE_TEXT_CHARS],
        "confidence": _confidence_band(score),
    }


def build_response(result: dict, latency_ms: Optional[int] = None) -> dict:
    rc = result.get("resolved_chapter") or {}
    is_emergency = result["is_emergency"]
    response = {
        "answer": result["final_answer"],
        "is_emergency": is_emergency,
        "is_clarification": bool(result.get("is_clarification")),
        "confidence": result.get("confidence"),
        "chapter": rc.get("meta", {}).get("chapter") if not is_emergency else None,
        "category_tag": rc.get("meta", {}).get("category_tag") if not is_emergency else None,
        "safety_flags": result.get("safety_flags", []),
        "dosha": result.get("dosha") if not is_emergency else None,
        "latency_ms": latency_ms,
    }
    if not is_emergency:
        response["reasoning_trace"] = {
            "steps": result.get("trace", []),
            "canonical_term": result.get("canonical_term"),
            "retrieved_verses": [_verse_summary(c) for c in result.get("retrieved", [])],
            "confidence_score": result.get("confidence_score"),
            "herbs_found": result.get("herbs_found", []),
            "dosha_scores": result.get("dosha_scores"),
            "safety_sources": result.get("safety_sources"),
            "verification_notes": result.get("verification_notes", []),
            "source_disagreements": result.get("source_disagreements", []),
            "grounding": {
                "score": result.get("grounding_score"),
                "cited": result.get("grounding_cited", []),
                "notes": result.get("grounding_notes", []),
            },
        }
        response["grounding"] = {
            "score": result.get("grounding_score"),
            "cited": result.get("grounding_cited", []),
            "notes": result.get("grounding_notes", []),
        }
    return response


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _history_from_store(conversation_id):
    record = conversations.get_conversation(conversation_id)
    if not record:
        return {"history": None, "dosha_profile": None}
    return {
        "history": [
            {"role": m["role"], "content": m["content"]}
            for m in record["messages"]
            if m.get("content")
        ],
        "dosha_profile": record.get("dosha_profile"),
    }


def _suggest_questions(result) -> list:
    if result.get("is_emergency") or result.get("is_clarification"):
        return []
    rc = result.get("resolved_chapter") or {}
    meta = rc.get("meta", {}) or {}
    condition = meta.get("traditional_condition") or meta.get("category_tag")
    herbs = result.get("herbs_found", [])
    dosha = result.get("dosha")

    out = []
    if herbs:
        out.append(f"How should {herbs[0].title()} be taken — dose and preparation?")
    if condition:
        out.append(f"What diet and habits suit {condition}?")
    if dosha:
        out.append(f"Which foods should be avoided on a {dosha} pattern?")
    if condition:
        out.append(f"What are the classical causes of {condition}?")
    out.append("What should I avoid while treating this?")
    return list(dict.fromkeys(out))[:3]


def _attach_summaries(resp, query, result):
    resp["suggestions"] = _suggest_questions(result)
    if result.get("final_answer") and not result["is_emergency"]:
        try:
            resp["summary"] = build_summary(query, resp["answer"], result)
        except Exception as e:  # noqa: BLE001
            print(f"[main] summary failed ({e})")
    return resp


def _resolved_label(result) -> Optional[str]:
    rc = result.get("resolved_chapter") or {}
    meta = rc.get("meta")
    if not meta:
        return None
    return f"{meta.get('sthana')}/{meta.get('chapter')}"


def _chunks(text: str, size: int = 60):
    for i in range(0, len(text), size):
        yield text[i : i + size]


def _run_graph_collect(state):
    """Drive the graph via its stream so we can capture per-node latency + tokens."""
    merged = {}
    node_times = []
    token_count = 0
    prev = time.time()
    for mode, payload in charaka_agent.stream(
        state, stream_mode=["updates", "messages"]
    ):
        if mode == "updates":
            node = next(iter(payload))
            merged.update(payload[node])
            now = time.time()
            node_times.append([node, round((now - prev) * 1000), 0])
            prev = now
        else:
            chunk, meta = payload
            if meta.get("langgraph_node") == "synthesize":
                text = getattr(chunk, "content", "")
                if isinstance(text, str) and text:
                    token_count += len(text.split())
    if node_times:
        node_times[-1][2] = token_count
    return merged, node_times, token_count


async def _event_stream(
    query: str, history: Optional[List[dict]], conversation_id: Optional[str],
    dosha_profile: Optional[str],
):
    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    if history is None and conversation_id:
        store = _history_from_store(conversation_id)
        history = store["history"]
        dosha_profile = dosha_profile or store["dosha_profile"]

    cacheable = conversation_id is None
    cache_key = (
        cache.LRUCache.key_for(query, dosha_profile) if cacheable else None
    )
    if cache_key:
        cached = _QUERY_CACHE.get(cache_key)
        if cached:
            trace.write_trace(
                TRACES_DIR,
                query,
                [("cache", 0, 0)],
                0,
                0,
                cache_hit=True,
                dosha=dosha_profile,
            )
            yield _sse(
                "stage",
                {"node": "cache", "label": "Serving cached answer", "ms": 0},
            )
            for part in _chunks(cached.get("answer", "")):
                yield _sse("token", {"delta": part})
            hit = dict(cached)
            hit["cache_hit"] = True
            yield _sse("done", hit)
            return

    state = {"query": query, "history": history or []}
    if dosha_profile:
        state["dosha_profile"] = dosha_profile

    def run():
        merged = {}
        synthesize_seen = False
        try:
            for mode, payload in charaka_agent.stream(
                state,
                stream_mode=["updates", "messages"],
            ):
                if mode == "updates":
                    node = next(iter(payload))
                    merged.update(payload[node])
                    queue.put_nowait(("stage", node))
                else:
                    chunk, meta = payload
                    if meta.get("langgraph_node") == "synthesize":
                        if not synthesize_seen:
                            synthesize_seen = True
                            queue.put_nowait(("stage", "synthesize"))
                        text = getattr(chunk, "content", "")
                        if isinstance(text, str) and text:
                            queue.put_nowait(("token", text))
        except Exception as e:  # noqa: BLE001
            queue.put_nowait(("error", str(e)))
        finally:
            queue.put_nowait(("done", merged))

    threading.Thread(target=run, daemon=True).start()

    t0 = time.time()
    prev = t0
    node_times = []
    token_count = 0
    while True:
        kind, payload = await queue.get()
        now = time.time()
        if kind == "stage":
            ms = round((now - prev) * 1000)
            prev = now
            node_times.append((payload, ms, 0))
            yield _sse(
                "stage",
                {
                    "node": payload,
                    "label": STAGE_LABELS.get(payload, payload.replace("_", " ")),
                    "ms": ms,
                },
            )
        elif kind == "token":
            token_count += len(payload.split())
            yield _sse("token", {"delta": payload})
        elif kind == "error":
            yield _sse("error", {"message": payload})
            break
        elif kind == "done":
            latency = round((now - t0) * 1000)
            resp = build_response(payload, latency_ms=latency)
            if payload.get("final_answer"):
                resp = _attach_summaries(resp, query, payload)
                conv_id, conv_title = conversations.save_turn(
                    conversation_id, query, resp
                )
                resp["conversation_id"] = conv_id
                resp["conversation_title"] = conv_title
            resp["cache_hit"] = False
            if node_times:
                node_times[-1] = (
                    node_times[-1][0],
                    node_times[-1][1],
                    token_count,
                )
            trace.write_trace(
                TRACES_DIR,
                query,
                node_times,
                token_count,
                latency,
                dosha=payload.get("dosha"),
                resolved_chapter=_resolved_label(payload),
            )
            if cache_key and payload.get("final_answer") and not payload.get(
                "is_emergency"
            ):
                _QUERY_CACHE.set(cache_key, resp)
            yield _sse("done", resp)
            break


@app.post("/ask", dependencies=[Depends(guard_ask)])
def ask(req: AskRequest):
    state = {"query": req.query, "history": req.history or []}
    if req.dosha_profile:
        state["dosha_profile"] = req.dosha_profile

    cache_key = (
        cache.LRUCache.key_for(req.query, req.dosha_profile)
        if not req.history
        else None
    )
    if cache_key:
        cached = _QUERY_CACHE.get(cache_key)
        if cached:
            resp = dict(cached)
            resp["cache_hit"] = True
            trace.write_trace(
                TRACES_DIR,
                req.query,
                [("cache", 0, 0)],
                0,
                0,
                cache_hit=True,
                dosha=req.dosha_profile,
            )
            return resp

    t0 = time.time()
    result, node_times, token_count = _run_graph_collect(state)
    latency = round((time.time() - t0) * 1000)
    resp = build_response(result, latency_ms=latency)
    if result.get("final_answer"):
        resp = _attach_summaries(resp, req.query, result)
    resp["cache_hit"] = False
    if cache_key and result.get("final_answer") and not result.get("is_emergency"):
        _QUERY_CACHE.set(cache_key, resp)
    trace.write_trace(
        TRACES_DIR,
        req.query,
        node_times,
        token_count,
        latency,
        dosha=result.get("dosha"),
        resolved_chapter=_resolved_label(result),
    )
    return resp


@app.post("/ask/stream", dependencies=[Depends(guard_ask)])
async def ask_stream(req: AskRequest):
    return StreamingResponse(
        _event_stream(req.query, req.history, req.conversation_id, req.dosha_profile),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/conversations")
def list_conversations():
    return {"conversations": conversations.list_conversations()}


@app.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str):
    record = conversations.get_conversation(conversation_id)
    if record is None:
        return {"ok": False, "error": "not_found"}
    return {"ok": True, "conversation": record}


@app.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: str):
    return {"ok": conversations.delete_conversation(conversation_id)}


@app.get("/corpus/sthanas")
def corpus_sthanas():
    chapters_by_sthana = {}
    for v in _CORPUS:
        key = v["sthana"]
        bucket = chapters_by_sthana.setdefault(
            key, {}
        )
        ch = bucket.setdefault(
            v["chapter"],
            {
                "chapter": v["chapter"],
                "verse_count": 0,
                "condition": v.get("traditional_condition"),
                "category": v.get("category_tag"),
            },
        )
        ch["verse_count"] += 1

    sthanas = []
    for sthana in STHANA_ORDER:
        if sthana not in chapters_by_sthana:
            continue
        chapters = sorted(
            chapters_by_sthana[sthana].values(), key=lambda c: c["chapter"]
        )
        sthanas.append(
            {
                "sthana": sthana,
                "title": STHANA_TITLES.get(sthana, sthana),
                "chapters": chapters,
                "verse_count": sum(c["verse_count"] for c in chapters),
            }
        )
    return {"sthanas": sthanas, "total_verses": len(_CORPUS)}


@app.get("/corpus/{sthana}/{chapter}")
def corpus_verses(sthana: str, chapter: int):
    ch = int(chapter)
    verses = [
        {
            "verse_id": v["verse_id"],
            "text": v["text_english"],
            "sanskrit": v.get("text_sanskrit"),
            "condition": v.get("traditional_condition"),
            "category": v.get("category_tag"),
            "herbs": [],
        }
        for v in _CORPUS
        if v["sthana"] == sthana and v["chapter"] == ch
    ]
    return {"ok": bool(verses), "sthana": sthana, "chapter": ch, "verses": verses}


class CorpusSearchRequest(BaseModel):
    query: str
    limit: int = 8


@app.post("/corpus/search")
def corpus_search(req: CorpusSearchRequest):
    from app.nodes.retriever import search_verses

    limit = max(1, min(req.limit, 25))
    return {"query": req.query, "results": search_verses(req.query, limit=limit)}


@app.post("/feedback")
def feedback(req: FeedbackRequest):
    FEEDBACK_LOG.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "message_id": req.message_id,
        "query": req.query,
        "rating": req.rating,
        "dosha": req.dosha,
        "category_tag": req.category_tag,
        "chapter": req.chapter,
        "answer": req.answer,
        "trace": req.trace,
    }
    with FEEDBACK_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return {"ok": True}


@app.get("/stats")
def get_stats():
    data = _FEEDBACK_STATS.snapshot()
    data["cache"] = _QUERY_CACHE.stats()
    return data


@app.get("/traces")
def list_traces(limit: int = 50):
    limit = max(1, min(limit, 200))
    return {"traces": trace.list_traces(TRACES_DIR, limit)}


@app.get("/traces/{run_id}")
def get_trace(run_id: str):
    record = trace.get_trace(TRACES_DIR, run_id)
    if record is None:
        return {"ok": False, "error": "not_found"}
    return {"ok": True, "trace": record}


class EvalRunRequest(BaseModel):
    corner: bool = True
    mode: Literal["retrieval", "full"] = "retrieval"


def _public_eval_row(row: dict) -> dict:
    return {
        "eval_id": row["eval_id"],
        "corner": row["corner"],
        "known_gap": row["known_gap"],
        "question": row["question"],
        "expected": row["expected"],
        "resolved": row["resolved"],
        "confidence": row["confidence"],
        "resolved_hit": row["resolved_hit"],
        "top_n_hit": row["top_n_hit"],
        "emergency": row["emergency"],
        "herbs_found": len(row["herbs_found"]),
        "safety_flags": len(row["safety_flags"]),
    }


async def _eval_event_stream(corner: bool, mode: str):
    from app.eval_suite import load_eval_items, run_question, summarize

    queue: asyncio.Queue = asyncio.Queue()
    items = load_eval_items(corner=corner)

    def run():
        rows = []
        try:
            for i, item in enumerate(items):
                row = run_question(item, mode=mode)
                rows.append(row)
                queue.put_nowait(
                    (
                        "item",
                        {
                            "index": i + 1,
                            "total": len(items),
                            **_public_eval_row(row),
                        },
                    )
                )
                time.sleep(0.05)
            summary = summarize(rows)
            payload = {
                "summary": summary,
                "rows": [_public_eval_row(r) for r in rows],
            }
            try:
                EVAL_RESULTS.write_text(
                    json.dumps(payload, ensure_ascii=False),
                    encoding="utf-8",
                )
            except OSError:
                pass
            queue.put_nowait(("done", payload))
        except Exception as e:  # noqa: BLE001
            queue.put_nowait(("error", str(e)))

    threading.Thread(target=run, daemon=True).start()

    while True:
        kind, payload = await queue.get()
        yield _sse(kind, payload)
        if kind in ("done", "error"):
            break


@app.post("/eval/run")
async def eval_run(req: EvalRunRequest):
    return StreamingResponse(
        _eval_event_stream(req.corner, req.mode),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/eval/last")
def eval_last():
    if not EVAL_RESULTS.exists():
        return {"ok": False, "error": "no_runs"}
    try:
        return {"ok": True, **json.loads(EVAL_RESULTS.read_text(encoding="utf-8"))}
    except (OSError, json.JSONDecodeError):
        return {"ok": False, "error": "unreadable"}


def _load_reference(name: str):
    with open(REFERENCE / name, encoding="utf-8") as f:
        return json.load(f)


@app.get("/herbs")
def herbs():
    herb_list = _load_reference("herbs.json")["herbs"]
    safety_list = _load_reference("herb_safety.json")
    botanicals = _load_reference("botanical_names.json")

    safety_by_key = {}
    for entry in safety_list:
        safety_by_key[entry["herb"]] = entry
        for alias in _load_reference("herbs.json").get("herbs", []):
            if alias["name"] != entry["herb"]:
                continue
            for a in alias.get("aliases", []):
                safety_by_key.setdefault(a, entry)

    catalog = []
    for h in herb_list:
        name = h["name"]
        entry = safety_by_key.get(name)
        if entry is None:
            for a in h.get("aliases", []):
                if a in safety_by_key:
                    entry = safety_by_key[a]
                    break
        if entry is None:
            entry = {}

        dosha_tags = []
        caution = (entry.get("dosha_caution") or "").lower()
        for d in ("vata", "pitta", "kapha"):
            if d in caution:
                dosha_tags.append(d.capitalize())

        catalog.append(
            {
                "name": name,
                "aliases": h.get("aliases", []),
                "botanical": botanicals.get(name),
                "dosha_tags": dosha_tags,
                "modern_source_verified": bool(entry.get("modern_source_verified")),
                "api_of_india_verified": bool(entry.get("api_of_india_verified")),
                "dosha_caution": entry.get("dosha_caution", ""),
                "contraindications": entry.get("contraindications", []),
                "interactions": entry.get("interactions", []),
                "pregnancy_flag": entry.get("pregnancy_flag", ""),
                "classical_source": entry.get("classical_source", ""),
                "modern_source": entry.get("modern_source", ""),
                "verification_note": entry.get("verification_note", ""),
            }
        )

    catalog.sort(key=lambda h: h["name"])
    return {"herbs": catalog, "count": len(catalog), "covered": len(safety_list)}