import re


MARKER_RE = re.compile(r"\[(\d{1,2})\]")
MAX_CHECKED = 3


def _cited_markers(answer: str) -> list[int]:
    seen = set()
    out = []
    for m in MARKER_RE.finditer(answer):
        n = int(m.group(1))
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def _retry_instruction(n: int, valid: list[int], out_of_range: list[int]) -> str:
    """Build the correction passed to a second synthesis pass.

    Only fires on failures a rewrite can actually fix. Low coverage (say 1 of 3
    verses cited) is deliberately NOT retried: an answer that draws on one verse
    honestly is not a defect, and re-spending a synthesis call to make it cite
    more would cost tokens to satisfy a metric rather than fix an error.
    """
    # Spelled as [1], [2] rather than [1, 2] so a marker quoted back from this
    # sentence is unambiguously a single citation, not a range.
    valid_markers = ", ".join(f"[{i}]" for i in range(1, n + 1))
    if out_of_range:
        return (
            "Your previous answer cited source numbers that do not exist: "
            f"{out_of_range}. Only {n} verse(s) were retrieved, so the only valid "
            f"inline markers are {valid_markers}. Rewrite the answer using only those "
            "markers. If a claim is not supported by any of those verses, leave it out "
            "rather than inventing a citation."
        )
    additional_markers = ", ".join(f"[{i}]" for i in range(2, n + 1)) or "none"
    return (
        "Your previous answer cited no retrieved verse inline. Every factual claim "
        "drawn from the context must carry the marker of the verse it came from: the "
        f"PRIMARY CONTEXT is [1], and the ADDITIONAL CONTEXT blocks are "
        f"{additional_markers}. Cite at least [1] wherever you state what the text says."
    )


def grounding(state):
    """Verify every [n] citation marker in the answer points at a real verse.

    Sets:
      grounding_score    0..1 — fraction of the top-N retrieved verses that the
                            answer actually cites (N = min(top-3, retrieved)).
      grounding_cited    list of 1-based marker indices that resolved.
      grounding_notes    diagnostics surfaced to the user.
      grounding_retry_instruction
                         set only when a second synthesis pass could plausibly
                         produce a better answer; the graph reads it as the retry
                         signal. See _retry_instruction for what is excluded.
    """
    answer = state.get("final_answer", "")
    retrieved = state.get("retrieved", [])
    n = min(MAX_CHECKED, len(retrieved))
    notes = []

    if n == 0:
        # Nothing was retrieved, so there is no verse to cite and no marker that
        # could be validated. Another pass would face the identical context, so
        # this is a retrieval failure, not a drafting one — do not retry.
        return {
            "grounding_score": 0.0,
            "grounding_cited": [],
            "grounding_notes": ["No retrieved verses to ground the answer against."],
            "grounding_retry_instruction": None,
            "grounding_ungrounded": True,
        }

    markers = _cited_markers(answer)
    valid = [m for m in markers if 1 <= m <= n]
    out_of_range = [m for m in markers if m > n]

    coverage = len(set(valid)) / n if n else 0.0
    score = round(min(coverage, 1.0), 3)

    if not markers:
        notes.append("The answer did not cite any retrieved verse inline — treat with extra caution.")
    elif out_of_range:
        notes.append(
            f"Answer cites out-of-range sources {out_of_range} (only {n} verses were retrieved)."
        )

    confidence = state.get("confidence")
    if confidence == "low":
        notes.append("Retrieval confidence is low — the closest match may not be exact.")

    # An empty marker list and an out-of-range one are both drafting faults the
    # model can be told about and correct. Anything else ships as-is.
    retry = _retry_instruction(n, valid, out_of_range) if (not valid or out_of_range) else None

    trace = state.get("trace", [])
    step = (
        f"grounding: {len(set(valid))}/{n} retrieved verse(s) cited inline "
        f"(score {score:.3f})"
    )
    if retry:
        step += " — retrying synthesis with citation feedback"
    return {
        "grounding_score": score,
        "grounding_cited": sorted(set(valid)),
        "grounding_notes": notes,
        "grounding_retry_instruction": retry,
        # True when the draft that ships carries no citation this check could
        # accept. Not a verdict on the prose — it says the answer asserts
        # Charaka's authority without pointing at a passage, which is the one
        # failure a user cannot detect by reading. The retry may still fix it;
        # this stays False on a rewrite that cites properly, so it describes the
        # shipped answer rather than the first attempt.
        "grounding_ungrounded": not valid,
        "trace": trace + [step],
    }