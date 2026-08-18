import json
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]

with open(BACKEND / "reference" / "mappings.json", encoding="utf-8") as f:
    mappings = json.load(f)

SYNONYMS = {
    "diabetes": "prameha",
    "taste": "rasa",
    "constitution": "prakriti",
    "body type": "prakriti",
    "cough": "kasa",
    "digestion": "agni",
    "gut": "grahani",
}


def expand_query(state):
    q = state["query"].lower()
    canonical = None
    for term, sanskrit in SYNONYMS.items():
        if term in q:
            canonical = sanskrit
            break
    expanded = f"{state['query']} {canonical}" if canonical else state["query"]
    return {"expanded_query": expanded, "canonical_term": canonical}