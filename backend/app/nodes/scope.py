"""Scope gate: refuse to answer what the corpus cannot support.

Three related defects were found by probing the running system:

 1. Off-topic queries still produced Charaka answers. "quantum computing
    scheduling algorithm" resolved to vimanasthana/8 at low confidence - the
    system confidently discussed something the corpus never mentions.
 2. Medication-substitution questions were ungated. "Can I stop taking my
    diabetes tablets?" retrieved chikitsasthana/6. A user acting on that could
    stop prescribed medication.
 3. Dosage questions were answerable from verse text. Charaka contains real
    quantities, so the model can quote a classical dose with convincing numbers
    (dangerous for toxic herbs such as arka/Calotropis).

These are the same defect - the system asserting things beyond its evidence - so
one gate handles all three rather than three patches.

Design notes:
 - This gate is about SCOPE, not acuity. It runs AFTER check_emergency, because
   a genuine emergency must win regardless of topic.
 - It never fabricates. Refusal text describes the system's boundaries and
   points to the corpus; it asserts no medical content of its own.
 - The "ask a doctor" instruction is standard safety boilerplate, not a claim.
 - Matching reuses emergency._norm/_matches so both gates agree on punctuation,
   apostrophes and word boundaries (this module imports rather than duplicates).
"""

import json
import re
from pathlib import Path

from app.nodes.emergency import _matches, _norm

# _detect_herb recognises any herb in herbs.json (discussed or not), so the
# coverage gate can tell "only about an absent herb" from "also about a
# discussed one". query_expansion does not import this module, so no cycle.
from app.nodes.query_expansion import _detect_herb

BACKEND = Path(__file__).resolve().parents[2]

# --- categories -------------------------------------------------------------

# 1. Treatment decisions the user must make with a clinician.
MEDICATION_PATTERNS = [
    r"\bstop(ping)?\b.{0,30}\b(tablets?|meds?|medication|medicine|drugs?|insulin)\b",
    r"\b(stop|quit)\b.{0,20}\b(treatment|therapy|antibiotics?)\b",
    r"\b(replace|substitute|swap)\b.{0,30}\b(medication|tablets?|meds?|insulin|drugs?|antibiotics?)\b",
    r"\binstead of\b.{0,25}\b(medication|tablets?|meds?|insulin|drugs?|antibiotics?|chemotherapy)\b",
    r"\b(my|his|her|their)\b.{0,20}\b(medication|tablets?|insulin|prescription)\b",
    r"\bshould i\b.{0,30}\b(stop|reduce|skip|lower|change)\b",
    r"\b(dose|dosage|dosing)\b.{0,25}\b(change|adjust|increase|decrease|lower|reduce)\b",
    r"\bcan i take\b.{0,40}\binstead\b",
    # Serious-condition overclaims. Charaka is a classical wellness text; it
    # cannot cure or diagnose these, and must never appear to.
    r"\bcure\b.{0,25}\b(cancer|hiv|aids|tb|tuberculosis|diabetes|epilepsy|covid|hepatitis|schizophrenia)\b",
    r"\b(cancer|hiv|aids|tb|tuberculosis|diabetes|epilepsy|schizophrenia)\b.{0,25}\b(cure|curable|heal|healed)\b",
    # NOT bare "diagnosis"/"diagnostic": topics.json maps those to the
    # diagnosis_method category ("Examination and diagnosis" is a real Charaka
    # topic), so matching them refused a whole legitimate category. Only the
    # user-as-patient phrasings are refused.
    r"\b(does|do|can|will)\b.{0,20}\bthis\s+diagnos(e|is)\b",
    r"\bdiagnos(e|is|ing)\s+(me|my)\b",
    r"\bdiagnostic\s+(test|results?)\b.{0,25}\b(for me|should i)\b",
    r"\bwhat (disease|condition|illness) do i have\b",
    r"\bhow do i find out (what|if)\b",
    r"\bdo i have\b.{0,30}\b(infection| disorder| disease| syndrome)\b",
    r"\breplace\b.{0,20}\b(surgery|chemotherapy|radiation|antibiotics?)\b",
]

# 2. Quantities. Charaka states real doses, so the model can quote a plausible
#    number. That number must come from a practitioner, never from this system.
DOSAGE_PATTERNS = [
    # "How much" alone is too broad: eval_12 ("What is the right quantity of food
    # to eat daily?") is a legitimate ahara/diet question in routine_dinacharya.
    # Restrict the vague phrasings to remedy/substance contexts.
    r"\bhow much\b.{0,40}\b(take|use|consume|drink|ingest|dose|apply|make)\b",
    r"\bhow (much|many)\b.{0,25}\b(grams?|mg|milligrams?|ml|millilitres?|milliliters?|doses?|tablets?|capsules?|powder|extract|juice|oil|decoction)\b",
    r"\bhow much\b.{0,30}\b(herbs?|medicine|medication|ashwagandha|guduchi|triphala|turmeric|shatavari)\b",
    # "quantity/amount" must name a remedy or measurement unit, else eval_12
    # ("the right quantity of food to eat daily" - ahara/diet) is refused.
    r"\b(what|which)\b.{0,20}\b(dosage|dose)\b",
    r"\b(what|which)\b.{0,15}\b(quantity|amount)\b.{0,30}\b(grams?|mg|ml|dose|doses|to take|of the|should i take|consume|drink|herb|medicine|powder|extract)\b",
    r"\bcorrect (dosage|dose|amount|quantity)\b",
    r"\b(dosage|dose|doses)\b.{0,20}\b(should|for me|per day|daily|safe|is it|right)\b",
    r"\b\d+\s*(mg|ml|grams?|g|milligrams?)\b",
    r"\bis \d+ .{0,15}(safe|ok|okay|too much|enough)\b",
    r"\bhow long\b.{0,25}\b(take|taking|use|using)\b",
    r"\bfor how long\b",
    r"\b(take|use|consume)\b.{0,20}\b(daily|every day|each morning|each night|twice a day)\b",
    r"\bsafe (dose|dosage|amount) of\b",
    r"\bhow many times\b",
    r"\bfrequency of\b.{0,20}\b(consumption|use|taking)\b",
]

# 3. Off-domain. Kept deliberately narrow: a wrong refusal on a legitimate
#    Charaka question is its own failure, so this only fires on clearly
#    non-Ayurvedic topics.
OFFDOMAIN_PATTERNS = [
    r"\b(quantum|blockchain|cryptocurrency|bitcoin|stock market|tax|taxes|"
    r"mortgage|sql|python|javascript|react|linux kernel|api|http|json)\b",
    r"\b(legal|law|court case|attorney lawyer|lawyer|sue|contract)\b",
    r"\b(stock|share|shares|portfolio|investing|loan|insurance)\b",
    r"\brecipe for\b",
    r"\bwho won\b|\b election\b|\bprime minister\b|\bpresident of\b",
    r"\bcapital of\b|\bcurrency of\b",
    r"\bhow to (code|program|compile|install|download|uninstall)\b",
    r"\b(cpu|gpu|router|firewall|kernel|compiler|database)\b",
    r"\b(car|phone|laptop|computer) (price|model|specs)\b",
]

COMPILED_MEDICATION = [re.compile(p, re.IGNORECASE) for p in MEDICATION_PATTERNS]
COMPILED_DOSAGE = [re.compile(p, re.IGNORECASE) for p in DOSAGE_PATTERNS]
COMPILED_OFFDOMAIN = [re.compile(p, re.IGNORECASE) for p in OFFDOMAIN_PATTERNS]

# --- refusal messages -------------------------------------------------------
# These state the system's limits. They make no health claims of their own.

MEDICATION_REFUSAL = (
    "This is a question for your doctor or pharmacist, not for me — and I don't "
    "want to guess, because getting it wrong could be genuinely dangerous.\n\n"
    "Charaka Samhita is a classical wellness text. I can describe what it says "
    "about herbs, foods, tastes and daily routine, but I can't advise you on "
    "starting, stopping or changing any prescribed medicine. Never change a "
    "prescribed treatment based on anything I say.\n\n"
    "Please speak with your prescribing clinician or pharmacist before making "
    "any change to your medication."
)

DOSAGE_REFUSAL = (
    "I can't give you a dose or quantity, and I'd rather tell you that plainly "
    "than guess — some herbs in these texts are potent, and a wrong amount can "
    "be harmful.\n\n"
    "Charaka Samhita does describe quantities and preparations, but working out "
    "a correct amount for *you* needs someone who can take your health, history "
    "and current medicines into account.\n\n"
    "Please ask a qualified Ayurvedic practitioner or your doctor for the "
    "appropriate dose, and let them know about every other medicine or herb you "
    "are taking."
)

OFFDOMAIN_REFUSAL = (
    "That's outside what I can help with. I'm a Charaka Samhita wellness "
    "assistant — I answer questions using verses from the classical Ayurvedic "
    "texts and nothing else.\n\n"
    "I'd rather say \"I don't know\" than invent an answer that sounds "
    "authoritative but isn't grounded in the text.\n\n"
    "If you'd like, I can help with Ayurvedic topics such as herbs and foods, "
    "the six tastes, dosha theory, daily routine (dinacharya) or seasonal "
    "regimen (ritucharya)."
)

CATEGORY_REFUSALS = {
    "medication": MEDICATION_REFUSAL,
    "dosage": DOSAGE_REFUSAL,
    "offdomain": OFFDOMAIN_REFUSAL,
}


def _first_match(patterns, q):
    for p in patterns:
        m = p.search(q)
        if m:
            return m.group(0)
    return None


def classify_scope(query):
    """Return (category, matched_text) or (None, None) when in-scope.

    Medication is checked before dosage: "should I stop my tablets" is the more
    dangerous reading and must not be answered as a dose question.
    """
    q = _norm(query)
    if not q:
        return None, None

    med = _first_match(COMPILED_MEDICATION, q)
    if med:
        return "medication", med

    dose = _first_match(COMPILED_DOSAGE, q)
    if dose:
        return "dosage", dose

    off = _first_match(COMPILED_OFFDOMAIN, q)
    if off:
        return "offdomain", off

    return None, None


def check_scope(state):
    """Refuse out-of-scope questions before retrieval and synthesis.

    Runs after check_emergency. Returns a terminal refusal (no verse retrieved,
    nothing synthesized) so the model never gets a chance to answer from an
    irrelevant passage.
    """
    query = state.get("query", "")
    trace = state.get("trace", [])

    category, matched = classify_scope(query)
    if not category:
        coverage = check_corpus_coverage({"query": query, "trace": []})
        if coverage.get("is_out_of_scope"):
            return {
                "is_out_of_scope": True,
                "scope_category": coverage["scope_category"],
                "final_answer": coverage["final_answer"],
                "trace": trace + coverage["trace"],
            }
        return {
            "is_out_of_scope": False,
            "scope_category": None,
            "trace": trace + ["scope gate: in scope (no refusal pattern matched)"],
        }

    return {
        "is_out_of_scope": True,
        "scope_category": category,
        "final_answer": CATEGORY_REFUSALS[category],
        "trace": trace
        + [f"scope gate: REFUSED '{category}' (matched '{matched}') - no retrieval, no synthesis"],
    }


# --- corpus coverage --------------------------------------------------------
#
# herbs.json is keyed by Sanskrit/modern names, but the corpus is an English
# translation that names plants in common English, so a user can ask about a
# herb this translation never discusses. build_herb_terminology.py classifies
# every herb by what actually occurs in the corpus; 22 occur under no name and
# no alias. Retrieval for those returns a weak, topically wrong verse at low
# confidence, which reads as grounded but is not.
#
# This is the same defect the categories above handle - asserting things beyond
# the evidence - so it belongs in this gate rather than in retrieval. The
# generated file is authoritative and nothing here is hand-listed, so a corpus
# rebuild that starts discussing a herb silently lifts the refusal.

_TERMINOLOGY_PATH = BACKEND / "reference" / "herb_terminology.json"

try:
    with open(_TERMINOLOGY_PATH, encoding="utf-8") as _f:
        _TERMINOLOGY = json.load(_f)
except (OSError, ValueError):  # noqa: BLE001
    # Missing or malformed generated data must not refuse valid questions: the
    # gate degrades to "no coverage information", never to "refuse everything".
    _TERMINOLOGY = None

ABSENT_HERBS = {
    name
    for name, entry in (_TERMINOLOGY or {}).get("herbs", {}).items()
    if entry.get("status") == "not_in_corpus"
}

HERB_NAMES = set((_TERMINOLOGY or {}).get("herbs", {}).keys())

COVERAGE_REFUSAL = (
    "This herb is not discussed in the Charaka Samhita text I have indexed, so I "
    "have no verse to ground an answer in. That is a limit of the translation I am "
    "working from, not a judgement about the plant. I would rather say that than "
    "assemble an answer from passages that do not mention it. If you can tell me "
    "an English name the text uses, I will look again."
)


def absent_herbs_in(text):
    """Absent herb names mentioned in ``text``, longest match first.

    Matching still goes through _matches for word boundaries, so a short name
    cannot fire inside a longer plant name. Longest-first matters when one
    absent name is a prefix of another; sorting keeps the most specific match.
    """
    found = [h for h in ABSENT_HERBS if _matches(h, text)]
    return sorted(found, key=len, reverse=True)


def check_corpus_coverage(state):
    """Refuse a question whose subject herb this corpus never discusses.

    Deliberately narrow. It refuses only when the herb is the *whole* subject of
    the query. "bibhitaki for cough" is refused because there is nothing to say;
    "bibhitaki and ginger for cough" is not, because ginger is discussed and the
    question is still partly answerable. Refusing there would trade one
    ungrounded answer for a refusal of a grounded one.

    Called from check_scope, which runs it only after the category patterns have
    declined to match, so a medication or dosage refusal keeps priority.
    """
    query = state.get("query", "")
    trace = state.get("trace", [])
    if not ABSENT_HERBS or not _norm(query):
        return {"is_out_of_scope": False, "scope_category": None, "trace": trace}

    q = _norm(query)

    # If the query also names a herb the corpus DOES discuss, it is not purely
    # about the absent one. _detect_herb matches all 93 herbs in herbs.json,
    # including absent ones, so it cannot answer this directly: it is used to
    # confirm the query is herb-led at all, then each detected herb is looked up
    # in the generated table.
    if _detect_herb(q):
        named = {n for n in HERB_NAMES if _matches(n, q)}
        if any(n not in ABSENT_HERBS for n in named):
            return {"is_out_of_scope": False, "scope_category": None, "trace": trace}

    absent = absent_herbs_in(q)
    if not absent:
        return {"is_out_of_scope": False, "scope_category": None, "trace": trace}

    herb = absent[0]
    return {
        "is_out_of_scope": True,
        "scope_category": "not_in_corpus",
        "final_answer": COVERAGE_REFUSAL,
        "trace": trace
        + [
            f"scope gate: REFUSED 'not_in_corpus' - '{herb}' occurs in no corpus "
            f"verse under any name or alias"
        ],
    }