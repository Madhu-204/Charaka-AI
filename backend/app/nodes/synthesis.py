import os

from dotenv import load_dotenv
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_groq import ChatGroq

load_dotenv()

STHANA_NAMES = {
    "sutrasthana": "Sutra Sthana",
    "vimanasthana": "Vimana Sthana",
    "sharirasthana": "Sharira Sthana",
    "chikitsasthana": "Chikitsa Sthana",
}

llm = ChatGroq(model="openai/gpt-oss-120b", api_key=os.environ["GROQ_API_KEY"])

SYSTEM_PROMPT = """You are Charaka AI, a general-wellness Ayurvedic assistant grounded in classical texts.

Rules you must always follow:
- Use ONLY the provided context. Never add information not present in it.
- Base your answer primarily on the PRIMARY CONTEXT (the disambiguated best match).
- You may use the ADDITIONAL CONTEXT only when it directly supports the question and clearly relates; always cite the specific chapter you draw from.
- Frame findings as "classical texts describe this pattern as..." — never claim a clinical medical diagnosis.
- Always cite the source chapter provided in the context.
- If confidence is marked "low", say explicitly that the match is uncertain.
- Always end with a line encouraging the user to consult a doctor if symptoms persist or worsen.
- If any safety flags are provided, state them clearly before any remedy suggestion."""

FALLBACK_ANSWER = (
    "I couldn't retrieve a grounded answer right now. Classical texts describe "
    "patterns here, but I can't confirm a match for your question at the moment. "
    "If your symptoms persist or worsen, please consult a doctor."
)


def _format_block(rc):
    meta = rc["meta"]
    sthana = STHANA_NAMES.get(meta["sthana"], meta["sthana"])
    return (
        f"Chapter: {sthana} Ch.{meta['chapter']} "
        f"({meta['traditional_condition'] or meta['category_tag']})\n"
        f"Verse: {rc['verse_id']}\n"
        f"Text: {rc['text']}"
    )


def synthesize(state):
    primary = state["resolved_chapter"]
    resolved_id = primary["verse_id"]
    additional = [c for c in state.get("retrieved", []) if c["verse_id"] != resolved_id]

    context = (
        f"PRIMARY CONTEXT:\n{_format_block(primary)}\n\n"
        f"ADDITIONAL CONTEXT:\n"
        + "\n---\n".join(_format_block(c) for c in additional)
        + "\n\n"
        f"Confidence: {state['confidence']}\n"
        f"Herbs found: {', '.join(state['herbs_found']) or 'none'}\n"
        f"Safety flags: {', '.join(state['safety_flags']) or 'none'}\n"
    )

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=f"Context:\n{context}\n\nUser question: {state['query']}"),
    ]
    try:
        response = llm.invoke(messages)
        return {"final_answer": response.content}
    except Exception as e:
        print(f"[synthesis] Groq call failed: {e}")
        return {"final_answer": FALLBACK_ANSWER}