import json
import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_groq import ChatGroq

load_dotenv()

BACKEND = Path(__file__).resolve().parents[2]

with open(BACKEND / "reference" / "herbs.json", encoding="utf-8") as f:
    _herbs_list = json.load(f)["herbs"]

HERB_ALIASES = {h["name"]: h["aliases"] for h in _herbs_list}

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
- CITE SOURCES INLINE: the PRIMARY CONTEXT is source [1]. The ADDITIONAL CONTEXT blocks are [2], [3], ... in the order they appear. Place the matching marker (e.g. [1], [2]) immediately after each claim that comes from that verse — every factual statement that is grounded in a verse must carry the marker of the verse it came from. Use a marker only when the claim is actually in that verse.
- If confidence is marked "low", say explicitly that the match is uncertain. If it is marked "medium", note that the match is related but not exact, and frame the answer accordingly.
- Always end with a line encouraging the user to consult a doctor if symptoms persist or worsen.
- If a CONVERSATION CONTEXT is provided, use it to resolve references like "that", "it", "the same herb", or "instead" in the current question. Keep the answer self-contained (the user may have forgotten the earlier turn), but never invent details that aren't also in the current context.
- If any safety flags are provided, state them clearly before any remedy suggestion.
- When an herb is mentioned in the context, also note its alternate names (aliases) provided in the HERB ALIASES section. Classical texts may use different names for the same herb — recognize and explain these equivalences to the user.
- If a SPECIES/IDENTITY DISCLOSURE is provided for an herb, state it explicitly and prominently BEFORE giving any remedy or safety detail for that herb — never bury it. If a disclosure says an herb's profile is based on a different (closest-match) species, or that one species must not be confused with another, repeat that clearly so the user cannot mistake one plant for another.
- If SOURCE DISAGREEMENTS are provided, state each one verbatim and frame it as a practitioner-review caution (classical texts describe use, but modern sources flag a strong caution)."""

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


def _format_history(history):
    if not history:
        return None
    lines = []
    for m in history[-6:]:
        role = m.get("role", "user")
        content = (m.get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content[:1200]}")
    if not lines:
        return None
    return "\n".join(lines)


def _herb_alias_block(herbs_found):
    lines = []
    for h in herbs_found:
        aliases = HERB_ALIASES.get(h, [])
        if aliases:
            lines.append(f"- {h} (also called: {', '.join(aliases)})")
        else:
            lines.append(f"- {h}")
    return "\n".join(lines)


def synthesize(state):
    primary = state["resolved_chapter"]
    resolved_id = primary["verse_id"]
    additional = [c for c in state.get("retrieved", []) if c["verse_id"] != resolved_id]

    herbs_found = state.get("herbs_found", [])
    alias_block = _herb_alias_block(herbs_found) if herbs_found else "none"

    verification_notes = state.get("verification_notes", [])
    source_disagreements = state.get("source_disagreements", [])

    context = (
        f"PRIMARY CONTEXT:\n{_format_block(primary)}\n\n"
        f"ADDITIONAL CONTEXT:\n"
        + "\n---\n".join(_format_block(c) for c in additional)
        + "\n\n"
        f"Confidence: {state['confidence']}\n"
        f"Herbs found: {', '.join(herbs_found) or 'none'}\n"
        f"HERB ALIASES (these are alternate names for the same herb):\n{alias_block}\n"
        f"Safety flags: {', '.join(state['safety_flags']) or 'none'}\n"
    )

    if verification_notes:
        context += (
            "\nSPECIES/IDENTITY DISCLOSURES & VERIFICATION NOTES "
            "(state these explicitly when they concern identity or a closest-match species):\n"
            + "\n".join(f"- {n}" for n in verification_notes)
        )
    if source_disagreements:
        context += (
            "\nSOURCE DISAGREEMENTS (practitioner-review cautions — state verbatim):\n"
            + "\n".join(f"- {d}" for d in source_disagreements)
        )

    conversation_block = _format_history(state.get("history"))
    if conversation_block:
        context += f"\nCONVERSATION CONTEXT (prior turns):\n{conversation_block}\n"

    dosha_profile = state.get("dosha_profile")
    if dosha_profile:
        context += (
            "\nUSER'S INFERRED DOSHA PROFILE: "
            f"this user has previously been assessed as a predominantly {dosha_profile} pattern. "
            "Shape recommendations to be compatible with that balance, and say so explicitly.\n"
        )

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=f"Context:\n{context}\n\nUser question: {state['query']}"),
    ]
    try:
        chunks = []
        for chunk in llm.stream(messages):
            chunks.append(chunk.content)
        return {"final_answer": "".join(chunks)}
    except Exception as e:
        print(f"[synthesis] Groq call failed: {e}")
        return {"final_answer": FALLBACK_ANSWER}
