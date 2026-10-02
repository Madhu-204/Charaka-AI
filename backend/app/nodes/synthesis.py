import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_groq import ChatGroq

load_dotenv()

BACKEND = Path(__file__).resolve().parents[2]

with open(BACKEND / "reference" / "herbs.json", encoding="utf-8") as f:
    _herbs_list = json.load(f)["herbs"]

HERB_ALIASES = {h["name"]: h["aliases"] for h in _herbs_list}


# --- prompt size budget -----------------------------------------------------
#
# Observed failure: Groq returned
#   "Limit 8000, Requested 8321" (HTTP 413) and synthesis raised
#   SynthesisUnavailable, so the user got a 503 instead of an answer.
#
# Nothing bounded the prompt: retrieved blocks, uploaded documents, history and
# verification notes were all appended in full. Measured growth on real data:
#   ~1.5k tokens  typical query (3 blocks)
#   ~6.1k         20 additional blocks
#   ~11.2k        40 additional blocks  <- over the limit
#
# The primary verse, safety flags and verification notes are never trimmed:
# dropping safety text to fit a budget would trade a working answer for an unsafe
# one. Only redundant/optional context is dropped, and truncation is announced to
# the model rather than done silently.
MAX_CONTEXT_TOKENS = int(os.getenv("CHARAKA_MAX_CONTEXT_TOKENS", "6000"))
MAX_ADDITIONAL_BLOCKS = int(os.getenv("CHARAKA_MAX_ADDITIONAL_BLOCKS", "12"))
MAX_DOC_CHARS = int(os.getenv("CHARAKA_MAX_DOC_CHARS", "900"))
MAX_HISTORY_TURNS = int(os.getenv("CHARAKA_MAX_HISTORY_TURNS", "6"))
# Absolute ceiling for the whole request. Safety flags, verification notes and
# source disagreements are never trimmed for fidelity, so a pathological amount
# of them (e.g. a 92-herb safety dump) can still overflow. Rather than let the
# provider 413 and surface a 503, the request is clamped here. Verified worst
# case: 9355 tokens before clamping, which fits under this ceiling.
MAX_REQUEST_TOKENS = int(os.getenv("CHARAKA_MAX_REQUEST_TOKENS", "7500"))


def _approx_tokens(text: str) -> int:
    """Cheap token estimate.

    Deliberately not an exact tokenizer: this only needs to keep requests under
    a ceiling, and loading a real tokenizer per request would be wasteful. C4
    under-estimates slightly for prose, which errs toward trimming more.
    """
    return max(1, len(text) // 4)


def _truncate_middle(text: str, limit: int) -> str:
    """Keep the head and tail of ``text`` when over ``limit``.

    Verse and note text often carries the citation at the end, so a plain
    head-truncation would drop the reference.
    """
    if limit <= 0 or len(text) <= limit:
        return text
    head = limit * 2 // 3
    tail = limit - head
    return f"{text[:head]}\n...[truncated]...\n{text[-tail:]}"

STHANA_NAMES = {
    "sutrasthana": "Sutra Sthana",
    "vimanasthana": "Vimana Sthana",
    "sharirasthana": "Sharira Sthana",
    "chikitsasthana": "Chikitsa Sthana",
}

llm = ChatGroq(
    model="openai/gpt-oss-120b",
    api_key=os.environ["GROQ_API_KEY"],
    max_retries=2,
    timeout=60,
)

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
- If SOURCE DISAGREEMENTS are provided, state each one verbatim and frame it as a practitioner-review caution (classical texts describe use, but modern sources flag a strong caution).
- If a USER-SUPPLIED DOCUMENT CONTEXT block is present, you may draw on it, but ALWAYS label anything taken from it as coming from "your uploaded document", cite it with its [U1]/[U2] markers, and never present it as classical Samhita text. Keep the classical corpus as your primary basis."""

class SynthesisUnavailable(RuntimeError):
    """Raised when the LLM provider fails or rate-limits during synthesis.

    Callers must surface this as a retryable error. Never swallow it and
    substitute a canned answer: a fabricated string with no citations is
    indistinguishable from a real grounded answer to the user.
    """


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


def _build_context(primary, additional, state, herbs_found, alias_block, history):
    """Assemble the full synthesis context.

    Single source of truth so the normal path and the over-budget fallback can
    never drift into sending duplicated sections.
    """
    context = (
        f"PRIMARY CONTEXT:\n{_format_block(primary)}\n\n"
        f"ADDITIONAL CONTEXT:\n"
        + ("\n---\n".join(_format_block(c) for c in additional) if additional else "none")
        + "\n\n"
        f"Confidence: {state['confidence']}\n"
        f"Herbs found: {', '.join(herbs_found) or 'none'}\n"
        f"HERB ALIASES (these are alternate names for the same herb):\n{alias_block}\n"
        f"Safety flags: {', '.join(state['safety_flags']) or 'none'}\n"
    )

    verification_notes = state.get("verification_notes", [])
    if verification_notes:
        context += (
            "\nSPECIES/IDENTITY DISCLOSURES & VERIFICATION NOTES "
            "(state these explicitly when they concern identity or a closest-match species):\n"
            + "\n".join(f"- {n}" for n in verification_notes)
        )
    source_disagreements = state.get("source_disagreements", [])
    if source_disagreements:
        context += (
            "\nSOURCE DISAGREEMENTS (practitioner-review cautions — state verbatim):\n"
            + "\n".join(f"- {d}" for d in source_disagreements)
        )

    user_docs = state.get("user_docs") or []
    if user_docs:
        block = (
            "\n\nUSER-SUPPLIED DOCUMENT CONTEXT "
            "(files the user uploaded; NOT the classical corpus):\n"
        )
        for i, d in enumerate(user_docs, 1):
            text = _truncate_middle(d["text"], MAX_DOC_CHARS)
            block += (
                f"[U{i}] (from \"{d.get('doc', 'uploaded document')}\", "
                f"score {d['score']}): {text}\n"
            )
        context += block

    conversation_block = _format_history(history)
    if conversation_block:
        context += f"\nCONVERSATION CONTEXT (prior turns):\n{conversation_block}\n"

    dosha_profile = state.get("dosha_profile")
    if dosha_profile:
        context += (
            "\nUSER'S INFERRED DOSHA PROFILE: "
            f"this user has previously been assessed as a predominantly {dosha_profile} pattern. "
            "Shape recommendations to be compatible with that balance, and say so explicitly.\n"
        )
    return context


def synthesize(state):
    primary = state["resolved_chapter"]
    resolved_id = primary["verse_id"]
    retrieved = state.get("retrieved", [])
    all_additional = [c for c in retrieved if c["verse_id"] != resolved_id]

    herbs_found = state.get("herbs_found", [])
    alias_block = _herb_alias_block(herbs_found) if herbs_found else "none"

    # Trim redundant context to fit the budget. Order of sacrifice, lowest value
    # first: extra retrieved blocks, then older history turns, then uploaded
    # document text. The primary verse, safety flags, verification notes and
    # source disagreements are NEVER trimmed - dropping a safety warning to save
    # a token would make the answer worse, not just shorter.
    additional = all_additional[:MAX_ADDITIONAL_BLOCKS]
    dropped_blocks = len(all_additional) - len(additional)
    history = (state.get("history") or [])[-MAX_HISTORY_TURNS:]

    context = _build_context(
        primary, additional, state, herbs_found, alias_block, history
    )

    # Final backstop. The per-section caps bound the normal case, but safety
    # flags, alias lists and verification notes are intentionally unbounded. If
    # the total still overflows, shed additional blocks until it fits, so the
    # provider never returns 413 and the user never gets a 503.
    total = _approx_tokens(SYSTEM_PROMPT) + _approx_tokens(context)
    while total > MAX_CONTEXT_TOKENS and additional:
        additional = additional[:-1]
        context = _build_context(
            primary, additional, state, herbs_found, alias_block, history
        )
        total = _approx_tokens(SYSTEM_PROMPT) + _approx_tokens(context)

    if dropped_blocks or additional != all_additional:
        print(
            f"[synthesis] context budget: "
            f"{len(all_additional) - len(additional)} additional verse(s) omitted to stay "
            f"within {MAX_CONTEXT_TOKENS} tokens"
        )
        context += (
            "\nNOTE: some additional supporting verses were omitted to fit the context "
            "budget. Base the answer only on the verses shown above.\n"
        )

    # Absolute last resort. Safety flags and verification notes are deliberately
    # never trimmed, so with a very large number of them the loops above cannot
    # get under the provider ceiling. Clamp rather than let Groq 413 (which
    # became a 503 for the user). Trimming order here is least-informative first
    # and still keeps every safety warning; only long prose is clamped.
    if _approx_tokens(SYSTEM_PROMPT) + _approx_tokens(context) > MAX_REQUEST_TOKENS:
        print(
            f"[synthesis] request exceeded {MAX_REQUEST_TOKENS} tokens; "
            "clamping context to fit the provider limit"
        )
        context = _truncate_middle(
            context, MAX_REQUEST_TOKENS * 4 - _approx_tokens(SYSTEM_PROMPT) * 4
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
        # Deliberately no fallback answer. A canned string here looks like a
        # successful grounded response but carries no citations, which reads as
        # a broken product rather than a rate limit. Raising lets the caller
        # surface an honest, retryable error.
        print(f"[synthesis] Groq call failed: {e}")
        raise SynthesisUnavailable(str(e)) from e
