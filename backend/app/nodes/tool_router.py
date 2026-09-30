import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_groq import ChatGroq

load_dotenv()

llm = ChatGroq(
    model="openai/gpt-oss-120b",
    api_key=os.environ["GROQ_API_KEY"],
    max_retries=2,
    timeout=60,
)

STHANA_ENUM = ["sutrasthana", "vimanasthana", "sharirasthana", "chikitsasthana"]

BACKEND = Path(__file__).resolve().parents[2]
with open(BACKEND / "reference" / "topics.json", encoding="utf-8") as f:
    TOPICS = json.load(f)["topics"]

TOPIC_ENUM = sorted(TOPICS)

# Longest terms first so "fever treatment" wins over "fever", and "skin disease"
# over any shorter prefix. Built once at import; the loop is the hot path.
_TOPIC_PATTERNS: list[tuple[str, re.Pattern]] = []
for _tag, _spec in TOPICS.items():
    for _term in _spec["terms"]:
        _TOPIC_PATTERNS.append((_tag, re.compile(r"\b" + re.escape(_term) + r"\b", re.IGNORECASE)))
_TOPIC_PATTERNS.sort(key=lambda p: -len(p[1].pattern))


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "herb_lookup",
            "description": (
                "Retrieve verses by herb or plant mention. Use when the question "
                "names a particular herb (e.g. ashwagandha, triphala, guggulu) and "
                "mentions its safety, dose or properties."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "herb": {
                        "type": "string",
                        "description": "Canonical herb name from the user's question.",
                    }
                },
                "required": ["herb"],
            },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "scope_retrieval",
            "description": (
                "Restrict retrieval to a single book (Sthana) of the Charaka Samhita, "
                "and optionally to one clinical topic. Use only when the user "
                "explicitly asks about a specific book (e.g. 'in Chikitsasthana' or "
                "'what does the Sutra Sthana say'), or explicitly asks for a topic "
                "or chapter. Do not use it for a general question that merely "
                "mentions a symptom as part of a broader wellness enquiry."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sthana": {
                        "type": "string",
                        "enum": STHANA_ENUM,
                        "description": "Optional. The book the user named.",
                    },
                    "topic": {
                        "type": "string",
                        "enum": TOPIC_ENUM,
                        "description": (
                            "Optional. Only set this when the user explicitly asks "
                            "for a specific topic, chapter or subject area."
                        ),
                    },
                },
            },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "plain_retrieval",
            "description": (
                "Default option for general wellness questions that span the corpus. "
                "No scoping or herb index is needed."
            ),
            "parameters": {"type": "object", "properties": {}},
        }
    },
]

SYSTEM_PROMPT = """You are the retrieval router for Charaka AI.
Decide which retrieval tool to use for the user's question.
- If the user names a specific herb and asks about it (safety, dose, properties) → herb_lookup.
- Only use scope_retrieval if the user explicitly names a specific book of the Charaka Samhita (Sutra, Vimana, Sharira, or Chikitsasthana), or explicitly asks for a specific topic, chapter or subject area. Do not use it just because a symptom appears in the question.
- Otherwise → plain_retrieval (the default)."""


# Surface forms users actually type when they want one specific book.
# Checked before skipping the router, so an explicit book request always
# reaches the LLM and can set a metadata_filter.
STHANA_MENTIONS = re.compile(
    r"\b(sutra|sutrasthana|vimana|sharira|chikitsa|chikitsasthana)\b", re.IGNORECASE
)

# Two tiers of scoping evidence.
#
# STRONG cues name a container of text ("the chapter on fever", "verses on
# diabetes"), so they mean the user wants retrieval narrowed to that scope.
#
# WEAK cues are ordinary question verbs. They are not enough on their own: in
# "What does rasa (taste) tell us about digestion?" the verb "says" pairs with
# a topic word that is the *object* of the question, not its subject, and
# scoping on "digestion" would hide the taste verses the user actually wants.
STRONG_SCOPE = re.compile(
    r"\b(chapter|verses?|passage|section|sthana|specifically|only|"
    r"in the sutra|book)\b",
    re.IGNORECASE,
)
WEAK_SCOPE = re.compile(
    r"\b(about|on|regarding|tell me|explain|describe)\b",
    re.IGNORECASE,
)


def detect_topics(query: str) -> list[str]:
    """Every topic tag the query mentions, in specificity order."""
    q = query or ""
    seen: list[str] = []
    for tag, pattern in _TOPIC_PATTERNS:
        if pattern.search(q) and tag not in seen:
            seen.append(tag)
    return seen


def detect_topic(query: str) -> str | None:
    """Return the category_tag the query explicitly asks to be scoped to.

    Returns None when the user is asking a general question that merely mentions
    the term, or when two different topics are both mentioned and no strong
    scoping cue disambiguates them. Over-filtering is the worse failure here: it
    silently hides correct verses, whereas under-filtering merely fails to
    narrow the pool.
    """
    q = query or ""
    matches = detect_topics(q)
    if not matches:
        return None
    if STHANA_MENTIONS.search(q) or STRONG_SCOPE.search(q):
        return matches[0]
    # A weak cue plus an ambiguous question is not a scoping request.
    if len(matches) > 1 or not WEAK_SCOPE.search(q):
        return None
    return matches[0]


def _and_clauses(clauses: list[dict]) -> dict:
    """Collapse clauses into a single valid Chroma `where` value.

    Chroma requires exactly one top-level operator and rejects an $and holding
    fewer than two clauses, so a one-clause list must degrade to the bare dict.
    """
    cleaned = [c for c in clauses if c]
    if not cleaned:
        return {}
    if len(cleaned) == 1:
        return cleaned[0]
    return {"$and": cleaned}


def _topic_clauses(tag: str) -> list[dict]:
    """The metadata clauses that scope retrieval to one topic tag.

    Split out so the deterministic path and the LLM tool path build identical
    clauses and cannot drift apart.
    """
    condition = TOPICS[tag].get("condition")
    if condition:
        # Narrower than the tag (e.g. respiratory -> Kasa only), so constrain both.
        return [{"category_tag": tag}, {"traditional_condition": condition}]
    return [{"category_tag": tag}]


def _topic_filter(tag: str) -> dict:
    """Build the Chroma metadata filter for a topic tag.

    Chroma requires a `where` clause to hold exactly one operator, so multiple
    keys must be wrapped in $and. It also rejects an $and with fewer than two
    clauses, so the single-clause case must stay a bare dict.
    """
    clauses = _topic_clauses(tag)
    return _and_clauses(clauses)


def route_tools(state):
    new_state = {
        "tool_decision": "plain_retrieval",
        "metadata_filter": None,
    }
    query = state.get("query", "")

    # A topic scope is resolved deterministically. It costs no LLM call and is
    # always available, so it is applied before (and independently of) routing.
    # `trace` accumulates from here so the topic scope stays visible in the trace
    # even when a later branch rebuilds it.
    trace = list(state.get("trace", []))
    topic = detect_topic(query)
    if topic:
        new_state["metadata_filter"] = _topic_filter(topic)
        trace.append(f"tool router: topic scope -> metadata filter on '{topic}'")

    # Skip the LLM only when the cheap deterministic herb detector already
    # decided the routing AND the user did not name a specific book. The book
    # check matters: "ashwagandha in chikitsasthana" needs scope_retrieval to
    # set metadata_filter, so herb detection alone is not sufficient.
    if not STHANA_MENTIONS.search(query) and not topic:
        from app.nodes.retriever import _detect_herb

        if _detect_herb(query):
            new_state["tool_decision"] = "herb_lookup"
            new_state["trace"] = trace + [
                "tool router: skipped LLM — herb detected deterministically, "
                "no book or topic named"
            ]
            return new_state

    try:
        result = llm.invoke(
            [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=f"User question: {state['query']}"),
            ],
            tools=TOOLS,
            tool_choice="auto",
        )
        calls = getattr(result, "tool_calls", None) or []
        step = f"tool router: LLM selected {calls[0]['name'] if calls else 'no tool'}"
        if not calls:
            new_state["trace"] = trace + [step]
            return new_state

        call = calls[0]
        name = call.get("name", "")
        args = call.get("args", {}) or {}
        new_state["tool_decision"] = name

        if name == "herb_lookup" and args.get("herb"):
            herb = args["herb"].strip().lower()
            current_canonical = (state.get("canonical_term") or "").lower()
            if herb != current_canonical:
                new_state["canonical_term"] = herb
                new_state["expanded_query"] = (
                    f"{state.get('expanded_query', state['query'])} {herb}"
                ).strip()
                step = f"tool router: herb_lookup → '{herb}' (appended to query)"
            else:
                step = f"tool router: herb_lookup → already canonical '{herb}'"
        elif name == "scope_retrieval" and (
            args.get("sthana") in STHANA_ENUM or args.get("topic") in TOPIC_ENUM
        ):
            # Merge, don't replace: a book scope and a topic scope are both valid
            # together ("in Chikitsa Sthana, on fever"). Chroma allows only one
            # top-level operator in `where`, so an existing $and has to be
            # nested inside a new $and rather than updated as a flat dict.
            existing = new_state["metadata_filter"] or {}
            clauses = list(existing.get("$and", [existing])) if existing else []
            parts = []
            if args.get("sthana") in STHANA_ENUM:
                parts.append(f"sthana={args['sthana']}")
                clauses.append({"sthana": args["sthana"]})
            topic_arg = args.get("topic")
            if topic_arg in TOPIC_ENUM:
                # A deterministic topic scope already in force wins; the LLM must
                # not be able to widen or contradict it.
                if not topic:
                    clauses += _topic_clauses(topic_arg)
                parts.append(f"topic={topic_arg}")
            new_state["metadata_filter"] = _and_clauses(clauses) if clauses else None
            step = "tool router: scope_retrieval → metadata filter on " + ", ".join(parts)
    except Exception as e:  # noqa: BLE001
        step = f"tool router: LLM call failed ({type(e).__name__}) → defaulting to plain_retrieval"

    new_state["trace"] = trace + [step]
    return new_state