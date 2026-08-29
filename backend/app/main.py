from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

from app.graph import charaka_agent

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


@app.post("/ask")
def ask(req: AskRequest):
    result = charaka_agent.invoke({"query": req.query})
    rc = result.get("resolved_chapter") or {}
    response = {
        "answer": result["final_answer"],
        "is_emergency": result["is_emergency"],
        "confidence": result.get("confidence"),
        "chapter": rc.get("meta", {}).get("chapter") if not result["is_emergency"] else None,
        "safety_flags": result.get("safety_flags", []),
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
            "safety_sources": result.get("safety_sources"),
            "verification_notes": result.get("verification_notes", []),
            "source_disagreements": result.get("source_disagreements", []),
        }
    return response