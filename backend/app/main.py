import asyncio
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Literal, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv

from app.graph import charaka_agent
from app import conversations

BACKEND = Path(__file__).resolve().parents[1]
FEEDBACK_LOG = BACKEND / "feedback_log.jsonl"
REFERENCE = BACKEND / "reference"

load_dotenv()
app = FastAPI()
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


class FeedbackRequest(BaseModel):
    query: str
    rating: Literal["up", "down"]
    message_id: Optional[str] = None
    answer: Optional[str] = None
    trace: Optional[List[str]] = None
    dosha: Optional[str] = None


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
        return None
    return [
        {"role": m["role"], "content": m["content"]}
        for m in record["messages"]
        if m.get("content")
    ]


async def _event_stream(
    query: str, history: Optional[List[dict]], conversation_id: Optional[str]
):
    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    if history is None and conversation_id:
        history = _history_from_store(conversation_id)

    def run():
        merged = {}
        synthesize_seen = False
        try:
            for mode, payload in charaka_agent.stream(
                {"query": query, "history": history or []},
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
    while True:
        kind, payload = await queue.get()
        now = time.time()
        if kind == "stage":
            ms = round((now - prev) * 1000)
            prev = now
            yield _sse(
                "stage",
                {
                    "node": payload,
                    "label": STAGE_LABELS.get(payload, payload.replace("_", " ")),
                    "ms": ms,
                },
            )
        elif kind == "token":
            yield _sse("token", {"delta": payload})
        elif kind == "error":
            yield _sse("error", {"message": payload})
            break
        elif kind == "done":
            resp = build_response(payload, latency_ms=round((now - t0) * 1000))
            if payload.get("final_answer"):
                conv_id, conv_title = conversations.save_turn(
                    conversation_id, query, resp
                )
                resp["conversation_id"] = conv_id
                resp["conversation_title"] = conv_title
            yield _sse("done", resp)
            break


@app.post("/ask")
def ask(req: AskRequest):
    result = charaka_agent.invoke({"query": req.query, "history": req.history or []})
    return build_response(result)


@app.post("/ask/stream")
async def ask_stream(req: AskRequest):
    return StreamingResponse(
        _event_stream(req.query, req.history, req.conversation_id),
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


@app.post("/feedback")
def feedback(req: FeedbackRequest):
    FEEDBACK_LOG.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "message_id": req.message_id,
        "query": req.query,
        "rating": req.rating,
        "dosha": req.dosha,
        "answer": req.answer,
        "trace": req.trace,
    }
    with FEEDBACK_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return {"ok": True}


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