STHANA_NAMES = {
    "sutrasthana": "Sutra Sthana",
    "vimanasthana": "Vimana Sthana",
    "sharirasthana": "Sharira Sthana",
    "chikitsasthana": "Chikitsa Sthana",
}


def _nearby_hints(retrieved):
    if not retrieved:
        return None
    lines = []
    for rc in retrieved[:2]:
        meta = rc["meta"]
        sthana = STHANA_NAMES.get(meta["sthana"], meta["sthana"])
        lines.append(
            f"- {sthana} Ch.{meta['chapter']} ({meta.get('traditional_condition') or meta.get('category_tag')})"
        )
    return "\n".join(lines)


def clarify(state):
    query = state["query"]
    selected = state.get("resolved_chapter")
    nearby = _nearby_hints(state.get("retrieved", []))

    if nearby:
        question = (
            f"Your question ('{query[:80]}') is close to content in the classical texts, "
            f"but the match isn't specific enough for me to pin down the right verse. "
            f"Closest chapters were:\n{nearby}\n\n"
            "Can you tell me a little more — for example whether it bothers you most "
            "after meals, in the morning, or with stress, and roughly how long you've "
            "noticed it? That will let me ground a precise answer."
        )
    else:
        question = (
            f"I couldn't match '{query[:80]}' to a specific passage in the classical "
            "texts with confidence. Could you tell me a little more about what you're "
            "experiencing (when it happens, how long it's lasted, and what you've tried)?"
        )

    trace = state.get("trace", [])
    step = "clarification: confidence low + no canonical term → asked user to disambiguate"
    return {
        "is_clarification": True,
        "clarification": question,
        "final_answer": question,
        "trace": trace + [step],
    }