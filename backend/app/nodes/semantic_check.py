"""Semantic self-verification: does the cited verse actually say what was claimed?

`grounding.py` is structural. It checks that every `[n]` marker parses and points
at a verse that exists in the retrieved set. It cannot catch the failure that
actually matters: a real verse, correctly numbered, cited for something it does
not say. A Charaka answer can be perfectly well-formed and still attribute
a claim to a passage that never made it.

This node asks the model that narrow question and nothing else, for the claims
that carry a citation. It is deliberately not a second grader — it never scores
fluency, tone or completeness, because those are not safety properties.

**Off by default** (`CHARAKA_SEMANTIC_CHECK=1` to enable), for the same reason
the cross-encoder reranker is: it costs an LLM call, and on an 8K TPM shared
tier an unmeasured extra call per request is how a free deployment starts
returning 429s. Enable it once the eval set says it catches real errors.

Bounded to **one call per request** — it only inspects the first draft, so the
worst case is two synthesis calls plus one verification, never a loop.

The known cost of that bound: when a flag triggers a rewrite, the answer the user
actually sees is the second draft, and that draft is not independently verified.
It was produced in response to the criticism rather than checked against it.

A provider failure here must never fail the request. The answer has already been
drafted and structurally checked; degrading to "unverified" is correct, and
raising would turn a verification nicety into an outage.
"""

import os
import re

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq

from .attribution import _sentences

load_dotenv()

# How many cited claims to verify. Each one adds its verse text to the prompt, so
# this is the main lever on token cost. Three covers the claims a reader is most
# likely to act on without inflating the prompt past the point of diminishing
# returns.
MAX_CLAIMS = 3

MARKER_RE = re.compile(r"\[(\d{1,2})\]")
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([.,;:!?])")
VERDICT_RE = re.compile(r"CLAIM\s+(\d+)\s*:\s*(SUPPORTED|PARTIAL|UNSUPPORTED)", re.I)

SYSTEM_PROMPT = """You check whether a cited source actually supports a claim. You are terse and literal.

For each numbered CLAIM you are shown the VERSE it cites. Reply with exactly one line per claim:

CLAIM <n>: SUPPORTED
CLAIM <n>: PARTIAL
CLAIM <n>: UNSUPPORTED

Use:
- SUPPORTED: the verse states this claim.
- PARTIAL: the verse is on the same topic but is narrower, vaguer, or carries a qualification the claim drops.
- UNSUPPORTED: the verse is about something else, or does not state this at all.

Judge only from the verse text given. Do not use outside knowledge, do not reward a claim for being
plausible, and do not explain. A claim about a treatment, dose, cause or outcome must be traceable to
words in the verse. Output the verdict lines and nothing else."""


def _enabled() -> bool:
    return os.environ.get("CHARAKA_SEMANTIC_CHECK", "0") == "1"


def _cited_claims(answer: str, retrieved: list, limit: int) -> list:
    """Pair each citation-bearing sentence with the verse it points at.

    Only the first marker in a sentence is used, so one sentence contributes one
    claim rather than one per marker. Distinct sentences citing the same verse are
    all kept: "relieves colic [1]" and "safe in pregnancy [1]" are two separate
    factual claims, and the second is exactly the kind that can be wrong while the
    first is fine.
    """
    pairs = []
    for sentence in _sentences(answer):
        m = MARKER_RE.search(sentence)
        if not m:
            continue
        n = int(m.group(1))
        if not 1 <= n <= len(retrieved):
            continue
        verse = retrieved[n - 1]
        text = (verse.get("text") or "").strip()
        if not text:
            continue
        claim = MARKER_RE.sub("", sentence).strip()
        # Removing "[1]" from mid-sentence leaves "colic ." — tidy the space it
        # strands before punctuation so the model reads a clean claim.
        claim = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", claim).strip()
        if claim:
            pairs.append((claim, n, text))
        if len(pairs) >= limit:
            break
    return pairs


def _parse(text: str, count: int) -> dict:
    """Pull verdicts out of the reply, defaulting anything unparseable to PARTIAL.

    A garbled reply must not read as SUPPORTED — that would turn a verifier
    failure into a false assurance, which is worse than having no verifier.
    """
    found = {}
    for idx, verdict in VERDICT_RE.findall(text or ""):
        i = int(idx)
        if 1 <= i <= count and i not in found:
            found[i] = verdict.upper()
    return {i: found.get(i, "PARTIAL") for i in range(1, count + 1)}


def _build_prompt(pairs: list) -> str:
    blocks = []
    for i, (claim, _marker, verse_text) in enumerate(pairs, start=1):
        blocks.append(f"CLAIM {i}: {claim}\nVERSE: {verse_text}")
    return "\n\n".join(blocks)


def semantic_check(state):
    """Set `grounding_semantic` — a per-claim support verdict for cited claims.

    Also sets `grounding_retry_instruction` when a claim is unsupported, reusing
    the retry edge the citation check already owns rather than adding a second
    loop. Skipped when disabled, when nothing was cited, or when a structural
    retry is already pending — in that case the rewrite addresses the more
    fundamental fault and the extra call would buy nothing.
    """
    trace = state.get("trace", [])
    answer = state.get("final_answer", "")
    retrieved = state.get("retrieved", [])

    def skipped(reason: str):
        return {"grounding_semantic": [], "trace": trace + [f"semantic_check: skipped ({reason})"]}

    if not _enabled():
        return skipped("CHARAKA_SEMANTIC_CHECK off")
    if not answer or not retrieved:
        return skipped("nothing to verify")
    if state.get("grounding_retry_instruction"):
        return skipped("citation retry already pending")
    # Only the first draft is verified. Verifying every attempt would double the
    # call count on exactly the requests that are already most expensive, and the
    # rewrite a flag produces is a response to the criticism rather than an
    # independently checked answer — so re-verifying it buys precision we cannot
    # act on anyway. This is what holds the worst case at one extra call.
    if state.get("synthesis_attempts", 1) > 1:
        return skipped("only the first draft is verified")

    pairs = _cited_claims(answer, retrieved, MAX_CLAIMS)
    if not pairs:
        return skipped("no cited claims")

    try:
        llm = ChatGroq(
            model="openai/gpt-oss-120b",
            api_key=os.environ["GROQ_API_KEY"],
            max_retries=1,
            timeout=30,
            max_tokens=300,
        )
        reply = llm.invoke(
            [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=_build_prompt(pairs))]
        )
        verdicts = _parse(getattr(reply, "content", "") or "", len(pairs))
    except Exception as exc:  # provider down, rate-limited, unparseable
        return skipped(f"verifier unavailable ({type(exc).__name__})")

    results = [
        {"claim": claim, "marker": marker, "verdict": verdicts[i], "verse_id": retrieved[marker - 1].get("verse_id")}
        for i, (claim, marker, _text) in enumerate(pairs, start=1)
    ]
    unsupported = [r for r in results if r["verdict"] == "UNSUPPORTED"]

    instruction = None
    if unsupported:
        instruction = (
            "A reviewer checked your citations and found that the cited verse does not actually "
            "state the claim: "
            + "; ".join(f'"{r["claim"][:120]}" is cited as [{r["marker"]}] but that verse does not say it' for r in unsupported)
            + ". Rewrite so every remaining claim is supported by the verse it cites. If you cannot "
            "support a claim from the given context, leave it out rather than keeping the citation."
        )

    summary = ", ".join(f"[{r['marker']}] {r['verdict'].lower()}" for r in results)
    step = f"semantic_check: {len(results)} cited claim(s) verified — {summary}"
    if unsupported:
        step += " — retrying synthesis with support feedback"

    out = {
        "grounding_semantic": results,
        "trace": trace + [step],
    }
    if instruction:
        out["grounding_retry_instruction"] = instruction
    return out