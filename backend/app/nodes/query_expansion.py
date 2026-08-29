import json
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]

with open(BACKEND / "reference" / "mappings.json", encoding="utf-8") as f:
    mappings = json.load(f)

with open(BACKEND / "reference" / "herbs.json", encoding="utf-8") as f:
    herbs_data = json.load(f)["herbs"]

SYNONYMS = {
    "diabetes": "prameha",
    "taste": "rasa",
    "constitution": "prakriti",
    "body type": "prakriti",
    "cough": "kasa",
    "digestion": "agni",
    "gut": "grahani",
}

HERB_PATTERNS = []
for herb in herbs_data:
    escaped = [re.escape(a) for a in herb["aliases"]]
    pattern = r"\b(?:" + "|".join(escaped) + r")\b"
    HERB_PATTERNS.append((herb["name"], re.compile(pattern, re.IGNORECASE)))


def expand_query(state):
    q = state["query"].lower()
    canonical = None

    for herb_name, pattern in HERB_PATTERNS:
        if pattern.search(q):
            canonical = herb_name
            break

    if not canonical:
        for term, sanskrit in SYNONYMS.items():
            if term in q:
                canonical = sanskrit
                break

    expanded = f"{state['query']} {canonical}" if canonical else state["query"]
    return {"expanded_query": expanded, "canonical_term": canonical}
