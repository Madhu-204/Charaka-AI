RED_FLAGS = [
    "chest pain",
    "difficulty breathing",
    "can't breathe",
    "severe bleeding",
    "unconscious",
    "loss of consciousness",
    "suicidal",
    "want to die",
    "sudden severe headache",
    "can't move",
    "stroke",
    "seizure",
    "severe abdominal pain",
    "coughing blood",
    "high fever with confusion",
]

EMERGENCY_MESSAGE = (
    "This sounds like it could be a medical emergency. "
    "Please seek immediate medical attention or contact emergency "
    "services right now — this isn't something I can help with as "
    "a wellness assistant."
)

INTERROGATIVE_MARKERS = [
    "what",
    "how",
    "which",
    "why",
    "when",
    "who",
    "describe",
    "according to",
    "charaka",
    "does",
    "is there",
    "remedies for",
    "treatment for",
    "tell me",
]

FIRST_PERSON_MARKERS = [
    "i have",
    "i've",
    "i am",
    "i'm",
    "i can",
    "im ",
    "my ",
    "me ",
    "can't",
    "cannot",
]


def _is_informational(q):
    return any(m in q for m in INTERROGATIVE_MARKERS) and not any(
        m in q for m in FIRST_PERSON_MARKERS
    )


def check_emergency(state):
    q = state["query"].lower()
    informational = _is_informational(q)
    trace = state.get("trace", [])
    for flag in RED_FLAGS:
        if flag in q:
            if informational:
                continue
            return {
                "is_emergency": True,
                "emergency_reason": flag,
                "final_answer": EMERGENCY_MESSAGE,
                "trace": trace + [f"emergency gate: RED_FLAG '{flag}' hit — redirected to doctor"],
            }
    return {
        "is_emergency": False,
        "trace": trace + ["emergency gate: no red flag detected (informational or wellness query)"],
    }