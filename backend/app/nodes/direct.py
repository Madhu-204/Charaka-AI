"""Answers for turns that need no verse.

Reached only from the router's `direct_answer` decision, which the router itself
gates behind a fixed pattern of greetings, thanks and capability questions (see
tool_router._META_QUERY). Nothing here touches the corpus.

Deliberately templated rather than generated. A greeting does not need the 3.5K-token
synthesis call, and answering "hello" by retrieving the Charaka Samhita produces a
confident, verse-cited response to a question nobody asked. It also means this branch
cannot hallucinate, which matters more than variety for the handful of inputs it sees.
"""

import re

GREETING = (
    "Namaste. I'm an assistant for the Charaka Samhita — I search 2,490 verses and "
    "answer from them, with the chapter cited.\n\n"
    "Ask me about a symptom, a treatment, an herb or its safety, a diet or daily "
    "routine, or what a particular book of the text says."
)

THANKS = (
    "You're welcome. Ask me anything else about the classical texts, or about a "
    "symptom, herb or routine you'd like grounded in them."
)

CAPABILITY = (
    "I search the Charaka Samhita and answer from it, citing the chapter for each "
    "claim.\n\n"
    "I can help with symptoms and classical treatment, herbs and their safety, diet "
    "and daily routine, and what a specific book (Sutra, Vimana, Sharira, Chikitsa "
    "Sthana) says about a topic.\n\n"
    "I don't diagnose, and I don't replace a doctor — for anything ongoing or "
    "worsening, please see one."
)

IDENTITY = (
    "I'm a research assistant for the Charaka Samhita, the classical Ayurvedic text. "
    "I answer from its verses and cite the chapter for each claim. I'm not a clinician "
    "and can't diagnose — for ongoing or worsening symptoms, please see a doctor."
)

FAREWELL = "Goodbye. Come back any time you have a question about the texts."

DEFAULT = GREETING

_THANKS = re.compile(r"\b(thanks|thank you|thx)\b", re.IGNORECASE)
_CAPABILITY = re.compile(
    r"\b(what can you do|how can you help|what do you do)\b", re.IGNORECASE
)
_IDENTITY = re.compile(r"\b(who are you|what are you)\b", re.IGNORECASE)
_FAREWELL = re.compile(r"\b(bye|goodbye|see you)\b", re.IGNORECASE)


def _reply_for(query: str) -> str:
    q = query or ""
    if _IDENTITY.search(q):
        return IDENTITY
    if _CAPABILITY.search(q):
        return CAPABILITY
    if _FAREWELL.search(q):
        return FAREWELL
    if _THANKS.search(q):
        return THANKS
    return DEFAULT


def direct_answer(state):
    query = state.get("query", "")
    answer = _reply_for(query)
    trace = state.get("trace", [])
    return {
        "final_answer": answer,
        # Terminal here, so these must say so explicitly. build_response reads
        # is_emergency to null out chapter/category/dosha; without is_direct the
        # client would be handed a null-chapter response shaped like a normal
        # grounded answer.
        "is_direct_answer": True,
        "tool_decision": "direct_answer",
        "grounding_score": None,
        "grounding_notes": [],
        "trace": trace
        + [
            "direct answer: conversational message — no retrieval, no citation "
            "check (nothing was retrieved to check)"
        ],
    }