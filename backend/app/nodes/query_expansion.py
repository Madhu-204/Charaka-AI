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

FOLLOWUP_HINTS = [
    "what about",
    "how about",
    "instead",
    "related",
    "that herb",
    "this herb",
    "same way",
    "can i also",
    "do you mean",
    "which herb",
    "similar herb",
]


def _last_user_message(history):
    for m in reversed(history or []):
        if m.get("role") == "user":
            return m.get("content", "")
    return None


def _collect_history_herbs(history):
    herbs = []
    for m in reversed(history or []):
        text = (m.get("content") or "").lower()
        for herb_name, pattern in HERB_PATTERNS:
            if pattern.search(text) and herb_name not in herbs:
                herbs.append(herb_name)
    return herbs


def _is_followup(query):
    q = query.lower()
    return any(h in q for h in FOLLOWUP_HINTS)


def _detect_herb(text):
    for herb_name, pattern in HERB_PATTERNS:
        if pattern.search(text):
            return herb_name
    return None


def _canonical_from(text):
    h = _detect_herb(text)
    if h:
        return h
    low = text.lower()
    for term, sanskrit in SYNONYMS.items():
        if term in low:
            return sanskrit
    return None


def expand_query(state):
    q = state["query"].lower()
    history = state.get("history") or []
    canonical = None
    prior = _last_user_message(history)
    followup = _is_followup(q) and bool(prior)

    combined = f"{prior.lower()} {q}" if followup else q

    canonical = _canonical_from(combined)

    if not canonical and followup and not _detect_herb(q):
        prior_herbs = _collect_history_herbs(history)
        if prior_herbs:
            canonical = prior_herbs[0]

    if followup:
        rewritten = f"{prior}. Follow-up: {state['query']}"
        expanded = f"{rewritten} {canonical}" if canonical else rewritten
        kind = "multi-turn follow-up rewritten over previous query"
    elif canonical:
        expanded = f"{combined} {canonical}"
        kind = f"detected canonical term '{canonical}' → expanded query"
    else:
        expanded = state["query"]
        kind = "no herb/condition term detected"

    trace = state.get("trace", [])
    step = f"query expansion: {kind}" + (
        f" (carried herb '{canonical}' from history)" if followup and not _detect_herb(q) and canonical else ""
    )
    return {
        "expanded_query": expanded,
        "canonical_term": canonical,
        "followup_context": prior if followup else None,
        "trace": trace + [step],
    }