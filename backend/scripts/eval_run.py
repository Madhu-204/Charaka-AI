import argparse
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.eval_suite import load_eval_items, run_question, summarize  # noqa: E402

# How many recall misses to print before collapsing to a count.
RECALL_MISS_SAMPLE = 12


def main():
    parser = argparse.ArgumentParser(
        description="Run the eval plus corner-case suite through the Charaka AI pipeline."
    )
    parser.add_argument(
        "--mode",
        choices=["retrieval", "full"],
        default="retrieval",
        help="retrieval = no LLM (free); full = also invokes the agent (Groq)",
    )
    parser.add_argument(
        "--corner",
        action="store_true",
        help="also run the corner-case regression set (reference/eval_corner_cases.json)",
    )
    parser.add_argument(
        "--recall",
        action="store_true",
        help="also run the verse-level recall probe (reference/eval_recall_cases.json). "
        "Synthetic needle queries that pin one verse; measures recall, not answer quality.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="list every recall miss instead of the first few",
    )
    args = parser.parse_args()

    eval_items = load_eval_items(corner=args.corner, recall=args.recall)
    rows = [run_question(item, mode=args.mode) for item in eval_items]
    summary = summarize(rows)

    print(f"\n{'=' * 78}")
    print(f"EVAL — {summary['total']} questions · mode={args.mode} · "
          f"corner={'yes' if args.corner else 'no'} · "
          f"recall={'yes' if args.recall else 'no'}")
    print(f"{'=' * 78}")
    for r in rows:
        mark = "+" if r["resolved_hit"] else "x"
        top = "T" if r["top_n_hit"] else "-"
        gap = "  [KNOWN GAP]" if r["known_gap"] else ""
        canonical = f"  [canonical={r['canonical']}]" if r["canonical"] else ""
        herb_info = f"  herbs={len(r['herbs_found'])}" if r["herbs_found"] else ""
        flag_info = f"  flags={len(r['safety_flags'])}" if r["safety_flags"] else ""
        src = r.get("safety_sources", {})
        src_counts = {}
        for v in src.values():
            src_counts[v] = src_counts.get(v, 0) + 1
        src_info = ""
        if src_counts:
            src_info = "  src:" + ",".join(f"{k}={v}" for k, v in sorted(src_counts.items()))
        print(
            f"{mark}{top} {r['eval_id']}  expected={r['expected']:<22} "
            f"resolved={r['resolved']:<22} conf={r['confidence']:<4}"
            f"{herb_info}{flag_info}{src_info}{canonical}{gap}"
        )
        if r["answer"]:
            print(f"        answer: {r['answer'][:180]}...")
    print(f"{'=' * 78}")
    q = summary["quality"]
    print(f"Quality sets     : {q['resolved']}/{q['total']} ({q['resolved_pct']}%, "
          f"95% CI {q['resolved_ci'][0]}-{q['resolved_ci'][1]}%)  "
          f"[core: {summary['core']['resolved']}/{summary['core']['total']} "
          f"({summary['core']['resolved_pct']}%, 95% CI "
          f"{summary['core']['resolved_ci'][0]}-{summary['core']['resolved_ci'][1]}%), "
          f"corner: "
          f"{summary['corner']['resolved']}/{summary['corner']['total']} "
          f"({summary['corner']['resolved_pct']}%)]")
    print(f"  (all rows incl. probe: {summary['resolved']}/{summary['total']} "
          f"({summary['resolved_pct']}%) — not comparable once the probe is on)")
    print(f"Top-3 accuracy   : {summary['top_n']}/{summary['total']} "
          f"({summary['top_n_pct']}%)")
    rec = summary["recall"]
    if rec["total"]:
        print(f"Recall probe     : {rec['total']} needle cases · "
              f"verse hit {rec['verse']}/{rec['total']} ({rec['verse_pct']}%, 95% CI "
              f"{rec['verse_ci'][0]}-{rec['verse_ci'][1]}%) · "
              f"verse in top-3 {rec['verse_top_n']}/{rec['total']} "
              f"({rec['verse_top_n_pct']}%, 95% CI "
              f"{rec['verse_top_n_ci'][0]}-{rec['verse_top_n_ci'][1]}%) · "
              f"chapter hit {rec['chapter_resolved']}/{rec['total']} "
              f"({rec['chapter_resolved_pct']}%)")
        print("                   (synthetic needles; a recall floor, not answer quality)")
    print(f"False emergency positives: {summary['emergency_false_positives']}/{summary['total']}")
    print(f"Known gaps       : {summary['known_gaps']} "
          f"({summary['known_gaps_admitted']} admitted/not yet fixed)")
    print(f"{'=' * 78}")
    print(f"Safety coverage   : {summary['safety_covered']}/{summary['herb_queries']} herb queries "
          f"got flags")
    for r in rows:
        if r["herbs_found"] and not r["safety_flags"]:
            print(f"  UNCOVERED {r['eval_id']}: herbs={r['herbs_found']}")
    print(f"{'=' * 78}")

    for r in rows:
        if not r["resolved_hit"]:
            print(f"  MISS {r['eval_id']}: expected {r['expected']} -> resolved {r['resolved']} "
                  f"({r['resolved_verse']}) conf={r['confidence']}"
                  f"{'  (known gap)' if r['known_gap'] else ''}")

    missed_verses = [r for r in rows if r["verse_hit"] is False]
    if missed_verses:
        print(f"{'=' * 78}")
        print(f"Recall misses ({len(missed_verses)}): the pinned verse was not resolved")
        # At 120 probe cases the full list is a wall of text that hides the
        # summary above it. Show enough to see the shape of the failure and
        # report the remainder as a count; the count is what matters.
        shown = missed_verses if args.verbose else missed_verses[:RECALL_MISS_SAMPLE]
        for r in shown:
            top3 = "in top-3" if r["top_n_verse_hit"] else "NOT in top-3"
            print(f"  {r['eval_id']}: expected {r['expected_verse']} "
                  f"-> got {r['resolved_verse']} ({top3}, conf={r['confidence']})")
        if len(missed_verses) > shown:
            print(f"  ... and {len(missed_verses) - len(shown)} more "
                  f"(re-run with --verbose to list all)")
        # A verse that never reaches the top 3 cannot be fixed by reranking the
        # existing pool: it is a recall failure, and widening the pool is the
        # only thing that would admit it.
        recall_failures = [r for r in missed_verses if not r["top_n_verse_hit"]]
        print(f"  -> {len(recall_failures)} are recall failures "
              f"(candidate pool never contained the verse)")


if __name__ == "__main__":
    main()