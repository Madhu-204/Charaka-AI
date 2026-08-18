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
    return {
        "answer": result["final_answer"],
        "is_emergency": result["is_emergency"],
        "confidence": result.get("confidence"),
        "chapter": (
            result.get("resolved_chapter", {}).get("meta", {}).get("chapter")
            if not result["is_emergency"]
            else None
        ),
        "safety_flags": result.get("safety_flags", []),
    }