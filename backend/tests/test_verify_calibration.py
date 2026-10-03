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
    ],
)
def test_section_announcements_are_rejected(sentence):
    assert vc._TITLE_RE.match(sentence), sentence


def test_substantive_passages_are_kept():
    real = "Guduchi is indicated in fever and in the disorders of pitta, and is given with sugar."
    assert not vc._TITLE_RE.match(real)


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


def test_build_drops_samples_whose_restatement_is_too_loose(monkeypatch, tmp_path):
    """A claim unrelated to its verse must never enter as a SUPPORTED label."""
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