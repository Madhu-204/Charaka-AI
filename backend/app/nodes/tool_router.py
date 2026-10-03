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
            "parameters": {
                "type": "object",
                "properties": {
                    "ambiguity": {
                        "type": "string",
                        "description": (
                            "Optional. Set this ONLY when the question is so vague "
                            "that no verse could meaningfully answer it — for example "
                            "'what should I do' with no symptom, complaint or topic "
                            "named. Describe in a few words what information is "
                            "missing. Leave it out whenever the question names "
                            "anything concrete, however briefly."
                        ),
                    }
                },
            },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "direct_answer",
            "description": (
                "The question needs no passage from the corpus at all: a greeting, "
                "thanks, a question about what this assistant is or what it can do, "
                "or who you are. NEVER use this for any health, symptom, treatment, "
                "herb, diet or lifestyle question — those must be grounded in a "
                "verse, however simple they look."
            ),
            "parameters": {"type": "object", "properties": {}},
        }
    },
]

SYSTEM_PROMPT = """You are the retrieval router for Charaka AI.
Decide which retrieval tool to use for the user's question.
- If the user names a specific herb and asks about it (safety, dose, properties) → herb_lookup.
- Only use scope_retrieval if the user explicitly names a specific book of the Charaka Samhita (Sutra, Vimana, Sharira, or Chikitsasthana), or explicitly asks for a specific topic, chapter or subject area. Do not use it just because a symptom appears in the question.
- If the question is a greeting, thanks, or asks what this assistant is or can do → direct_answer. Nothing in the corpus can answer it.
- Otherwise → plain_retrieval (the default). On plain_retrieval, also set `ambiguity` if the question names no symptom, complaint, herb or topic at all, so the user can be asked for detail instead of receiving an unfocused answer."""


# Greetings, thanks and capability questions. This is a deliberately narrow
# whitelist, and it is the ONLY thing that can authorise the direct_answer branch.
#
# The LLM proposing direct_answer is not sufficient on its own: routing a health
# question past retrieval would also route it past grounding, safety notes and
# citation checks, and the user would get a confident answer with no verse behind
# it. So the model's choice is treated as a proposal and confirmed here against a
# fixed pattern. Anything not matched falls through to plain_retrieval, which is
# the safe direction to fail in.
#
# Note what is absent: a bare "help". "Help" is usually the opening of a health
# question ("help with my rash"), and the pattern is anchored at the start of the
# string, so allowing it would swallow exactly the queries this branch must not
# touch. The unambiguous phrasings below cover the real capability questions.
_META_QUERY = re.compile(
    r"^\s*(hi|hey|hello|yo|namaste|namaskar|good\s+(morning|afternoon|evening)|"
    r"thanks|thank\s+you|thx|ok|okay|cool|nice|great|bye|goodbye|"
    r"who\s+are\s+you|what\s+are\s+you|what\s+can\s+you\s+do|how\s+can\s+you\s+help|"
    r"what\s+do\s+you\s+do)\b",
    re.IGNORECASE,
)


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

    Nested `$and`s are flattened here rather than left to the caller. Merging a
    book scope into an existing topic scope at line ~277 already handles it, but
    that made correctness depend on every call site remembering; a missed site
    produces a nested operator Chroma rejects only at query time. Flattening
    here keeps the returned value valid for any input.
    """
    flattened: list[dict] = []
    for clause in clauses:
        if not clause:
            continue
        if set(clause) == {"$and"}:
            flattened.extend(c for c in clause["$and"] if c)
        else:
            flattened.append(clause)
    if not flattened:
        return {}
    if len(flattened) == 1:
        return flattened[0]
    return {"$and": flattened}


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


def _has_anchor(query: str, topic: str | None) -> bool:
    """True when the query names something concrete enough to retrieve against.

    Guards the ambiguity branch. A vague-sounding question that still names a
    symptom or an herb ("what about my knee pain?", "is triphala safe?") is
    perfectly answerable, so treating it as ambiguous would replace a real answer
    with a follow-up question. Requiring an anchor keeps clarification for the
    genuinely empty queries, which is where it helps.
    """
    if topic or STHANA_MENTIONS.search(query):
        return True
    from app.nodes.retriever import _detect_herb

    return bool(_detect_herb(query))


def route_tools(state):
    new_state = {
        "tool_decision": "plain_retrieval",
        "metadata_filter": None,
    }
    query = state.get("query", "")

    # Cheap, deterministic, and checked before the LLM so a greeting never costs a
    # tool-selection call at all. The regex is narrow enough that this can run first
    # without risk: nothing here can reach a health question.
    if _META_QUERY.match(query or ""):
        new_state["tool_decision"] = "direct_answer"
        new_state["direct_answer"] = True
        new_state["trace"] = list(state.get("trace", [])) + [
            "tool router: conversational message matched the meta-query pattern → "
            "answered without retrieval"
        ]
        return new_state

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
            # top-level operator in `where`, so an existing $and is flattened
            # by _and_clauses rather than updated as a flat dict.
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
        elif name == "direct_answer":
            # Confirmed against the whitelist, not taken on the model's word. See
            # _META_QUERY for why this branch is gated.
            if _META_QUERY.match(state["query"]):
                new_state["tool_decision"] = "direct_answer"
                new_state["direct_answer"] = True
                step = "tool router: LLM proposed direct_answer — confirmed by pattern"
            else:
                # Undo the optimistic assignment above: the model asked to skip
                # retrieval and we are refusing, so the state must not still be
                # labelled direct_answer. route_after_tools keys off the
                # `direct_answer` flag rather than this field, but tool_decision is
                # persisted and shown in the trace, so leaving it would misreport
                # what happened.
                new_state["tool_decision"] = "plain_retrieval"
                step = (
                    "tool router: LLM proposed direct_answer but the question names "
                    "something concrete → retrieving instead"
                )
        elif name == "plain_retrieval":
            ambiguity = (args.get("ambiguity") or "").strip()
            # Only honour the flag when there is genuinely nothing to retrieve
            # against. Asking a user to clarify a question we could have answered
            # is worse than giving a loosely-matched answer.
            if ambiguity and not _has_anchor(query, topic):
                new_state["needs_clarification"] = True
                new_state["clarification_hint"] = ambiguity
                step = f"tool router: question underspecified ({ambiguity}) → asking first"
    except Exception as e:  # noqa: BLE001
        step = f"tool router: LLM call failed ({type(e).__name__}) → defaulting to plain_retrieval"

    new_state["trace"] = trace + [step]
    return new_state