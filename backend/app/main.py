import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Literal, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

from app.graph import charaka_agent

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


class AskRequest(BaseModel):
    query: str


class FeedbackRequest(BaseModel):
    query: str
    rating: Literal["up", "down"]
    message_id: Optional[str] = None
    answer: Optional[str] = None
    trace: Optional[List[str]] = None
    dosha: Optional[str] = None


@app.post("/ask")
def ask(req: AskRequest):
    result = charaka_agent.invoke({"query": req.query})
    rc = result.get("resolved_chapter") or {}
    response = {
        "answer": result["final_answer"],
        "is_emergency": result["is_emergency"],
        "confidence": result.get("confidence"),
        "chapter": rc.get("meta", {}).get("chapter") if not result["is_emergency"] else None,
        "category_tag": rc.get("meta", {}).get("category_tag") if not result["is_emergency"] else None,
        "safety_flags": result.get("safety_flags", []),
        "dosha": result.get("dosha") if not result["is_emergency"] else None,
    }
    if not result["is_emergency"]:
        response["reasoning_trace"] = {
            "steps": result.get("trace", []),
            "canonical_term": result.get("canonical_term"),
            "retrieved_verses": [
                {
                    "verse_id": c["verse_id"],
                    "chapter": f"{c['meta']['sthana']}/{c['meta']['chapter']}",
                    "score": round(float(c["score"]), 4),
                }
                for c in result.get("retrieved", [])
            ],
            "confidence_score": result.get("confidence_score"),
            "herbs_found": result.get("herbs_found", []),
            "dosha_scores": result.get("dosha_scores"),
            "safety_sources": result.get("safety_sources"),
            "verification_notes": result.get("verification_notes", []),
            "source_disagreements": result.get("source_disagreements", []),
        }
    return response


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