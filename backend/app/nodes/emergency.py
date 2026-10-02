"""Emergency / red-flag gate.

Two failure modes were found by probing real phrasings:

 1. Matching was English-only literal substrings. Every Hindi ("dil dard",
    "saans nahi", "behosh", "atmahitya"), Hinglish and common clinical synonym
    ("cardiac arrest", "heart attack", "overdose", "anaphylaxis", "choking")
    sailed straight through to verse retrieval. A Hindi-speaking user describing
    chest pain was being sent Ayurvedic verse content instead of emergency
    services.
 2. Punctuation defeated it: "chest-pain" did not match "chest pain".

Both are fixed by normalizing query and flags through the same function, so
matching stays a cheap substring test (no model, no regex-heavy hot path) while
being tolerant of spacing, hyphens and apostrophe variants.

The informational exemption is retained deliberately: "what are the symptoms of
chest pain" is a legitimate study question and must NOT redirect. First-person
reporting ("I have chest pain") does redirect.
"""

import re

RED_FLAGS = [
    # --- cardiac / respiratory ---
    "chest pain",
    "can't breathe",
    "cannot breathe",
    "cant breathe",
    # NOTE: bare "shortness of breath" / "difficulty breathing" are ALSO
    # legitimate topic terms - topics.json maps them to the respiratory category
    # (Hikka-Shwasa, a real Charaka chapter). Used as a red flag they refuse a
    # whole category. They are handled as SYMPTOMS instead: gated only when the
    # user reports them in first person. See SYMPTOM_ONLY_FLAGS.
    "can't breathe properly",
    "choking",
    "cardiac arrest",
    "heart attack",
    "angina",
    "palpitations with chest",
    # --- neurological ---
    "stroke",
    "seizure",
    "fits",
    "convulsion",
    "face droop",
    "facial droop",
    "slurred speech",
    "slurring",
    "can't speak",
    "cannot speak",
    "can't talk",
    "loss of vision",
    "can't see",
    "numbness on one side",
    "weakness on one side",
    "one side of my body",
    "one side of my face",
    "passing out",
    "passed out",
    "fainted",
    "blackout",
    # --- trauma / bleeding ---
    "severe bleeding",
    "bleeding heavily",
    "unconscious",
    "loss of consciousness",
    "can't move",
    "cannot move",
    "can't feel my arm",
    "can't feel my leg",
    # --- suicidal ---
    "suicidal",
    "want to die",
    "kill myself",
    "end my life",
    # --- acute abdomen / critical ---
    "sudden severe headache",
    "worst headache of my life",
    "severe abdominal pain",
    "coughing blood",
    "vomiting blood",
    "high fever with confusion",
    "overdose",
    "anaphylaxis",
    "anaphylactic",
    "severe allergic reaction",
    # Common clipped/typo forms. Hand-listed rather than fuzzed: a general
    # edit-distance pass over medical text risks false positives, and in this
    # module a false negative is the dangerous direction.
    "chest pn",
    "chestpain",
    "cantbreath",
    "breathing problem",
    # --- Hindi ---
    "दिल का दर्द",
    "दर्द हो रहा है",
    "सीने में दर्द",
    "सांस नहीं लग रही",
    "सांस नहीं चल रही",
    "सांस फूल रही",
    "दम घुट रहा",
    "बेहोश",
    "बेहोशी",
    "हृदयाघात",
    "दिल का दरद",  # common misspelling
    "आत्महत्या",
    "मरना चाहता",
    "खून बहना",
    "कमजोरी एक तरफ",
    "चेहरा टेढ़ा",
    "बोल नहीं पा रहा",
    # --- Hinglish ---
    "dil dard",
    "dil ka dard",
    "saans nahi",
    "saans nahi chal rahi",
    "behosh",
    "mriya",
    "khoon beh raha",
    "fits chal rahi",
    "dimaag ka attack",
    "heart attack",
]

# Symptoms that are simultaneously red flags and legitimate classical topics.
# A bare "shortness of breath" as a search term is the respiratory chapter
# (Hikka-Shwasa); "I have shortness of breath" is a person in distress. Gate
# these only when the query reports them rather than asking about them.
SYMPTOM_ONLY_FLAGS = [
    "shortness of breath",
    "difficulty breathing",
    "breathlessness",
    "wheezing",
    "palpitations",
    "chest discomfort",
]

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
    "symptoms of",
    "signs of",
    "in charaka",
    # Hindi interrogative - study questions must stay informational
    "क्या",
    "कैसे",
    "क्यों",
    "कौन",
    "कब",
    "कितना",
    "लक्षण",
    "चिकित्सा",
    "आयुर्वेद",
    "कृपया बताइए",
]

FIRST_PERSON_MARKERS = [
    "i have",
    "i've",
    "i am",
    "i'm",
    "i can",
    "i feel",
    "i felt",
    "im ",
    "my ",
    "me ",
    "can't",
    "cannot",
    "cant ",
    "won't",
    "getting",
    "since last night",
    # Hindi first-person - a user describing their OWN symptoms must redirect
    "मुझे",
    "मेरा",
    "मेरे",
    "मैं",
    "मुझे तकलीफ",
    "मेरी तकलीफ",
    "लग रही",
    "लग रहा",
    "हो रहा है",
    "हो रही है",
    # Hinglish first-person
    "mujhe",
    "mera",
    "meri",
    "mujh",
]

EMERGENCY_MESSAGE = (
    "This sounds like it could be a medical emergency. "
    "Please seek immediate medical attention or contact emergency "
    "services right now - this isn't something I can help with as "
    "a wellness assistant."
)

# --- normalization ---------------------------------------------------------
# One function applied to BOTH the query and every red flag, so the two sides
# always agree. Kept deliberately simple and fast: lowercase, fold smart
# apostrophes, drop apostrophes, turn punctuation into spaces, collapse space.
_PUNCT_RE = re.compile(r"[^a-z0-9\u0900-\u097F]+")


def _norm(text):
    """Lowercase and strip punctuation/apostrophe variants for matching."""
    if not text:
        return ""
    t = str(text).lower()
    t = t.replace("\u2019", "'").replace("\u02bc", "'").replace("\u2018", "'")
    t = t.replace("'", "").replace("\u0142", "l")
    t = _PUNCT_RE.sub(" ", t)
    return " ".join(t.split())


# Normalize once at import rather than per-request. Empty results are dropped so
# a flag that normalizes to nothing can never match everything.
NORMALIZED_FLAGS = [(f, _norm(f)) for f in RED_FLAGS]
NORMALIZED_FLAGS = [(orig, n) for orig, n in NORMALIZED_FLAGS if n]
NORMALIZED_INTERROGATIVE = [_norm(m) for m in INTERROGATIVE_MARKERS if _norm(m)]
NORMALIZED_FIRST_PERSON = [_norm(m) for m in FIRST_PERSON_MARKERS if _norm(m)]


def _matches(flag, q):
    """Substring match constrained to word boundaries.

    A plain ``in`` test was too loose: "seizure" fired on "remedies for seizure"
    (a study question) and the Hindi "mriya" fired inside the word "guduchi".
    Boundaries keep this a cheap test while stopping word-internal hits.
    """
    if not flag:
        return False
    pattern = r"(?<!\w)" + re.escape(flag).replace(r"\ ", r"\s+") + r"(?!\w)"
    return re.search(pattern, q) is not None


def _is_informational(q):
    """Study questions are informational; first-person reports are not.

    Matches on normalized text so Hindi and punctuation variants behave the same
    way as English ones.
    """
    informational = any(_matches(m, q) for m in NORMALIZED_INTERROGATIVE)
    first_person = any(_matches(m, q) for m in NORMALIZED_FIRST_PERSON)
    return informational and not first_person


def _reports_symptom(q):
    """True when the query reads as a person reporting a symptom, not studying it.

    Used for SYMPTOM_ONLY_FLAGS, which are dual-purpose: real Charaka topics and
    real clinical symptoms. "herbs for shortness of breath" is a topic query;
    "I have shortness of breath" is a person needing care.

    Deliberately narrow: this returns True only on an explicit reporting signal
    (first person, or an imperative request for help). Anything else - a bare
    keyword, a study question, a topic lookup - returns False and continues to
    normal retrieval. Erring toward "not an emergency" here is correct: the
    unambiguous red flags live in RED_FLAGS, and a bare symptom noun is far more
    often a search term than a live emergency.
    """
    return any(_matches(m, q) for m in NORMALIZED_FIRST_PERSON)


def check_emergency(state):
    """Return the emergency redirect when the query reports a red flag.

    ``state`` needs only "query"; "trace" is appended when present. Returns the
    same keys as before (is_emergency, emergency_reason, final_answer, trace) so
    no caller changes.
    """
    raw = state["query"]
    q = _norm(raw)
    informational = _is_informational(q)
    trace = state.get("trace", [])

    # Dual-purpose symptoms: gate only on a symptom report, never on a topic
    # query. Checked after RED_FLAGS so an unambiguous red flag still wins.
    for original in SYMPTOM_ONLY_FLAGS:
        n = _norm(original)
        if n and _matches(n, q) and _reports_symptom(q):
            return {
                "is_emergency": True,
                "emergency_reason": original,
                "final_answer": EMERGENCY_MESSAGE,
                "trace": trace
                + [
                    f"emergency gate: reported symptom '{original}' - redirected to doctor"
                ],
            }

    for original, norm in NORMALIZED_FLAGS:
        if _matches(norm, q):
            if informational:
                # Genuine study question ("what are the symptoms of stroke").
                # Do not redirect, but do not silently drop the signal either.
                return {
                    "is_emergency": False,
                    "emergency_reason": None,
                    "final_answer": None,
                    "trace": trace
                    + [
                        f"emergency gate: RED_FLAG '{original}' present but query reads "
                        "as an informational/study question - not redirected"
                    ],
                }
            return {
                "is_emergency": True,
                "emergency_reason": original,
                "final_answer": EMERGENCY_MESSAGE,
                "trace": trace
                + [f"emergency gate: RED_FLAG '{original}' hit - redirected to doctor"],
            }

    return {
        "is_emergency": False,
        "emergency_reason": None,
        "final_answer": None,
        "trace": trace + ["emergency gate: no red flag detected (informational or wellness query)"],
    }