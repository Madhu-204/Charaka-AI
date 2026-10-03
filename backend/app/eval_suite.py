import json
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def load_eval_items(corner: bool = False, recall: bool = False) -> list:
    items = json.loads(
        (BACKEND / "reference" / "eval_set.json").read_text(encoding="utf-8")
    )
    if corner:
        extra_path = BACKEND / "reference" / "eval_corner_cases.json"
        if extra_path.exists():
            items = items + json.loads(
                extra_path.read_text(encoding="utf-8")
            )
    if recall:
        probe_path = BACKEND / "reference" / "eval_recall_cases.json"
        if probe_path.exists():
            items = items + json.loads(probe_path.read_text(encoding="utf-8"))
    return items


def run_question(item: dict, mode: str = "retrieval") -> dict:
    from app.nodes.emergency import check_emergency
    from app.nodes.query_expansion import expand_query
    from app.nodes.retriever import retrieve
    from app.nodes.safety import check_safety

    q = item["question"]
    emg = check_emergency({"query": q})
    st = expand_query({"query": q})
    r = retrieve(st)
    s = check_safety({**st, **r, "resolved_chapter": r["resolved_chapter"]})
    resolved = r["resolved_chapter"]
    r_meta = resolved["meta"]

    answer = None
    if mode == "full":
        import os

        from app.graph import charaka_agent

        # Same step ceiling the serving path uses, so an eval run cannot loop
        # where production would have been cut off.
        answer = charaka_agent.invoke(
            {"query": q},
            config={
                "recursion_limit": int(
                    os.getenv("CHARAKA_RECURSION_LIMIT", "25")
                )
            },
        ).get("final_answer")

    expect_emergency = bool(item.get("expected_emergency"))
    exp_sthana = item.get("expected_sthana")
    exp_chapter = item.get("expected_chapter")
    exp_canonical = item.get("expected_canonical")
    exp_verse = item.get("expected_verse_id")

    if expect_emergency:
        resolved_hit = bool(emg["is_emergency"])
        top_n_hit = bool(emg["is_emergency"])
    elif exp_canonical:
        resolved_hit = (st.get("canonical_term") or "").lower() == exp_canonical.lower()
        top_n_hit = resolved_hit
    else:
        # Charaka treats many topics in more than one chapter, so an item may
        # credit several. Both "vimanasthana/1" and "sutrasthana/26" are titled
        # on tastes/rasa, and scoring only the one that happens to be listed
        # turned a correct retrieval into a reported failure.
        acceptable = {
            (exp_sthana, exp_chapter),
            *{
                tuple(part.split("/", 1))
                for part in (item.get("acceptable_chapters") or [])
                if "/" in part
            },
        }
        acceptable = {(s, int(c)) for s, c in acceptable}
        resolved_hit = (r_meta["sthana"], r_meta["chapter"]) in acceptable
        top_n_hit = any(
            (c["meta"]["sthana"], c["meta"]["chapter"]) in acceptable
            for c in r["retrieved"][:3]
        )

    # Verse-level scoring, scored independently of the chapter-level result.
    # Chapter resolution cannot distinguish two verses inside the right chapter,
    # so any experiment about which verse wins needs this separate signal. None
    # is reported for items that do not pin a verse.
    verse_hit = None
    top_n_verse_hit = None
    if exp_verse:
        verse_hit = resolved["verse_id"] == exp_verse
        top_n_verse_hit = any(c["verse_id"] == exp_verse for c in r["retrieved"][:3])

    herbs = s.get("herbs_found", [])
    flags = s.get("safety_flags", [])
    return {
        "eval_id": item["eval_id"],
        "corner": bool(item.get("corner")),
        "recall": bool(item.get("recall")),
        "known_gap": bool(item.get("known_gap")),
        "question": q,
        "expected_emergency": expect_emergency,
        "emergency_flagged": bool(emg["is_emergency"]),
        "expected": (
            "EMERGENCY"
            if expect_emergency
            else exp_canonical
            if exp_canonical
            else f"{exp_sthana}/{exp_chapter}"
        ),
        "expected_verse": exp_verse,
        "verse_hit": verse_hit,
        "top_n_verse_hit": top_n_verse_hit,
        "resolved": (
            f"emergency={emg['is_emergency']}"
            if expect_emergency
            else f"{r_meta['sthana']}/{r_meta['chapter']}"
        ),
        "resolved_verse": resolved["verse_id"],
        "canonical": st["canonical_term"],
        "confidence": r["confidence"],
        "resolved_hit": resolved_hit,
        "top_n_hit": top_n_hit,
        "emergency": bool(emg["is_emergency"]),
        "herbs_found": herbs,
        "safety_flags": flags,
        "safety_sources": s.get("safety_sources", {}),
        "answer": answer,
    }


def _wilson(hits: int, total: int, z: float = 1.96) -> tuple:
    """Wilson score interval for a proportion.

    The recall probe is small enough that a raw percentage invites reading noise
    as signal: 2/25 versus 7/25 looks like a 20-point swing, but the intervals
    overlap heavily. Reporting the interval next to the count keeps a future
    ranking change from being justified by a difference this sample cannot
    resolve. Wilson rather than normal-approximation because it stays sane at
    the 0% and 100% ends, which is exactly where a needle probe lives.
    """
    if total <= 0:
        return (0.0, 0.0)
    p = hits / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    margin = (
        z * ((p * (1 - p) / total + z * z / (4 * total * total)) ** 0.5) / denom
    )
    return (round(100 * max(0.0, centre - margin), 1), round(100 * min(1.0, centre + margin), 1))


def summarize(rows: list) -> dict:
    total = len(rows)
    resolved = sum(1 for x in rows if x["resolved_hit"])
    top_n = sum(1 for x in rows if x["top_n_hit"])
    emergency_false_positives = sum(
        1 for x in rows if x["emergency"] and not x["expected_emergency"]
    )
    known_gaps = sum(1 for x in rows if x["known_gap"])
    gaps_passing = sum(1 for x in rows if x["known_gap"] and x["resolved_hit"])
    herb_queries = [x for x in rows if x["herbs_found"]]
    safety_covered = sum(1 for x in herb_queries if x["safety_flags"])
    core = [x for x in rows if not x["corner"] and not x["recall"]]
    corner = [x for x in rows if x["corner"]]
    recall = [x for x in rows if x["recall"]]

    def _pct(n: int, d: int) -> float:
        return round(100 * n / max(1, d), 1)

    def _group(rows_subset: list) -> dict:
        return {
            "total": len(rows_subset),
            "resolved": sum(1 for x in rows_subset if x["resolved_hit"]),
            "resolved_pct": _pct(
                sum(1 for x in rows_subset if x["resolved_hit"]), len(rows_subset)
            ),
            "top_n": sum(1 for x in rows_subset if x["top_n_hit"]),
            "top_n_pct": _pct(
                sum(1 for x in rows_subset if x["top_n_hit"]), len(rows_subset)
            ),
        }

    # Recall probe, reported apart from the quality sets. `resolved` here is the
    # chapter-level result and stays comparable across sets; `verse` is the
    # strict pinned-verse result and is what a reranking change moves.
    recall_verse = sum(1 for x in recall if x["verse_hit"])
    recall_verse_top_n = sum(1 for x in recall if x["top_n_verse_hit"])
    verse_ci = _wilson(recall_verse, len(recall))
    verse_top_n_ci = _wilson(recall_verse_top_n, len(recall))
    core_ci = _wilson(sum(1 for x in core if x["resolved_hit"]), len(core))
    quality = core + corner
    quality_ci = _wilson(sum(1 for x in quality if x["resolved_hit"]), len(quality))

    return {
        "total": total,
        "resolved": resolved,
        "resolved_pct": _pct(resolved, total),
        "top_n": top_n,
        "top_n_pct": _pct(top_n, total),
        "emergency_false_positives": emergency_false_positives,
        "known_gaps": known_gaps,
        "known_gaps_admitted": known_gaps - gaps_passing,
        "herb_queries": len(herb_queries),
        "safety_covered": safety_covered,
        # Headline over the real question sets only. `resolved_pct` above spans
        # every row, so once the 120 synthetic needles are switched on it reads
        # like a catastrophic regression that is really just the probe
        # outnumbering the quality sets 4:1. The quality figure is the one to
        # judge a retrieval change by.
        "quality": {
            "total": len(quality),
            "resolved": sum(1 for x in quality if x["resolved_hit"]),
            "resolved_pct": _pct(
                sum(1 for x in quality if x["resolved_hit"]), len(quality)
            ),
            "resolved_ci": quality_ci,
            "top_n": sum(1 for x in quality if x["top_n_hit"]),
            "top_n_pct": _pct(sum(1 for x in quality if x["top_n_hit"]), len(quality)),
        },
        "core": {
            "total": len(core),
            "resolved": sum(1 for x in core if x["resolved_hit"]),
            "resolved_pct": _pct(sum(1 for x in core if x["resolved_hit"]), len(core)),
            "resolved_ci": core_ci,
            "top_n": sum(1 for x in core if x["top_n_hit"]),
            "top_n_pct": _pct(sum(1 for x in core if x["top_n_hit"]), len(core)),
        },
        "corner": {
            "total": len(corner),
            "resolved": sum(1 for x in corner if x["resolved_hit"]),
            "resolved_pct": _pct(sum(1 for x in corner if x["resolved_hit"]), len(corner)),
            "top_n": sum(1 for x in corner if x["top_n_hit"]),
            "top_n_pct": _pct(sum(1 for x in corner if x["top_n_hit"]), len(corner)),
        },
        "recall": {
            "total": len(recall),
            "chapter_resolved": sum(1 for x in recall if x["resolved_hit"]),
            "chapter_resolved_pct": _pct(
                sum(1 for x in recall if x["resolved_hit"]), len(recall)
            ),
            "verse": recall_verse,
            "verse_pct": _pct(recall_verse, len(recall)),
            "verse_ci": verse_ci,
            "verse_top_n": recall_verse_top_n,
            "verse_top_n_pct": _pct(recall_verse_top_n, len(recall)),
            "verse_top_n_ci": verse_top_n_ci,
        },
    }