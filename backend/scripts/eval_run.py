import argparse
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.eval_suite import load_eval_items, run_question, summarize  # noqa: E402


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
    args = parser.parse_args()

    eval_items = load_eval_items(corner=args.corner)
    rows = [run_question(item, mode=args.mode) for item in eval_items]
    summary = summarize(rows)

    print(f"\n{'=' * 78}")
    print(f"EVAL — {summary['total']} questions · mode={args.mode} · "
          f"corner={'yes' if args.corner else 'no'}")
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
    print(f"Resolved accuracy : {summary['resolved']}/{summary['total']} "
          f"({summary['resolved_pct']}%)  "
          f"[core: {summary['core']['resolved']}/{summary['core']['total']} "
          f"({summary['core']['resolved_pct']}%), corner: "
          f"{summary['corner']['resolved']}/{summary['corner']['total']} "
          f"({summary['corner']['resolved_pct']}%)]")
    print(f"Top-3 accuracy   : {summary['top_n']}/{summary['total']} "
          f"({summary['top_n_pct']}%)")
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


if __name__ == "__main__":
    main()