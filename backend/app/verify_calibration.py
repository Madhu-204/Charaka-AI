"""Calibration for the semantic verifier: should `CHARAKA_SEMANTIC_CHECK` be on?

The verifier is committed, tested, and off. Two live runs gave two all-SUPPORTED
and two all-PARTIAL verdicts on unrelated answers, which is not a verdict at all
— it is noise. Turning it on in that state would add an LLM call per request to
buy randomness, so the question is measurable and this measures it.

## Labels are assigned by construction, never by asking a model

The obvious way to build this set is to have an LLM label claim/verse pairs.
That is circular: the thing under test decides the answer key, and any shared
bias becomes apparent skill. So every label here follows from how the pair was
*built*, not from an opinion about it:

| Tier | Label | How the label is known to be correct |
|---|---|---|
| `supported` | SUPPORTED | The claim is a restatement of the verse it is shown. |
| `wrong_verse` | UNSUPPORTED | The same claim, shown against a different verse in the same chapter. |
| `off_topic` | UNSUPPORTED | A claim restating a verse from an unrelated topic. |
| `qualifier_dropped` | PARTIAL | The claim states a verse's conclusion without the condition that verse attaches to it. |

## The paired design is the point

`supported` and `wrong_verse` are the *same claim* shown against two different
verses. The only variable is which verse is in front of the verifier. That makes
the measurement sensitive in a way that scoring claims one at a time is not: a
claim the verifier simply likes will be graded SUPPORTED both times and show up
as noise rather than as skill, because a competent verifier has to move when the
verse moves.

It also means `off_topic` is the easy tier and `wrong_verse` is the one worth
failing. A verifier that only catches cross-topic mismatches is not worth an LLM
call per request, because the structural checks already handle verses that have
nothing to do with the question.

## What the numbers mean

The dangerous direction is a false SUPPORTED on an unsupported claim: it converts
a bad citation into apparent confirmation and suppresses the retry. So that rate
is reported first and gates the decision. Flagging a supported claim is wasteful
but not unsafe, and costs a rewrite.

Everything is paced against a token budget. On an 8K TPM shared tier an
unpaced run of a few hundred calls reliably produces 429s halfway through and
loses the work, which is most likely why the earlier calibration attempt was
abandoned.

Usage:
    python -m app.verify_calibration build --groups 8
    python -m app.verify_calibration run
    python -m app.verify_calibration score
    python -m app.verify_calibration all --groups 8
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BACKEND = Path(__file__).resolve().parent.parent
REFERENCE_SET = BACKEND / "reference" / "verifier_calibration_set.json"

# Headroom under the shared 8K TPM ceiling. The ceiling is per minute and shared
# with nothing else, but requests are not metered uniformly, so planning against
# exactly 8000 turns the run into a race.
TPM_BUDGET = int(os.getenv("CHARAKA_TPM_BUDGET", "6000"))

# Sentences that only announce a section carry no propositional content, so they
# cannot support or fail a claim.
_TITLE_RE = re.compile(
    r"^\s*(we shall now expound|thus declared|now, therefore|end of)", re.I
)

_STOPWORDS = {
    "that", "this", "with", "from", "they", "their", "there", "then", "than",
    "which", "when", "what", "where", "these", "those", "have", "been", "were",
    "into", "also", "such", "other", "shall", "would", "should", "could",
    "both", "each", "about", "after", "before", "while", "because", "through",
}


class Pacer:
    """Keep a rolling 60-second token estimate under a ceiling.

    Sleeps before a call that would cross the budget rather than retrying after
    a 429, because a retried call is still billed and a partially completed run
    is harder to reason about than a slow one.
    """

    def __init__(self, tpm: int = TPM_BUDGET, window: float = 60.0):
        self.tpm = tpm
        self.window = window
        self.events: list[tuple[float, int]] = []
        self.waited = 0.0

    def _trim(self, now: float) -> None:
        self.events = [(t, n) for t, n in self.events if now - t < self.window]

    def wait(self, tokens: int) -> None:
        now = time.time()
        self._trim(now)
        used = sum(n for _, n in self.events)
        if used + tokens > self.tpm and self.events:
            sleep_for = self.window - (now - self.events[0][0]) + 1.0
            if sleep_for > 0:
                time.sleep(sleep_for)
                self.waited += sleep_for
            self._trim(time.time())
        self.events.append((time.time(), tokens))


def _content_words(text: str) -> set[str]:
    words = re.findall(r"[a-z][a-z-]{3,}", (text or "").lower())
    return {w for w in words if w not in _STOPWORDS}


def overlap(a: str, b: str) -> float:
    """Jaccard over content words.

    The guard that keeps generated labels defensible: a "restatement" that shares
    almost nothing with its source is not a restatement, and labelling it
    SUPPORTED would put a wrong key in the answer set.
    """
    wa, wb = _content_words(a), _content_words(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


# --- corpus selection -------------------------------------------------------

_VERSE_COLLECTION = None


def _corpus() -> list[dict]:
    """Substantive chunks from the live collection, grouped by chapter."""
    global _VERSE_COLLECTION
    if _VERSE_COLLECTION is None:
        from app.nodes.retriever import collection

        raw = collection.get(include=["documents", "metadatas"])
        items = []
        for i, (doc, meta) in enumerate(zip(raw["documents"], raw["metadatas"])):
            text = (doc or "").strip()
            if len(text) < 220 or _TITLE_RE.match(text):
                continue
            items.append(
                {
                    "index": i,
                    "text": text,
                    "chapter": meta.get("chapter"),
                    "category": meta.get("category_tag"),
                }
            )
        _VERSE_COLLECTION = items
    return _VERSE_COLLECTION


def select_groups(count: int, min_gap: int = 3) -> list[tuple[dict, dict]]:
    """Verse pairs drawn from within a single chapter, but not from each other.

    Two constraints, both about not accidentally making the test too easy:

    *Same chapter, so the wrong verse is genuinely confusable.* A verse from an
    unrelated chapter is visibly wrong to anyone who has read the text, which is
    the case the structural checks already handle.

    *Separated by at least `min_gap` chunks, because adjacent chunks are often
    continuous prose.* Where a passage says "first do X, then Y", the next chunk
    genuinely continues the thought, so pairing them would label a SUPPORTED
    claim UNSUPPORTED and put a wrong answer in the key.

    Pairs are drawn round-robin across chapters so a small pilot spans different
    parts of the text rather than returning four pairs from the chapter that
    happens to sort first.
    """
    by_chapter: dict[tuple, list[dict]] = {}
    for item in _corpus():
        by_chapter.setdefault((item["category"], item["chapter"]), []).append(item)

    candidates: dict[tuple, list[tuple[dict, dict]]] = {}
    for key, verses in by_chapter.items():
        verses = sorted(verses, key=lambda v: v["index"])
        pairs = [(verses[i], verses[i + min_gap]) for i in range(len(verses) - min_gap)]
        if pairs:
            candidates[key] = pairs

    chosen: list[tuple[dict, dict]] = []
    keys = sorted(candidates, key=lambda k: (str(k[0]), str(k[1])))
    depth = 0
    while len(chosen) < count and any(depth < len(candidates[k]) for k in keys):
        for key in keys:
            if depth < len(candidates[key]):
                chosen.append(candidates[key][depth])
                if len(chosen) >= count:
                    break
        depth += 1
    return chosen


# --- claim generation -------------------------------------------------------

GENERATE_PROMPT = """Read the passage and write short test claims about it.

PASSAGE:
{text}

Return JSON with exactly these keys:
- "claim": one sentence, 8-25 words, stating the passage's main therapeutic claim. Restate it in your own words. Do not copy a clause verbatim. Do not add anything the passage does not say.
- "qualifier": the conditional or qualifying words the passage attaches to that claim (for example "in cases of", "especially", "for one who", "may"). Empty string if the passage states it unconditionally.
- "unconditional": the same claim with the qualifier removed, stated as if it always holds. Empty string if there is no qualifier.

Return only JSON, no other text."""

_JSON_RE = re.compile(r"\{.*\}", re.S)
_FIELD_RE = {
    "claim": re.compile(r'"claim"\s*:\s*"(.*?)"', re.S),
    "qualifier": re.compile(r'"qualifier"\s*:\s*"(.*?)"', re.S),
    "unconditional": re.compile(r'"unconditional"\s*:\s*"(.*?)"', re.S),
}


def _strip_reasoning(text: str) -> str:
    """gpt-oss interleaves a reasoning block; it must not reach the JSON parse."""
    return re.sub(r"<reasoning>.*?</reasoning>", "", text or "", flags=re.S)


def _parse_generation(reply) -> dict:
    body = _strip_reasoning(getattr(reply, "content", "") or "")
    match = _JSON_RE.search(body)
    if not match:
        return {}
    blob = match.group(0)
    out = {}
    for field, pattern in _FIELD_RE.items():
        found = pattern.search(blob)
        if found:
            out[field] = found.group(1).replace('\\"', '"').strip()
    return out


def generate_claims(verses: list[dict], pacer: Pacer) -> list[dict]:
    """One call per verse, reused as both a positive and a negative."""
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_groq import ChatGroq

    llm = ChatGroq(
        model="openai/gpt-oss-120b",
        api_key=__import__("os").environ["GROQ_API_KEY"],
        max_retries=1,
        timeout=45,
        max_tokens=400,
    )
    out = []
    for verse in verses:
        prompt = GENERATE_PROMPT.format(text=verse["text"][:1500])
        pacer.wait(len(prompt) // 3 + 120)
        try:
            reply = llm.invoke(
                [
                    SystemMessage(content="You output only compact JSON."),
                    HumanMessage(content=prompt),
                ]
            )
            fields = _parse_generation(reply)
        except Exception as exc:  # a lost sample must not end the run
            print(f"  generation failed for verse {verse['index']}: {type(exc).__name__}")
            continue

        claim = fields.get("claim", "")
        # Guard: the label is only valid if the claim really restates its verse.
        if not claim or overlap(claim, verse["text"]) < 0.30:
            print(f"  dropped verse {verse['index']}: restatement overlap too low")
            continue

        out.append(
            {
                "verse": verse,
                "claim": claim,
                "qualifier": fields.get("qualifier", ""),
                "unconditional": fields.get("unconditional", ""),
            }
        )
    return out


# --- building the labelled set ---------------------------------------------


def build(groups: int) -> list[dict]:
    pacer = Pacer()
    pair_list = select_groups(groups)
    print(f"selected {len(pair_list)} chapter-local verse pairs")

    records = generate_claims([v for pair in pair_list for v in pair], pacer)
    by_index = {r["verse"]["index"]: r for r in records}
    print(f"generated {len(records)} usable claims (waited {pacer.waited:.0f}s)")

    samples = []
    for verse_a, verse_b in pair_list:
        a, b = by_index.get(verse_a["index"]), by_index.get(verse_b["index"])
        if not a or not b:
            continue
        # Re-check the guard here rather than trusting generate_claims. The label
        # is only valid while the claim restates its verse, and a guard that
        # exists only in the generator is not protecting the answer key — it is
        # protecting it from a code path that nothing else depends on.
        if overlap(a["claim"], a["verse"]["text"]) < 0.30:
            print(f"  dropped pair at verse {verse_a['index']}: claim does not restate its verse")
            continue

        # Same claim, the verse it came from: SUPPORTED by construction.
        samples.append(
            {
                "tier": "supported",
                "label": "SUPPORTED",
                "claim": a["claim"],
                "verse_index": verse_a["index"],
                "verse_text": verse_a["text"],
                "chapter": verse_a["chapter"],
                "category": verse_a["category"],
            }
        )
        # The same claim, the neighbouring verse: UNSUPPORTED by construction, and
        # hard because both verses are from one chapter.
        samples.append(
            {
                "tier": "wrong_verse",
                "label": "UNSUPPORTED",
                "claim": a["claim"],
                "verse_index": verse_b["index"],
                "verse_text": verse_b["text"],
                "chapter": verse_b["chapter"],
                "category": verse_b["category"],
            }
        )

        if a["qualifier"] and a["unconditional"] and len(a["unconditional"]) > 20:
            if overlap(a["unconditional"], a["claim"]) >= 0.25:
                samples.append(
                    {
                        "tier": "qualifier_dropped",
                        "label": "PARTIAL",
                        "claim": a["unconditional"],
                        "verse_index": a["verse"]["index"],
                        "verse_text": a["verse"]["text"],
                        "chapter": a["verse"]["chapter"],
                        "category": a["verse"]["category"],
                    }
                )

    REFERENCE_SET.write_text(
        json.dumps(
            {
                "built_with_groups": len(records) // 2,
                "samples": samples,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"wrote {len(samples)} labelled samples to {REFERENCE_SET.name}")
    _tally(samples)
    return samples


def _tally(samples: list[dict]) -> None:
    counts: dict[str, int] = {}
    for s in samples:
        counts[f"{s['tier']} ({s['label']})"] = counts.get(f"{s['tier']} ({s['label']})", 0) + 1
    for key in sorted(counts):
        print(f"  {key}: {counts[key]}")


def load() -> list[dict]:
    if not REFERENCE_SET.exists():
        raise SystemExit(f"{REFERENCE_SET.name} missing — run `build` first")
    return json.loads(REFERENCE_SET.read_text(encoding="utf-8"))["samples"]


# --- running the verifier ---------------------------------------------------


def run(batch: int = 3) -> None:
    """Score every sample through the real verifier prompt and cache the result."""
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_groq import ChatGroq

    from app.nodes.semantic_check import SYSTEM_PROMPT, _build_prompt, _parse

    samples = load()
    pacer = Pacer()
    llm = ChatGroq(
        model="openai/gpt-oss-120b",
        api_key=os.environ["GROQ_API_KEY"],
        max_retries=1,
        timeout=45,
        max_tokens=300,
    )

    for start in range(0, len(samples), batch):
        chunk = samples[start : start + batch]
        pairs = [(s["claim"], i + 1, s["verse_text"]) for i, s in enumerate(chunk)]
        prompt = _build_prompt(pairs)
        pacer.wait(len(prompt) // 3 + 80)
        try:
            reply = llm.invoke(
                [
                    SystemMessage(content=SYSTEM_PROMPT),
                    HumanMessage(content=prompt),
                ]
            )
            verdicts = _parse(getattr(reply, "content", "") or "", len(chunk))
        except Exception as exc:
            print(f"  batch at {start} failed: {type(exc).__name__}")
            continue

        for offset, verdict in verdicts.items():
            samples[start + offset - 1]["verdict"] = verdict
        print(
            f"  {start + len(chunk)}/{len(samples)} "
            + ", ".join(f"{s['tier']}={v}" for s, v in zip(chunk, verdicts.values()))
        )

    _write_results(samples)
    print(f"waited {pacer.waited:.0f}s for token budget")


def _write_results(samples: list[dict]) -> None:
    REFERENCE_SET.write_text(
        json.dumps({"samples": samples}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# --- scoring ----------------------------------------------------------------

ORDER = {"SUPPORTED": 2, "PARTIAL": 1, "UNSUPPORTED": 0}


def score(threshold: float = 0.10) -> dict:
    samples = [s for s in load() if "verdict" in s]
    if not samples:
        raise SystemExit("no verdicts — run `run` first")

    by_tier: dict[str, list[dict]] = {}
    for s in samples:
        by_tier.setdefault(s["tier"], []).append(s)

    print(f"scoring {len(samples)} samples\n")
    for tier in sorted(by_tier):
        rows = by_tier[tier]
        expected = rows[0]["label"]
        exact = sum(1 for r in rows if r["verdict"] == expected)
        print(f"{tier}  (expect {expected}, n={len(rows)})")
        print(f"  exact match      {exact}/{len(rows)} = {exact / len(rows):.0%}")
        distribution: dict[str, int] = {}
        for r in rows:
            distribution[r["verdict"]] = distribution.get(r["verdict"], 0) + 1
        print(f"  verdicts         {distribution}")

    negatives = by_tier.get("wrong_verse", [])
    false_support = [r for r in negatives if r["verdict"] == "SUPPORTED"]
    false_support_rate = len(false_support) / len(negatives) if negatives else 0.0

    supported = by_tier.get("supported", [])
    false_flag = [r for r in supported if r["verdict"] != "SUPPORTED"]
    false_flag_rate = len(false_flag) / len(supported) if supported else 0.0

    print(f"\nfalse SUPPORTED on a same-chapter wrong verse: {len(false_support)}/{len(negatives)} = {false_support_rate:.0%}")
    if false_support:
        for r in false_support[:3]:
            print(f"  claim: {r['claim'][:90]}")
    print(f"false flag on a correctly cited claim:        {len(false_flag)}/{len(supported)} = {false_flag_rate:.0%}")

    print("\nverdict")
    if not negatives:
        print("  INCONCLUSIVE — no wrong_verse tier was built")
    elif false_support_rate <= threshold and false_flag_rate <= threshold:
        print(f"  ENABLE — both false rates at or under {threshold:.0%}")
        print("  set CHARAKA_SEMANTIC_CHECK=1 and re-run the live sample")
    else:
        print(f"  KEEP OFF — at least one false rate exceeds {threshold:.0%}")
        print("  the verifier cannot currently tell a same-chapter wrong verse from a right one")

    return {
        "false_support_rate": false_support_rate,
        "false_flag_rate": false_flag_rate,
        "n": len(samples),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["build", "run", "score", "all"])
    parser.add_argument("--groups", type=int, default=6, help="chapter-local verse pairs")
    parser.add_argument("--batch", type=int, default=3)
    parser.add_argument("--threshold", type=float, default=0.10)
    args = parser.parse_args()

    if args.command in ("build", "all"):
        build(args.groups)
    if args.command in ("run", "all"):
        run(args.batch)
    if args.command in ("score", "all"):
        score(args.threshold)


if __name__ == "__main__":
    main()