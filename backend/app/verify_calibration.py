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
# cannot support or fail a claim. The later patterns matter more than they look:
# "This chapter will discuss..." and "Providing exhaustive information on..."
# pass as prose, and a restatement of one is trivially SUPPORTED against its own
# verse, so leaving them in quietly pads the easiest tier with free passes.
_TITLE_RE = re.compile(
    r"^\s*(we shall now expound|thus declared|now, therefore|end of"
    r"|this chapter will|this section will|in this chapter|let us now"
    r"|providing exhaustive|we now proceed)",
    re.I,
)

# Below this a generated "restatement" is not one. Read off the observed spread
# rather than assumed: across twelve live generations every faithful restatement
# scored at or above 0.50 on loose_coverage and the single bad one scored 0.00,
# so the threshold sits in the gap. Jaccard was tried first and had no such gap
# (0.05-0.44 across valid samples), which is why it is not used.
MIN_RESTATEMENT_COVERAGE = 0.45

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
    """Jaccard over content words."""
    wa, wb = _content_words(a), _content_words(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def coverage(claim: str, verse: str) -> float:
    """How much of the *claim* is present in the verse.

    The guard that decides whether a SUPPORTED label is legitimate is coverage,
    not Jaccard. Jaccard divides by the union, so it penalises a claim for being
    shorter than its verse: a faithful compressed restatement of a 90-word chunk
    scores lower than a near-verbatim copy of it, which is backwards for the
    question being asked ("does the verse state this claim", not "are these two
    the same length").

    Coverage also does not punish the verse for saying more than the claim,
    which is the normal case for a summary.
    """
    wc, wv = _content_words(claim), _content_words(verse)
    if not wc:
        return 0.0
    return len(wc & wv) / len(wc)


def loose_coverage(claim: str, verse: str) -> float:
    """Coverage under a shared-prefix match.

    Exact matching misses morphology: "administering" is not "administered" is
    not "administration", so an LLM restatement of a verse that says
    "administered" scores as if it were unrelated. A six-character prefix is a
    crude and deliberately unprincipled stand-in for a stemmer — it merges some
    unrelated words and splits some related ones — but it is only ever used to
    decide whether to *trust a generated label*, and the thresholds were read off
    the observed distribution rather than assumed.
    """
    wc, wv = _content_words(claim), _content_words(verse)
    if not wc:
        return 0.0
    prefixes = {w[:6] for w in wv}
    return sum(1 for w in wc if w[:6] in prefixes) / len(wc)


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


def diagnose(verses: list[dict], pacer: Pacer) -> None:
    """Report guard scores instead of applying them.

    Thresholds chosen by guessing produced a guard that rejected a faithful
    restatement of a 90-word passage, and twelve identical "overlap too low"
    lines gave no hint why. Printing all three measures for every sample is the
    only way to see where good and bad restatements actually separate.
    """
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_groq import ChatGroq

    llm = ChatGroq(
        model="openai/gpt-oss-120b",
        api_key=os.environ["GROQ_API_KEY"],
        max_retries=1,
        timeout=45,
        max_tokens=1200,
        reasoning_effort="low",
    )
    print(f"{'jaccard':>8} {'cover':>7} {'loose':>7}  claim")
    for verse in verses:
        prompt = GENERATE_PROMPT.format(text=verse["text"][:1500])
        pacer.wait(len(prompt) // 3 + 400)
        try:
            reply = llm.invoke(
                [
                    SystemMessage(content="You output only compact JSON."),
                    HumanMessage(content=prompt),
                ]
            )
        except Exception as exc:
            print(f"  failed: {type(exc).__name__}")
            continue
        meta = getattr(reply, "response_metadata", {}) or {}
        if meta.get("finish_reason") == "length":
            print(f"{'--':>8} {'--':>7} {'--':>7}  [truncated]")
            continue
        claim = _parse_generation(reply).get("claim", "")
        if not claim:
            print(f"{'--':>8} {'--':>7} {'--':>7}  [no claim]")
            continue
        print(
            f"{overlap(claim, verse['text']):8.3f} "
            f"{coverage(claim, verse['text']):7.3f} "
            f"{loose_coverage(claim, verse['text']):7.3f}  {claim[:70]}"
        )


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
    """One call per verse, reused as both a positive and a negative.

    The reasoning budget matters more than it looks. gpt-oss spends the
    completion budget on reasoning first, and a restatement task provokes far
    more reasoning than the verifier's terse verdict does — at 400 completion
    tokens it returned `finish_reason=length` with 398 reasoning tokens and
    empty content, so every sample was silently dropped and the run produced an
    empty set with no explanation. Hence the larger budget, `low` reasoning
    effort, and an explicit truncation retry rather than a quiet skip.
    """
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_groq import ChatGroq

    llm = ChatGroq(
        model="openai/gpt-oss-120b",
        api_key=os.environ["GROQ_API_KEY"],
        max_retries=1,
        timeout=45,
        max_tokens=1200,
        reasoning_effort="low",
    )
    out = []
    for verse in verses:
        prompt = GENERATE_PROMPT.format(text=verse["text"][:1500])
        pacer.wait(len(prompt) // 3 + 400)
        try:
            reply = llm.invoke(
                [
                    SystemMessage(content="You output only compact JSON."),
                    HumanMessage(content=prompt),
                ]
            )
        except Exception as exc:  # a lost sample must not end the run
            print(f"  generation failed for verse {verse['index']}: {type(exc).__name__}")
            continue

        meta = getattr(reply, "response_metadata", {}) or {}
        if meta.get("finish_reason") == "length":
            # Say so rather than reporting a content-based rejection that looks
            # like a labelling problem.
            print(
                f"  verse {verse['index']}: reasoning consumed the token budget, "
                "no claim generated"
            )
            continue

        fields = _parse_generation(reply)
        claim = fields.get("claim", "")
        # Guard: the label is only valid if the claim really restates its verse.
        if not claim or loose_coverage(claim, verse["text"]) < MIN_RESTATEMENT_COVERAGE:
            print(f"  dropped verse {verse['index']}: claim does not restate its verse")
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


def build(groups: int, force: bool = False) -> list[dict]:
    if REFERENCE_SET.exists() and not force:
        try:
            existing = json.loads(REFERENCE_SET.read_text(encoding="utf-8")).get("samples", [])
        except json.JSONDecodeError:
            existing = []
        scored = sum(1 for s in existing if "verdict" in s)
        if scored:
            raise SystemExit(
                f"{REFERENCE_SET.name} holds {scored} scored sample(s). Rebuilding would "
                "discard those verdicts, which cost real tokens to produce. Move it "
                "aside, or pass --force if the new set is worth more than the old one."
            )

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
        if loose_coverage(a["claim"], a["verse"]["text"]) < MIN_RESTATEMENT_COVERAGE:
            print(f"  dropped pair at verse {verse_a['index']}: claim does not restate its verse")
            continue

        # The wrong_verse tier asserts that the neighbouring verse does not state
        # this claim. If it restates it about as well as the original does, the
        # corpus has a duplicate or a paraphrase and the label is simply wrong —
        # silently poisoning the one tier the whole measurement turns on.
        cov_source = loose_coverage(a["claim"], a["verse"]["text"])
        cov_other = loose_coverage(a["claim"], b["verse"]["text"])
        if cov_other >= cov_source - 0.10:
            print(
                f"  dropped pair at verse {verse_a['index']}: neighbour verse covers the "
                f"claim too well ({cov_other:.2f} vs {cov_source:.2f}), UNSUPPORTED unsafe"
            )
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


def _wilson_upper(hits: int, total: int, z: float = 1.96) -> float:
    """Upper bound on a proportion, for when the point estimate is 0.

    Zero false assurances out of six is the headline number here and it is not
    the strong result it looks like: the rule of three puts the 95% upper bound
    near 50%, so "0/6" is compatible with a true rate anywhere up to that. A
    report that shows only the point estimate invites reading a bound as a
    measurement.
    """
    if total == 0:
        return 1.0
    p = hits / total
    denom = 1 + z * z / total
    centre = p + z * z / (2 * total)
    margin = z * ((p * (1 - p) / total + z * z / (4 * total * total)) ** 0.5)
    return min(1.0, (centre + margin) / denom)


def _paired_flips(samples: list[dict]) -> tuple[int, int, int]:
    """Did the verdict move when the verse moved?

    The strongest evidence available, because it removes the claim entirely: for
    one claim shown against its own verse and then a different verse, a verifier
    with any discriminative power must grade the second lower. Counting a strict
    downward move isolates that, and needs no threshold to be interpreted.

    Returns (flipped, unchanged, not_pairable).
    """
    supported = {s["claim"]: s for s in samples if s["tier"] == "supported"}
    flipped = unchanged = unpaired = 0
    for s in samples:
        if s["tier"] != "wrong_verse":
            continue
        partner = supported.get(s["claim"])
        if not partner or partner.get("verdict") is None or s.get("verdict") is None:
            unpaired += 1
            continue
        if ORDER[partner["verdict"]] > ORDER[s["verdict"]]:
            flipped += 1
        else:
            unchanged += 1
    return flipped, unchanged, unpaired


def score(threshold: float = 0.10, flag_threshold: float = 0.40) -> dict:
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

    print(
        f"\nfalse SUPPORTED on a same-chapter wrong verse: "
        f"{len(false_support)}/{len(negatives)} = {false_support_rate:.0%}"
    )
    if false_support:
        for r in false_support[:3]:
            print(f"  claim: {r['claim'][:90]}")
    upper = _wilson_upper(len(false_support), len(negatives))
    print(f"  95% upper bound on the true rate: {upper:.0%}")
    if len(negatives) < 20:
        print(f"  n={len(negatives)} is too small to establish a rate below {threshold:.0%}")

    print(
        f"false flag on a correctly cited claim:        "
        f"{len(false_flag)}/{len(supported)} = {false_flag_rate:.0%}"
    )

    partial = by_tier.get("qualifier_dropped", [])
    if partial:
        caught = sum(1 for r in partial if r["verdict"] in ("PARTIAL", "UNSUPPORTED"))
        print(
            f"dropped qualifiers noticed:                   "
            f"{caught}/{len(partial)}"
        )
        if caught == 0:
            print("  it does not detect an over-broad claim at all, so enabling it buys")
            print("  wrong-verse detection only, not the broader check it was sold as")

    flipped, unchanged, unpaired = _paired_flips(samples)
    print(f"\npaired claim, two verses: verdict dropped {flipped}/{flipped + unchanged}")
    if unpaired:
        print(f"  {unpaired} sample(s) could not be paired")

    print("\nverdict")
    if not negatives:
        print("  INCONCLUSIVE — no wrong_verse tier was built")
        return {}
    # Asymmetric on purpose. The two directions cost very different amounts:
    # a false SUPPORTED suppresses the retry and lets a bad citation ship as
    # confirmed, while a false PARTIAL only adds a misleading word to the
    # response payload — it triggers no rewrite and costs no extra call, since
    # only UNSUPPORTED feeds the retry instruction. Gating both at one threshold
    # treats a cosmetic defect like a safety defect.
    if false_support_rate > threshold:
        print(f"  KEEP OFF — {false_support_rate:.0%} of wrong verses were called SUPPORTED")
        print("  that is the direction that converts a bad citation into apparent confirmation")
    elif len(negatives) < 20:
        print(f"  PROMISING BUT UNDERPOWERED — no false assurance in {len(negatives)} trials")
        print(f"  consistent with a true rate up to {upper:.0%}, so this does not yet justify an")
        print("  LLM call on every request; the number worth growing is the wrong_verse tier")
    elif false_flag_rate > flag_threshold:
        print(f"  MARGINAL — safe direction holds, but {false_flag_rate:.0%} of correct citations")
        print("  are flagged, which adds noise to the payload without buying retries")
    else:
        print(f"  ENABLE — {false_support_rate:.0%} false assurance, {false_flag_rate:.0%} false flags")
        print("  set CHARAKA_SEMANTIC_CHECK=1 and re-run the live sample")

    return {
        "false_support_rate": false_support_rate,
        "false_support_upper95": upper,
        "false_flag_rate": false_flag_rate,
        "flipped": flipped,
        "n": len(samples),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["build", "run", "score", "all", "diagnose"])
    parser.add_argument("--groups", type=int, default=6, help="chapter-local verse pairs")
    parser.add_argument("--batch", type=int, default=3)
    parser.add_argument("--threshold", type=float, default=0.10)
    parser.add_argument("--flag-threshold", type=float, default=0.40)
    parser.add_argument("--force", action="store_true", help="overwrite a scored set")
    args = parser.parse_args()

    if args.command == "diagnose":
        pacer = Pacer()
        diagnose([v for pair in select_groups(args.groups) for v in pair], pacer)
        print(f"waited {pacer.waited:.0f}s")
        return
    if args.command in ("build", "all"):
        build(args.groups, args.force)
    if args.command in ("run", "all"):
        run(args.batch)
    if args.command in ("score", "all"):
        score(args.threshold, args.flag_threshold)


if __name__ == "__main__":
    main()