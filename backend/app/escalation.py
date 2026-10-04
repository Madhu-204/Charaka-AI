"""Localized escalation: turning a detected red flag into an actionable hand-off.

The emergency gate detects acuity. It used to answer with one fixed English
sentence - "seek immediate medical attention or contact emergency services" -
which is the least useful sentence that can be said to someone in a crisis. It
names no number, so a user has to already know the number, and it treats
self-harm the same as a heart attack, when the two need different destinations:
an ambulance for one, a person who will pick up for one.

This module separates the two:

  * CATEGORY - what kind of emergency. Only ``self_harm`` routes to a crisis
    line; everything else routes to the emergency number.
  * REGION   - where the user is, which decides the numbers. Read from an
    explicit country mention in the query, else ``CHARAKA_REGION``, else the
    ``default_region`` in reference/emergency_contacts.json.
  * LANGUAGE - Devanagari in the query means the reply is in Hindi. A user who
    typed "mujhe aatmahatya ka vichar ho raha hai" in Latin script still gets
    English, but "आत्महत्या" gets Hindi, and it is the same code path.

Numbers live in ``reference/emergency_contacts.json`` so they can be corrected
without a code change. Entries carry a ``verified`` flag; unverified entries log
a warning at import, because shipping an unverified crisis number is worse than
shipping none - see ``_warn_unverified``.
"""

import json
import os
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CONTACTS_FILE = BACKEND / "reference" / "emergency_contacts.json"

with open(CONTACTS_FILE, encoding="utf-8") as _f:
    CONTACTS = json.load(_f)

REGIONS = CONTACTS.get("regions", {})
DEFAULT_REGION = os.getenv("CHARAKA_REGION") or CONTACTS.get("default_region", "IN")
DIRECTORY_URL = CONTACTS.get("directory_url")

# Region codes that fall back to the international directory rather than guessing.
FALLBACK_REGION = "GLOBAL"


# --- categorization ----------------------------------------------------------
#
# Matched against the normalized red flag that actually fired, so a category is
# always explainable ("heart attack" -> cardiac_respiratory) and the trace can
# name it. Order matters only in that the first match wins, and the lists are
# disjoint enough that it does not.

_CATEGORY_PATTERNS = [
    (
        "self_harm",
        [
            "suicidal", "want to die", "kill myself", "end my life",
            "आत्महत्या", "मरना चाहता",
            # Must mirror the transliterations added to emergency.RED_FLAGS, or a
            # Hinglish self-harm report escalates to an ambulance number instead of
            # a crisis line - the same highest-severity path, wrong destination.
            "aatmahatya", "atmahatya", "jeevan ant",
            "marna chahta", "marna chahti",
        ],
    ),
    (
        "overdose_poisoning",
        [
            "overdose", "anaphylaxis", "anaphylactic", "severe allergic reaction",
            "choking",
        ],
    ),
    (
        "cardiac_respiratory",
        [
            "chest pain", "chest pn", "chestpain", "can t breathe",
            "cannot breathe", "cant breathe", "cantbreath", "breathing problem",
            "cardiac arrest", "heart attack", "angina", "palpitations with chest",
            "shortness of breath", "difficulty breathing", "breathlessness",
            "wheezing", "palpitations", "chest discomfort",
            "heart attack", "dimaag ka attack",
            "दिल का दरद", "दिल का दर्द", "सीने में दर्द", "सांस नहीं लग रही",
            "सांस नहीं चल रही", "सांस फूल रही", "दम घुट रहा", "हृदयाघात",
            "दिल का दरद", "सांस", "मिर्या",
        ],
    ),
    (
        "neuro",
        [
            "stroke", "seizure", "fits", "convulsion", "face droop",
            "facial droop", "slurred speech", "slurring", "can t speak",
            "cannot speak", "can t talk", "loss of vision", "can t see",
            "numbness on one side", "weakness on one side",
            "one side of my body", "one side of my face",
            "fits chal rahi", "बोल नहीं पा रहा", "चेहरा टेढ़ा",
        ],
    ),
    (
        "trauma_bleeding",
        [
            "severe bleeding", "bleeding heavily", "unconscious",
            "loss of consciousness", "can t move", "cannot move",
            "can t feel my arm", "can t feel my leg", "passing out",
            "passed out", "fainted", "blackout",
            "behosh", "behoshi", "khoon beh raha", "खून बहना", "बेहोश", "बेहोशी",
        ],
    ),
    (
        "acute_abdomen",
        [
            "severe abdominal pain", "vomiting blood", "coughing blood",
        ],
    ),
    (
        "critical_fever",
        [
            "high fever with confusion", "sudden severe headache",
            "worst headache of my life",
        ],
    ),
]

from app.nodes.emergency import _norm  # noqa: E402  (no cycle: emergency does not import this)

_NORMALIZED_CATEGORIES = [
    (cat, [_norm(p) for p in pats if _norm(p)]) for cat, pats in _CATEGORY_PATTERNS
]

OTHER = "other"


def categorize(flag):
    """Classify the red flag that fired. Returns a category key, else ``other``."""
    if not flag:
        return OTHER
    norm = _norm(flag)
    if not norm:
        return OTHER
    for category, patterns in _NORMALIZED_CATEGORIES:
        if any(p in norm for p in patterns):
            return category
    return OTHER


# --- region ------------------------------------------------------------------

_COUNTRY_ALIASES = {
    "IN": ["india", "bharat", "hindi", "hindi speaking", "delhi", "mumbai",
           "bangalore", "bengaluru", "chennai", "kolkata", "hyderabad", "pune",
           "ahmedabad", "jaipur", "lucknow", "patna", "noida"],
    "US": ["united states", "usa", "u s a", "america", "new york", "california",
           "texas", "florida", "chicago"],
    "GB": ["united kingdom", "uk", "britain", "england", "scotland", "wales",
           "london", "manchester"],
    "AU": ["australia", "sydney", "melbourne", "perth"],
    "CA": ["canada", "toronto", "vancouver", "montreal"],
}


def detect_region(query, default=None):
    """Pick a region for escalation.

    An explicit country or city mention in the query wins, because that is the
    user telling us where they are. Otherwise the configured default. Unknown
    regions resolve to the international directory rather than to a country's
    number, which would be worse than useless.
    """
    norm = _norm(query or "")
    if norm:
        for code, aliases in _COUNTRY_ALIASES.items():
            if code in REGIONS and any(_norm(a) in norm for a in aliases):
                return code
    chosen = default or DEFAULT_REGION
    return chosen if chosen in REGIONS else FALLBACK_REGION


# --- language ----------------------------------------------------------------

_DEVA_RE = re.compile(r"[\u0900-\u097F]")


def detect_language(query) -> str:
    """``hi`` when the query contains Devanagari, else ``en``."""
    return "hi" if _DEVA_RE.search(query or "") else "en"


# --- message assembly --------------------------------------------------------


def _contacts(region):
    return REGIONS.get(region) or REGIONS.get(FALLBACK_REGION, {})


def _crisis_lines(region):
    entries = _contacts(region).get("crisis") or []
    return [f"- {e['name']}: {e['number']} ({e.get('hours', '')})".replace(" ()", "")
            for e in entries if e.get("number")]


def _self_harm_message(region, lang):
    contacts = _contacts(region)
    number = contacts.get("emergency")
    lines = _crisis_lines(region)

    if number:
        en_emergency = (
            f"If you are in immediate danger, call {number} or go to the "
            "nearest emergency department."
        )
        hi_emergency = (
            f"यदि आप तुरंत ख़तरे में हैं, तो {number} पर कॉल करें या निकटतम "
            "आपातकालीन विभाग जाएँ।"
        )
    else:
        en_emergency = (
            "If you are in immediate danger, contact your local emergency "
            "number or go to the nearest emergency department."
        )
        hi_emergency = (
            "यदि आप तुरंत ख़तरे में हैं, तो अपने स्थानीय आपातकालीन नंबर पर संपर्क "
            "करें या निकटतम आपातकालीन विभाग जाएँ।"
        )

    directory = (
        f"- दुनिया भर में हेल्पलाइन: {DIRECTORY_URL}"
        if lang == "hi"
        else f"- Helplines anywhere in the world: {DIRECTORY_URL}"
    )

    if lang == "hi":
        parts = [
            "आपने जो कहा उससे लगता है आप ख़ुद को नुकसान पहुँचाने के बारे में सोच रहे हैं। "
            "मैं इसमें मदद नहीं कर सकता, और मैं चाहता हूँ कि आप इसे अकेले न संभालें।",
            "",
            hi_emergency,
            "",
            "आप अभी किसी से बात कर सकते हैं — मुफ़्त और गोपनीय:",
        ]
        parts += lines or ([directory] if DIRECTORY_URL else [])
        parts.append("")
        parts.append("कृपया आज ही किसी से बात करें। आपको यह अकेले नहीं संभालना है।")
        return "\n".join(parts)

    emergency_line = en_emergency
    parts = [
        "What you've described sounds like you may be thinking about harming "
        "yourself. I can't help with that, and I don't want to leave you "
        "carrying it alone.",
        "",
        emergency_line,
        "",
        "You can also speak to someone now, free and confidential:",
    ]
    parts += lines or ([directory] if DIRECTORY_URL else [])
    parts.append("")
    parts.append("Please talk to someone today. You do not have to handle this "
                 "by yourself.")
    return "\n".join(parts)


def _emergency_message(region, lang):
    contacts = _contacts(region)
    label = contacts.get("label", "your area")
    number = contacts.get("emergency")
    note = contacts.get("emergency_note") or ""

    if lang == "hi":
        where = f"{label} में {number} पर कॉल करें" if number else \
            "अपने स्थानीय आपातकालीन नंबर पर संपर्क करें"
        elsewhere = (
            "यदि आप किसी अन्य देश में हैं, तो वहाँ के आपातकालीन नंबर पर तुरंत कॉल करें।"
        )
        tail = "यह किसी wellness सहायक के रूप में मेरी सहायता की बात नहीं है।"
        # `note` is English prose from the contacts file, so it is dropped rather
        # than pasted into a Hindi reply. The number itself is language-neutral
        # and is the part that matters.
        return (
            "यह एक चिकित्सा आपातस्थिति जैसा लग रहा है। कृपया तुरंत चिकित्सा "
            f"सहायता लें।\n\n{where}।\n{elsewhere}\n\n{tail}"
        )

    where = f"In {label}, call {number}" if number else \
        "Contact your local emergency number"
    elsewhere = "If you are somewhere else, contact that country's emergency number now."
    tail = ("This isn't something I can help with as a wellness assistant.")
    return (
        "This sounds like it could be a medical emergency. Please seek immediate "
        f"medical attention.\n\n{where}.{(' ' + note) if note else ''}\n{elsewhere}"
        f"\n\n{tail}"
    )


def build_message(flag, query=None, region=None, lang=None) -> str:
    """Build the escalation reply for a fired red flag.

    ``flag`` is the red flag that matched (state["emergency_reason"]); ``query``
    is the user's text, used only to pick region and language.
    """
    category = categorize(flag)
    resolved_region = detect_region(query, default=region)
    resolved_lang = lang or detect_language(query)

    if category == "self_harm":
        return _self_harm_message(resolved_region, resolved_lang)
    return _emergency_message(resolved_region, resolved_lang)


def describe(flag, query=None, region=None):
    """Return ``(category, region, language)`` for the trace, without building text."""
    return (
        categorize(flag),
        detect_region(query, default=region),
        detect_language(query),
    )


def _warn_unverified():
    """Warn once at import about any region whose numbers are unchecked.

    A wrong crisis number is worse than none, so this is deliberately loud rather
    than a debug log. Silencing it means editing the JSON, which is the point.
    """
    unchecked = [
        code
        for code, cfg in REGIONS.items()
        if not cfg.get("verified") and (cfg.get("emergency") or cfg.get("crisis"))
    ]
    if unchecked:
        print(
            "[escalation] WARNING: unverified emergency numbers in "
            f"{CONTACTS_FILE.name} for {', '.join(sorted(unchecked))}. "
            "Confirm each number with the issuing authority and set "
            '"verified": true before relying on them in production.'
        )


_warn_unverified()