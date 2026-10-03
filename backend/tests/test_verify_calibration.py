"""The calibration set has to be trustworthy before any tokens are spent on it.

These tests never call a provider. They pin the property the whole measurement
rests on: that a label follows from how a pair was constructed, not from anyone's
opinion — including the opinion of the model being tested.
"""

import json

import pytest

from app import verify_calibration as vc


class FakeLLM:
    """Stands in for ChatGroq so the builders can be exercised without tokens."""

    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.prompts = []

    def invoke(self, messages):
        self.prompts.append(getattr(messages[-1], "content", ""))
        return type("Reply", (), {"content": self.payloads.pop(0)})()


# --- the guard that makes generated labels defensible -----------------------


def test_overlap_is_high_for_a_restatement():
    verse = "Guduchi is indicated in fever and in the disorders of pitta"
    claim = "The herb guduchi is used for fever and pitta disorders"
    assert vc.overlap(claim, verse) >= 0.30


def test_overlap_is_low_for_an_unrelated_claim():
    verse = "Guduchi is indicated in fever and in the disorders of pitta"
    claim = "Castor oil is applied to the head to treat migraine"
    assert vc.overlap(claim, verse) < 0.30


def test_overlap_ignores_filler_words():
    """Stopwords must not make two unrelated claims look similar."""
    dense = "pitta vata kapha rasa guna virya vipaka prabhava"
    filler = "that this with from they their there then than which when what"
    assert vc.overlap(dense, filler) == 0.0


def test_overlap_handles_empty_input():
    assert vc.overlap("", "anything") == 0.0
    assert vc.overlap("anything", "") == 0.0


# --- generation parsing -----------------------------------------------------


def test_parse_generation_reads_the_three_fields():
    reply = FakeLLM(['{"claim": "Guduchi treats fever", "qualifier": "in fever cases", "unconditional": "Guduchi treats fever"}'])
    parsed = vc._parse_generation(reply.invoke(["x"]))
    assert parsed["claim"] == "Guduchi treats fever"
    assert parsed["qualifier"] == "in fever cases"


def test_parse_generation_ignores_a_reasoning_block():
    """gpt-oss emits reasoning before the answer; it must not break the parse."""
    body = (
        "<reasoning>The passage mentions guduchi and fever, so I will restate it."
        " This reasoning is long and contains braces {like this} too.</reasoning>"
        '{"claim": "Guduchi is used in fever", "qualifier": "", "unconditional": ""}'
    )
    parsed = vc._parse_generation(FakeLLM([body]).invoke(["x"]))
    assert parsed["claim"] == "Guduchi is used in fever"


def test_parse_generation_returns_empty_on_garbage():
    assert vc._parse_generation(FakeLLM(["no json here at all"]).invoke(["x"])) == {}


# --- title filter -----------------------------------------------------------


@pytest.mark.parametrize(
    "sentence",
    [
        "We shall now expound the chapter entitled 'The Quest for Longevity.'",
        "Thus declared the worshipful Atreya.",
        "End of the section on fever.",
        # These pass as prose and are the ones that actually matter: a
        # restatement of a chapter announcement is trivially SUPPORTED against
        # its own verse, padding the easiest tier with free passes.
        "This chapter will discuss the specific disorders of each humor.",
        "Providing exhaustive information on fever's causes, symptoms and treatment.",
    ],
)
def test_section_announcements_are_rejected(sentence):
    assert vc._TITLE_RE.match(sentence), sentence


def test_substantive_passages_are_kept():
    real = "Guduchi is indicated in fever and in the disorders of pitta, and is given with sugar."
    assert not vc._TITLE_RE.match(real)


# --- the measures the label guard actually uses ----------------------------


def test_jaccard_penalises_a_compressed_claim():
    """Why Jaccard is not the guard.

    It divides by the union, so a faithful short summary of a long passage scores
    below a near-verbatim copy of it. This is the live example: the generated
    claim "Administering sequential cleansing, enemata, and gender-specific diet"
    scored 0.073 on Jaccard against its own verse and was being dropped, while
    loose_coverage scored it 0.545 and it was plainly faithful.
    """
    verse = (
        "The man and woman should first be administered the oleation and sudation "
        "procedures, then cleansed by means of emetics and purgatives and thus "
        "gradually brought to a state of humoral concord."
    )
    compressed = "Administering sequential cleansing, enemata, and gender-specific diet"
    copied = (
        "The man and woman should be administered oleation and sudation, then "
        "cleansed by emetics and purgatives"
    )
    assert vc.overlap(compressed, verse) < vc.overlap(copied, verse)
    # The prefix measure separates the same two samples the Jaccard guard could not.
    assert vc.loose_coverage(compressed, verse) > vc.loose_coverage("The fifth tune of Jupiter", verse)


def test_loose_coverage_matches_across_morphology():
    """`administering` is not `administered` to an exact matcher, and a
    restatement of a verse that says one will always use the other."""
    verse = "The man should be administered oleation and then cleansed by emetics"
    claim = "Administering oleation precedes the cleansing by emetics"
    assert vc.coverage(claim, verse) < 0.45
    assert vc.loose_coverage(claim, verse) >= vc.MIN_RESTATEMENT_COVERAGE


def test_loose_coverage_still_rejects_an_unrelated_claim():
    verse = "Guduchi is indicated in fever and in the disorders of pitta"
    assert vc.loose_coverage("Castor oil cures migraine", verse) == 0.0


def test_threshold_sits_inside_the_observed_gap():
    """The live spread was 0.00 for the one bad sample and >=0.50 for every valid
    one, so the guard must reject the former and accept the latter."""
    assert 0.0 < vc.MIN_RESTATEMENT_COVERAGE < 0.50


# --- selection --------------------------------------------------------------


def test_selected_pairs_share_a_chapter(monkeypatch):
    """Both hard tiers depend on the two verses being genuinely confusable."""
    verses = _chapter_verses(0, 7, "fever") + _chapter_verses(4, 9, "skin")
    monkeypatch.setattr(vc, "_corpus", lambda: verses)
    monkeypatch.setattr(vc, "_VERSE_COLLECTION", verses)
    pairs = vc.select_groups(10)
    assert pairs, "expected pairs from two chapters"
    for a, b in pairs:
        assert a["chapter"] == b["chapter"]
        assert a["category"] == b["category"]
        assert a["index"] != b["index"]


def test_selected_verses_are_not_adjacent(monkeypatch):
    """Adjacent chunks continue each other's thought, so pairing them would put a
    wrong label in the key: where one passage says "first do X, then Y", the next
    chunk genuinely does support the claim."""
    verses = _chapter_verses(0, 7, "fever")
    monkeypatch.setattr(vc, "_corpus", lambda: verses)
    monkeypatch.setattr(vc, "_VERSE_COLLECTION", verses)
    for a, b in vc.select_groups(10):
        assert b["index"] - a["index"] >= 3


def test_selection_spreads_across_chapters(monkeypatch):
    """A small pilot must not return several pairs from the first chapter."""
    verses = _chapter_verses(0, 7, "fever") + _chapter_verses(4, 9, "skin")
    monkeypatch.setattr(vc, "_corpus", lambda: verses)
    monkeypatch.setattr(vc, "_VERSE_COLLECTION", verses)
    pairs = vc.select_groups(2)
    assert len({p[0]["chapter"] for p in pairs}) == 2


def test_selection_is_deterministic(monkeypatch):
    verses = [
        {"index": i, "text": "x" * 300, "chapter": 3, "category": "c"} for i in range(6)
    ]
    monkeypatch.setattr(vc, "_corpus", lambda: verses)
    monkeypatch.setattr(vc, "_VERSE_COLLECTION", verses)
    assert vc.select_groups(3) == vc.select_groups(3)


# --- construction: the invariant the measurement depends on -----------------


def _verse(index, chapter, category, text):
    return {"index": index, "text": text, "chapter": chapter, "category": category}


# Chapter-local but topically distinct passages, which is how real treatment
# chapters look: many herbs and formulations side by side. Four per chapter
# because select_groups keeps verses at least `min_gap` chunks apart.
BANK = [
    ("Guduchi is indicated in fever and in the disorders of pitta",
     "Guduchi is used in fever and in pitta disorders"),
    ("Pippali mixed with honey should be administered to a patient suffering from cough",
     "Pippali with honey is given to a patient suffering from cough"),
    ("Musta is indicated in fever and in the disorders of pitta and of the digest",
     "Musta is useful in fever and in pitta disorders of the digest"),
    ("Vasa decoction should be used to treat bleeding disorders",
     "Vasa decoction is used to treat bleeding disorders"),
    ("Lodhra decoction is applied externally to bleeding wounds",
     "Lodhra decoction is applied externally to bleeding wounds"),
    ("Sandarasa paste is prescribed in disorders of the skin",
     "Sandarasa paste is prescribed in disorders of the skin"),
    ("The juice of the plant called gokshura is used in the treatment of Kushtha",
     "Gokshura juice is used in the treatment of Kushtha"),
    ("Rasna is prescribed in disorders affecting the joints",
     "Rasna is prescribed in disorders affecting the joints"),
]

_CLAIMS = {text: claim for text, claim in BANK}


def _chapter_verses(offset, chapter, category):
    """Four verses in one chapter, one per bank entry in that block."""
    return [
        _verse(offset + i, chapter, category, BANK[offset + i][0]) for i in range(4)
    ]


def _fake_claims(pairs):
    records = []
    for a, b in pairs:
        for v in (a, b):
            records.append(
                {
                    "verse": v,
                    "claim": _CLAIMS[v["text"]],
                    "qualifier": "",
                    "unconditional": "",
                }
            )
    return records


def test_paired_tiers_share_one_claim_and_differ_only_in_verse(monkeypatch, tmp_path):
    """The core design invariant.

    If `supported` and `wrong_verse` did not carry an identical claim, a score
    difference between them could be caused by the claim rather than by the verse
    being checked, and the whole measurement would mean nothing.
    """
    verses = _chapter_verses(0, 4, "fever") + _chapter_verses(4, 8, "skin")
    monkeypatch.setattr(vc, "_corpus", lambda: verses)
    monkeypatch.setattr(vc, "_VERSE_COLLECTION", verses)
    monkeypatch.setattr(vc, "generate_claims", lambda v, p: _fake_claims(vc.select_groups(10)))
    monkeypatch.setattr(vc, "REFERENCE_SET", tmp_path / "set.json")

    samples = vc.build(10)
    tiers = {}
    for s in samples:
        tiers.setdefault(s["tier"], []).append(s)

    assert set(tiers) == {"supported", "wrong_verse"}
    assert {s["label"] for s in tiers["supported"]} == {"SUPPORTED"}
    assert {s["label"] for s in tiers["wrong_verse"]} == {"UNSUPPORTED"}

    # Same claim, different verse, same chapter.
    for s in tiers["wrong_verse"]:
        match = [t for t in tiers["supported"] if t["claim"] == s["claim"]]
        assert match, "wrong_verse must reuse a supported claim"
        assert match[0]["verse_index"] != s["verse_index"]
        assert match[0]["chapter"] == s["chapter"]


def test_qualifier_dropped_is_emitted_only_when_a_qualifier_existed(monkeypatch, tmp_path):
    verses = _chapter_verses(0, 4, "fever")
    monkeypatch.setattr(vc, "_corpus", lambda: verses)
    monkeypatch.setattr(vc, "_VERSE_COLLECTION", verses)
    monkeypatch.setattr(vc, "REFERENCE_SET", tmp_path / "set.json")

    ginger = "Ginger relieves the pain of colic in patients with pitta aggravation"
    verses[0] = _verse(0, 4, "fever", ginger)

    def claims(_v, _p):
        out = []
        for v in verses:
            if v["index"] == 0:
                out.append({
                    "verse": v,
                    "claim": "Ginger relieves the pain of colic in patients",
                    "qualifier": "in patients with",
                    "unconditional": "Ginger relieves the pain of colic",
                })
            else:
                out.append({
                    "verse": v,
                    "claim": _CLAIMS[v["text"]],
                    "qualifier": "",
                    "unconditional": "",
                })
        return out

    monkeypatch.setattr(vc, "generate_claims", claims)
    samples = vc.build(10)
    partial = [s for s in samples if s["tier"] == "qualifier_dropped"]
    assert len(partial) == 1
    assert partial[0]["label"] == "PARTIAL"
    assert partial[0]["claim"] == "Ginger relieves the pain of colic"
    # The unqualified claim is the PARTIAL sample and must not also appear as a
    # SUPPORTED one — otherwise the answer key contradicts itself.
    assert all(s["claim"] != partial[0]["claim"] for s in samples if s["tier"] == "supported")
    # The qualified form is what the SUPPORTED tier uses.
    assert any(
        s["claim"] == "Ginger relieves the pain of colic in patients"
        for s in samples
        if s["tier"] == "supported"
    )


def test_pair_is_dropped_when_the_neighbour_restates_the_same_claim(monkeypatch, tmp_path):
    """The wrong_verse tier asserts the neighbour does NOT state the claim.

    If the corpus holds a duplicate or a paraphrase, the label is wrong, and it
    is wrong on the one tier the entire measurement turns on — a verifier that
    correctly flags it would be marked wrong for being right.
    """
    duplicate = "Musta is indicated in fever and in the disorders of pitta"
    verses = [
        _verse(0, 4, "fever", "Guduchi is indicated in fever and in the disorders of pitta"),
        _verse(3, 4, "fever", duplicate),
    ]
    monkeypatch.setattr(vc, "_corpus", lambda: verses)
    monkeypatch.setattr(vc, "_VERSE_COLLECTION", verses)
    monkeypatch.setattr(vc, "REFERENCE_SET", tmp_path / "set.json")

    def claims(_v, _p):
        out = []
        for v in verses:
            if v["index"] == 0:
                out.append({
                    "verse": v,
                    "claim": "Guduchi is used in fever and in pitta disorders",
                    "qualifier": "",
                    "unconditional": "",
                })
            else:
                out.append({
                    "verse": v,
                    "claim": "Musta is used in fever and in pitta disorders",
                    "qualifier": "",
                    "unconditional": "",
                })
        return out

    monkeypatch.setattr(vc, "generate_claims", claims)
    assert vc.build(10) == []


def test_pair_is_dropped_when_the_claim_does_not_restate_its_verse(monkeypatch, tmp_path):
    verses = [
        {"index": i, "text": "Guduchi is indicated in fever " * 20, "chapter": 4, "category": "f"}
        for i in range(4)
    ]
    monkeypatch.setattr(vc, "_corpus", lambda: verses)
    monkeypatch.setattr(vc, "_VERSE_COLLECTION", verses)
    monkeypatch.setattr(vc, "REFERENCE_SET", tmp_path / "set.json")
    monkeypatch.setattr(
        vc,
        "generate_claims",
        lambda v, p: [
            {"verse": v, "claim": "castor oil cures migraine", "qualifier": "", "unconditional": ""}
            for v in verses
        ],
    )
    assert vc.build(10) == []


# --- pacing -----------------------------------------------------------------


def test_pacer_does_not_sleep_under_budget():
    pacer = vc.Pacer(tpm=1000)
    pacer.wait(100)
    pacer.wait(100)
    assert pacer.waited == 0.0


def test_pacer_waits_when_the_window_is_exhausted():
    pacer = vc.Pacer(tpm=200, window=0.2)
    pacer.wait(150)
    pacer.wait(150)  # crosses the budget; must wait out the window
    assert pacer.waited > 0.0


# --- confidence bounds and the paired metric --------------------------------


def test_wilson_bound_on_zero_is_much_worse_than_zero():
    """`0/12` reads like a clean result and is not one.

    The pilot's headline number was no false assurance in twelve trials; the
    bound is the only honest way to report it, because zero out of twelve is
    still consistent with a true rate around a quarter.
    """
    assert vc._wilson_upper(0, 12) > 0.15
    assert vc._wilson_upper(0, 12) < vc._wilson_upper(0, 4)
    assert vc._wilson_upper(0, 100) < 0.05
    assert vc._wilson_upper(3, 12) > vc._wilson_upper(0, 12)


def test_wilson_handles_an_empty_tier():
    assert vc._wilson_upper(0, 0) == 1.0


def test_paired_flips_count_a_drop_only_when_the_verdict_moves():
    samples = [
        {"tier": "supported", "claim": "a", "verdict": "SUPPORTED"},
        {"tier": "wrong_verse", "claim": "a", "verdict": "UNSUPPORTED"},  # flipped
        {"tier": "supported", "claim": "b", "verdict": "PARTIAL"},
        {"tier": "wrong_verse", "claim": "b", "verdict": "PARTIAL"},  # unchanged
        {"tier": "supported", "claim": "c", "verdict": "SUPPORTED"},
        {"tier": "wrong_verse", "claim": "c", "verdict": "UNSUPPORTED"},  # flipped
    ]
    flipped, unchanged, unpaired = vc._paired_flips(samples)
    assert (flipped, unchanged, unpaired) == (2, 1, 0)


def test_paired_flips_reports_an_unpaired_negative():
    """A wrong_verse sample with no matching supported partner cannot be scored."""
    samples = [{"tier": "wrong_verse", "claim": "z", "verdict": "UNSUPPORTED"}]
    assert vc._paired_flips(samples) == (0, 0, 1)


def test_paired_flips_ignores_missing_verdicts():
    samples = [
        {"tier": "supported", "claim": "a", "verdict": "SUPPORTED"},
        {"tier": "wrong_verse", "claim": "a"},
    ]
    assert vc._paired_flips(samples) == (0, 0, 1)


# --- gating is asymmetric on purpose ----------------------------------------


def _write_scored(tmp_path, samples):
    (tmp_path / "set.json").write_text(json.dumps({"samples": samples}), encoding="utf-8")
    return tmp_path / "set.json"


def _neg(verdict):
    return {
        "tier": "wrong_verse", "label": "UNSUPPORTED", "claim": "c", "verse_text": "v",
        "chapter": 1, "category": "x", "verse_index": 1, "verdict": verdict,
    }


def _pos(verdict):
    return {
        "tier": "supported", "label": "SUPPORTED", "claim": "c", "verse_text": "v",
        "chapter": 1, "category": "x", "verse_index": 0, "verdict": verdict,
    }


def test_a_lone_false_support_is_enough_to_keep_it_off(tmp_path, monkeypatch, capsys):
    """One confidently wrong endorsement outweighs any number of correct flags."""
    monkeypatch.setattr(vc, "REFERENCE_SET", _write_scored(tmp_path, [_neg("SUPPORTED")]))
    vc.score()
    assert "KEEP OFF" in capsys.readouterr().out


def test_underpowered_is_reported_as_underpowered_not_as_failure(tmp_path, monkeypatch, capsys):
    """A clean small sample must not be reported as a pass.

    Zero false assurances in a handful of trials is encouraging and still
    insufficient; saying so is the difference between measuring and guessing.
    """
    monkeypatch.setattr(vc, "REFERENCE_SET", _write_scored(tmp_path, [_neg("UNSUPPORTED")]))
    vc.score()
    out = capsys.readouterr().out
    assert "PROMISING BUT UNDERPOWERED" in out
    assert "KEEP OFF" not in out


def test_a_high_flag_rate_alone_does_not_keep_it_off(tmp_path, monkeypatch, capsys):
    """A flag rate over the old symmetric threshold must not veto a safety win.

    12.5% of correct citations flagged is worse than the 10% this used to gate on,
    but every one of those flags is a PARTIAL, which triggers no rewrite and
    costs no extra call. Treating it as equivalent to a false endorsement let a
    cosmetic defect block the one property that matters.
    """
    samples = [_neg("UNSUPPORTED")] * 24 + [_pos("PARTIAL")] * 5 + [_pos("SUPPORTED")] * 35
    monkeypatch.setattr(vc, "REFERENCE_SET", _write_scored(tmp_path, samples))
    metrics = vc.score()
    out = capsys.readouterr().out
    assert metrics["false_flag_rate"] == 0.125
    assert "ENABLE" in out


def test_a_very_high_flag_rate_is_reported_as_marginal(tmp_path, monkeypatch, capsys):
    """Above the flag threshold it stops being cosmetic."""
    samples = [_neg("UNSUPPORTED")] * 24 + [_pos("PARTIAL")] * 20 + [_pos("SUPPORTED")] * 4
    monkeypatch.setattr(vc, "REFERENCE_SET", _write_scored(tmp_path, samples))
    vc.score()
    assert "MARGINAL" in capsys.readouterr().out


def test_build_refuses_to_discard_scored_samples(tmp_path, monkeypatch):
    """A rebuild costs tokens and must not silently drop verdicts that cost more."""
    path = _write_scored(tmp_path, [{**_pos("SUPPORTED"), "verdict": "SUPPORTED"}])
    monkeypatch.setattr(vc, "REFERENCE_SET", path)
    with pytest.raises(SystemExit) as excinfo:
        vc.build(1)
    assert "scored sample" in str(excinfo.value)


def test_build_may_overwrite_when_forced(tmp_path, monkeypatch):
    path = _write_scored(tmp_path, [{**_pos("SUPPORTED"), "verdict": "SUPPORTED"}])
    monkeypatch.setattr(vc, "REFERENCE_SET", path)
    monkeypatch.setattr(vc, "select_groups", lambda *a, **k: [])
    monkeypatch.setattr(vc, "generate_claims", lambda *a, **k: [])
    assert vc.build(1, force=True) == []


# --- scoring ----------------------------------------------------------------


def test_score_reports_a_false_support_rate(tmp_path, monkeypatch, capsys):
    samples = [
        {"tier": "supported", "label": "SUPPORTED", "claim": "c", "verse_text": "v",
         "chapter": 1, "category": "x", "verse_index": 0, "verdict": "SUPPORTED"},
        {"tier": "wrong_verse", "label": "UNSUPPORTED", "claim": "c", "verse_text": "v",
         "chapter": 1, "category": "x", "verse_index": 1, "verdict": "SUPPORTED"},
    ]
    monkeypatch.setattr(vc, "REFERENCE_SET", tmp_path / "set.json")
    (tmp_path / "set.json").write_text(json.dumps({"samples": samples}), encoding="utf-8")

    metrics = vc.score(threshold=0.10)
    out = capsys.readouterr().out
    assert metrics["false_support_rate"] == 1.0
    assert metrics["false_flag_rate"] == 0.0
    assert "KEEP OFF" in out