VATA_KEYWORDS = [
    "bloat",
    "gas",
    "constipat",
    "dry",
    "cold",
    "anxiet",
    "insomnia",
    "can't sleep",
    "cannot sleep",
    "joint",
    "stiff",
    "cracking",
    "tremor",
    "restless",
    "irregular appetite",
    "irregular bowel",
    "wind",
    "pain",
    "spasm",
    "nervous",
    "irritability of the nervous",
]

PITTA_KEYWORDS = [
    "acidity",
    "heartburn",
    "burning",
    "burn",
    "inflam",
    "rash",
    "anger",
    "angry",
    "irritable",
    "heat",
    "loose stools",
    "diarrh",
    "sweat",
    "redness",
    "hot",
    "boil",
    "acne",
    "peptic",
    "gastritis",
    "ulcer",
    "sour",
]

KAPHA_KEYWORDS = [
    "sluggish",
    "sluggishness",
    "heavy",
    "heaviness",
    "congestion",
    "mucus",
    "phlegm",
    "cough",
    "weight",
    "fatigue",
    "dull",
    "sinus",
    "stuffy",
    "runny nose",
    "sleepy",
    "oversle",
    "itch",
    "nausea",
    "fluid retention",
    "water retention",
    "lethargy",
]

CANONICAL_ORDER = ["Vata", "Pitta", "Kapha"]


def _score(query, keywords):
    score = 0
    matched = set()
    for kw in keywords:
        if kw in query:
            score += 1
            matched.add(kw)
    return score, matched


def infer_dosha(query: str) -> dict:
    q = query.lower()
    vata, vata_kw = _score(q, VATA_KEYWORDS)
    pitta, pitta_kw = _score(q, PITTA_KEYWORDS)
    kapha, kapha_kw = _score(q, KAPHA_KEYWORDS)

    scores = {"Vata": vata, "Pitta": pitta, "Kapha": kapha}
    top = max(scores.values())

    if top == 0:
        return {
            "dosha": None,
            "dosha_scores": scores,
            "dosha_keywords": [],
        }

    leaders = [d for d, s in scores.items() if s == top]
    if len(leaders) > 1:
        label = "-".join(d for d in CANONICAL_ORDER if d in leaders)
    else:
        label = leaders[0]

    matched = set()
    matched.update(vata_kw)
    matched.update(pitta_kw)
    matched.update(kapha_kw)

    return {
        "dosha": label,
        "dosha_scores": scores,
        "dosha_keywords": sorted(matched),
    }


def tag_dosha(state):
    result = infer_dosha(state["query"])
    trace = state.get("trace", [])
    if result["dosha"]:
        step = (
            f"dosha tagger: matched {result['dosha']} pattern "
            f"(Vata={result['dosha_scores']['Vata']}, "
            f"Pitta={result['dosha_scores']['Pitta']}, "
            f"Kapha={result['dosha_scores']['Kapha']})"
        )
    else:
        step = "dosha tagger: no clear dosha pattern detected"
    return {
        "dosha": result["dosha"],
        "dosha_scores": result["dosha_scores"],
        "trace": trace + [step],
    }