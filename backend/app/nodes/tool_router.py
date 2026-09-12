import os

from dotenv import load_dotenv
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_groq import ChatGroq

load_dotenv()

llm = ChatGroq(model="openai/gpt-oss-120b", api_key=os.environ["GROQ_API_KEY"])

STHANA_ENUM = ["sutrasthana", "vimanasthana", "sharirasthana", "chikitsasthana"]

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
                "Restrict retrieval to a single book (Sthana) of the Charaka Samhita. "
                "Use only when the user explicitly asks about a specific book, e.g. "
                "'in Chikitsasthana' or 'what does the Sutra Sthana say'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sthana": {"type": "string", "enum": STHANA_ENUM}
                },
                "required": ["sthana"],
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
- Only use scope_retrieval if the user explicitly names a specific book of the Charaka Samhita (Sutra, Vimana, Sharira, or Chikitsasthana).
- Otherwise → plain_retrieval (the default)."""


def route_tools(state):
    new_state = {
        "tool_decision": "plain_retrieval",
        "metadata_filter": None,
    }

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
            new_state["trace"] = state.get("trace", []) + [step]
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
        elif name == "scope_retrieval" and args.get("sthana") in STHANA_ENUM:
            new_state["metadata_filter"] = {"sthana": args["sthana"]}
            step = f"tool router: scope_retrieval → metadata filter on '{args['sthana']}'"
    except Exception as e:  # noqa: BLE001
        step = f"tool router: LLM call failed ({type(e).__name__}) → defaulting to plain_retrieval"

    new_state["trace"] = state.get("trace", []) + [step]
    return new_state