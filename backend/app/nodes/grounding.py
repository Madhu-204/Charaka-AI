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


def grounding(state):
    """Verify every [n] citation marker in the answer points at a real verse.

    Sets:
      grounding_score    0..1 — fraction of the top-N retrieved verses that the
                            answer actually cites (N = min(top-3, retrieved)).
      grounding_cited    list of 1-based marker indices that resolved.
      grounding_notes    diagnostics surfaced to the user.
    """
    answer = state.get("final_answer", "")
    retrieved = state.get("retrieved", [])
    n = min(MAX_CHECKED, len(retrieved))
    notes = []

    if n == 0:
        return {
            "grounding_score": 0.0,
            "grounding_cited": [],
            "grounding_notes": ["No retrieved verses to ground the answer against."],
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

    trace = state.get("trace", [])
    step = (
        f"grounding: {len(set(valid))}/{n} retrieved verse(s) cited inline "
        f"(score {score:.3f})"
    )
    return {
        "grounding_score": score,
        "grounding_cited": sorted(set(valid)),
        "grounding_notes": notes,
        "trace": trace + [step],
    }