import argparse
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.nodes.query_expansion import expand_query
from app.nodes.retriever import retrieve
from app.nodes.safety import check_safety
from app.nodes.emergency import check_emergency


def main():
    parser = argparse.ArgumentParser(
        description="Run the 20-question eval set through the Charaka AI pipeline."
    )
    parser.add_argument(
        "--mode",
        choices=["retrieval", "full"],
        default="retrieval",
        help="retrieval = no LLM (free); full = also invokes the agent (Groq)",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=3,
        help="pool depth used for the 'top-N' accuracy metric (default 3)",
    )
    args = parser.parse_args()

    with open(BACKEND / "reference" / "eval_set.json", encoding="utf-8") as f:
        eval_items = json.load(f)

    if args.mode == "full":
        from app.graph import charaka_agent

    rows = []
    for item in eval_items:
        q = item["question"]
        exp_sthana, exp_chapter = item["expected_sthana"], item["expected_chapter"]

        emg = check_emergency({"query": q})
        st = expand_query({"query": q})
        r = retrieve(st)
        s = check_safety({**st, **r, "resolved_chapter": r["resolved_chapter"]})
        resolved = r["resolved_chapter"]
        r_meta = resolved["meta"]

        resolved_hit = (
            r_meta["sthana"] == exp_sthana and r_meta["chapter"] == exp_chapter
        )
        top_n_hit = any(
            c["meta"]["sthana"] == exp_sthana and c["meta"]["chapter"] == exp_chapter
            for c in r["retrieved"][: args.top_n]
        )

        answer = None
        if args.mode == "full":
            full = charaka_agent.invoke({"query": q})
            answer = full["final_answer"]

        rows.append(
            {
                "eval_id": item["eval_id"],
                "question": q,
                "expected": f"{exp_sthana}/{exp_chapter}",
                "resolved": f"{r_meta['sthana']}/{r_meta['chapter']}",
                "resolved_verse": resolved["verse_id"],
                "canonical": st["canonical_term"],
                "confidence": r["confidence"],
                "resolved_hit": resolved_hit,
                "top_n_hit": top_n_hit,
                "emergency": emg["is_emergency"],
                "answer": answer,
            }
        )

    resolved_hits = sum(1 for r in rows if r["resolved_hit"])
    top_n_hits = sum(1 for r in rows if r["top_n_hit"])
    emergency_false_positives = sum(1 for r in rows if r["emergency"])

    print(f"\n{'=' * 78}")
    print(f"EVAL — 20 questions · mode={args.mode} · top-N={args.top_n}")
    print(f"{'=' * 78}")
    for r in rows:
        mark = "✓" if r["resolved_hit"] else "✗"
        top = "T" if r["top_n_hit"] else "-"
        canonical = f"  [canonical={r['canonical']}]" if r["canonical"] else ""
        print(
            f"{mark}{top} {r['eval_id']}  expected={r['expected']:<22} "
            f"resolved={r['resolved']:<22} conf={r['confidence']:<4}"
            f"{canonical}"
        )
        if r["answer"]:
            print(f"        answer: {r['answer'][:180]}...")
    print(f"{'=' * 78}")
    print(f"Resolved accuracy : {resolved_hits}/20 ({resolved_hits * 5}%)  "
          f"[Phase 3 baseline top-1: 16/20 (80%)]")
    print(f"Top-{args.top_n} accuracy: {top_n_hits}/20 ({top_n_hits * 5}%)  "
          f"[Phase 3 baseline top-3: 17/20 (85%)]")
    print(f"False emergency positives: {emergency_false_positives}/20")
    print(f"{'=' * 78}")

    for r in rows:
        if not r["resolved_hit"]:
            print(f"  MISS {r['eval_id']}: expected {r['expected']} -> resolved {r['resolved']} "
                  f"({r['resolved_verse']}) conf={r['confidence']}")


if __name__ == "__main__":
    main()