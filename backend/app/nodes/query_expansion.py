import json
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]

with open(BACKEND / "reference" / "mappings.json", encoding="utf-8") as f:
    mappings = json.load(f)

with open(BACKEND / "reference" / "herbs.json", encoding="utf-8") as f:
    herbs_data = json.load(f)["herbs"]

# English -> Sanskrit bridge terms. The value is appended to the query so the
# embedding model sees the term Charaka actually uses.
#
# These were selected by measurement, not by guessing. A candidate only earns a
# place if both terms occur in the corpus vocabulary and appending it improved
# retrieval on deliberately hard paraphrases ("my chest is tight and i can't
# catch my breath"). Several plausible mappings were rejected on that basis:
# "astringent"->"kashaya" flipped a correct answer (sutrasthana/26 ->
# chikitsasthana/3), and "diabetes", "gut" and "body type" never appear in the
# corpus text at all, so they could not help.
#
# Keys are matched with `in`, not word boundaries, so longer phrases are listed
# before their substrings where both are wanted.
SYNONYMS = {
    "high temperature": "jwara",
    "fever": "jwara",
    "chest is tight": "shwasa",
    "breathing": "shwasa",
    "hiccups": "hikka",
    "hiccup": "hikka",
    "skin disease": "kushtha",
    "joint pain": "vatavyadhi",
    "thirsty": "prameha",
    "old age": "ayu",
    "indigestion": "grahani",
    "tastes": "rasa",
    "taste": "rasa",
    "constitution": "prakriti",
    "body type": "prakriti",
    "cough": "kasa",
    "digestion": "agni",
    "diabetes": "prameha",
}

HERB_PATTERNS = []
for herb in herbs_data:
    escaped = [re.escape(a) for a in herb["aliases"]]
    pattern = r"\b(?:" + "|".join(escaped) + r")\b"
    HERB_PATTERNS.append((herb["name"], re.compile(pattern, re.IGNORECASE)))


# --- Hindi input normalization ------------------------------------------------
#
# `all-MiniLM-L6-v2` is an English-only encoder, and the BM25 tokenizer is
# `[a-z]+`, so Devanagari input is invisible to both halves of hybrid search.
# Measured before this was added, "ज्वर का उपचार" (treatment of fever) returned
# vimanasthana/8 at cosine 0.380 — barely above the 0.194 noise floor of
# ("jwara", "horse"), i.e. it retrieved noise, and scored 0.00 on BM25.
#
# A full transliteration is not enough on its own: ITRANS would render ज्वर as
# "jvar", which shares little with either "fever" or "jwara" in embedding space.
# A curated glossary does better because it emits the term the corpus actually
# uses -- the romanised Sanskrit Charaka's translator writes ("jwara", "kasa"),
# which is already in the index. That keeps this free: no model, no API, no
# new dependency.
#
# Entries are ordered longest-first at match time so a longer phrase wins over a
# prefix of itself.
HINDI_TERMS = {
    # ailments
    "ज्वर": "jwara",
    "बुखार": "jwara",
    "कास": "kasa",
    "खांसी": "kasa",
    "खाँसी": "kasa",
    "श्वास": "shwasa",
    "सांस": "shwasa",
    "हिक्का": "hikka",
    "हिचकिनी": "hikka",
    "कुष्ठ": "kushtha",
    "त्वचा रोग": "kushtha",
    "प्रमेह": "prameha",
    "मधुमेह": "prameha",
    "अतिसार": "atisara",
    "दस्त": "atisara",
    "कब्ज": "vibandha",
    "अजीर्ण": "ajirna",
    "पाचन": "agni",
    "हृदय": "hridaya",
    "शिरोरोग": "shiroroga",
    "सिरदर्द": "shiroroga",
    "कब्ज़": "vibandha",
    # doshas
    "वात": "vata",
    "पित्त": "pitta",
    "कफ": "kapha",
    # herbs
    "अश्वगंधा": "ashwagandha",
    "शतावरी": "shatavari",
    "गुडूची": "guduchi",
    "अमला": "amalaki",
    "हरितकी": "haritaki",
    "बिभितकी": "bibhitaki",
    "त्रिफला": "triphala",
    "जीरक": "cumin",
    "सौंठ": "ginger",
    "काली मिर्च": "black pepper",
    "पिप्पली": "long pepper",
    "इलायची": "cardamom",
    "दालचीनी": "cinnamon",
    "सौंफ": "fennel",
    "हींग": "asafoetida",
    "चंदन": "sandalwood",
    "यष्टिमधु": "liquorice",
    "कूज": "musta",
    "कुटज": "kutaja",
    # general
    "आयुर्वेद": "ayurveda",
    "चिकित्सा": "chikitsa",
    "उपचार": "chikitsa",
    "व्याधि": "vyadhi",
    "रोग": "roga",
    "दोष": "dosa",
    "आहार": "ahara",
    "निद्रा": "nidra",
}

# Devanagari range, used to decide whether a query needs normalizing at all.
DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")

# Longest first so "त्वचा रोग" is matched before a hypothetical "त्वचा".
_HINDI_PATTERNS = [
    (term, re.compile(re.escape(term))) for term in sorted(HINDI_TERMS, key=len, reverse=True)
]


def has_devanagari(text: str) -> bool:
    return bool(DEVANAGARI_RE.search(text or ""))


def normalize_hindi(query: str) -> str:
    """Rewrite Devanagari terms in ``query`` to their romanised equivalents.

    Only matched glossary terms are replaced; everything else is left exactly as
    typed. English queries are returned untouched, so this is safe to call
    unconditionally.
    """
    if not has_devanagari(query):
        return query
    out = query
    for term, pattern in _HINDI_PATTERNS:
        out = pattern.sub(HINDI_TERMS[term], out)
    return out

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
    # Devanagari equivalents. Without these a Hindi follow-up is never detected,
    # so the prior turn is dropped and the query is answered in isolation.
    "इसके बारे में",
    "इसका उपयोग",
    "इसी तरह",
    "क्या यह",
    "और क्या",
    "इसके अलावा",
    "इसकी तरह",
    "इसका",
]


def _last_user_message(history):
    """Most recent user turn, Devanagari normalized.

    Normalizing here matters for follow-ups: the rewritten query is built from
    the prior turn, so without this a Hindi prior stays Devanagari and the
    retriever sees two unknown queries instead of one normalized one.
    """
    for m in reversed(history or []):
        if m.get("role") == "user":
            return normalize_hindi(m.get("content", "") or "")
    return None


def _collect_history_herbs(history):
    herbs = []
    for m in reversed(history or []):
        text = normalize_hindi((m.get("content") or "").lower())
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
    raw = state["query"]
    # Normalize before anything else so the canonical-term detector, the herb
    # detector and retrieval all see the same romanised text. Without this,
    # Devanagari reaches the English-only encoder and the [a-z]+ BM25 tokenizer
    # and contributes nothing to either.
    normalized = normalize_hindi(raw)
    q = normalized.lower()
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
        rewritten = f"{prior}. Follow-up: {normalized}"
        expanded = f"{rewritten} {canonical}" if canonical else rewritten
        kind = "multi-turn follow-up rewritten over previous query"
    elif canonical:
        expanded = f"{combined} {canonical}"
        kind = f"detected canonical term '{canonical}' → expanded query"
    else:
        expanded = normalized
        kind = "no herb/condition term detected"

    trace = state.get("trace", [])
    step = f"query expansion: {kind}" + (
        f" (carried herb '{canonical}' from history)" if followup and not _detect_herb(q) and canonical else ""
    )
    if normalized != raw:
        step += " (Devanagari terms normalized to romanised Sanskrit)"
    return {
        "expanded_query": expanded,
        "canonical_term": canonical,
        "followup_context": prior if followup else None,
        "trace": trace + [step],
    }