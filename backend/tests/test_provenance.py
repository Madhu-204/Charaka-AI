"""Provenance tests: non-corpus context must never read as classical Charaka.

The retrieval layer is corpus-only, but three other things reach the synthesis
prompt: modern pharmacology flags, a modern botanical alias list, and
hand-authored legacy cautions. If those are passed to the model without a
provenance label, it presents a 20th-century drug-interaction warning as though
Charaka said it, with a chapter citation attached.

These assert the labels exist, that the prompt instructs honest attribution,
and that the alias list does not present editorial names as classical ones.
"""

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import pytest  # noqa: E402

from app.nodes.synthesis import (  # noqa: E402
    SYSTEM_PROMPT,
    _build_context,
    _herb_alias_block,
)


def verse():
    return {
        "verse_id": "v1",
        "text": "Verse 1: classical text here.",
        "meta": {
            "sthana": "chikitsasthana",
            "chapter": 1,
            "traditional_condition": "Jwara",
            "category_tag": "fever_acute",
        },
    }


def state(**over):
    s = {
        "confidence": "high",
        "safety_flags": [],
        "verification_notes": [],
        "source_disagreements": [],
        "user_docs": [],
        "herbs_found": [],
        "dosha_profile": None,
    }
    s.update(over)
    return s


def build(st=None, herbs=None, alias="none"):
    return _build_context(verse(), [], st or state(), herbs or [], alias, [])


class TestModernSafetyFlagLabelling:
    def test_flags_section_declares_non_corpus_origin(self):
        ctx = build(state(safety_flags=["arka: TOXIC - cardiac glycosides"]))
        assert "MODERN SAFETY FLAGS" in ctx
        assert "NOT Charaka Samhita" in ctx

    def test_flag_text_survives_labelling(self):
        flag = "guggulu: interacts with: warfarin"
        ctx = build(state(safety_flags=[flag]))
        assert flag in ctx

    def test_no_bare_unlabelled_safety_line(self):
        """The old header was exactly 'Safety flags:' with no provenance."""
        ctx = build(state(safety_flags=["x: y"]))
        assert "Safety flags:" not in ctx

    def test_prompt_forbids_citing_a_chapter_for_flags(self):
        low = SYSTEM_PROMPT.lower()
        assert "never present them as a classical instruction" in low
        assert "never as a classical claim" not in low


class TestHerbAliasLabelling:
    def test_alias_section_declares_non_corpus_origin(self):
        ctx = build(state(), ["ginger"], "- ginger (also called: shunthi)")
        assert "NOT from the classical" in ctx
        assert "modern botanical naming reference" in ctx

    def test_alias_equivalence_not_asserted_as_classical(self):
        """The old prompt told the model to 'explain these equivalences'."""
        low = SYSTEM_PROMPT.lower()
        assert "classical texts may use different names" not in low

    def test_prompt_requires_honest_attribution(self):
        low = SYSTEM_PROMPT.lower()
        assert "modern botanical naming aid" in low
        assert "unless the verse itself shows it" in low

    def test_self_referential_alias_dropped(self):
        """trikatu lists only itself; rendering 'also called: trikatu' is noise."""
        out = _herb_alias_block(["trikatu"])
        assert out == "- trikatu"

    def test_real_aliases_preserved(self):
        out = _herb_alias_block(["ginger"])
        assert "shunthi" in out
        assert "ginger" in out

    def test_case_insensitive_self_reference_dropped(self):
        """herbs.json lists 'ginger' among its own ginger aliases."""
        out = _herb_alias_block(["ginger"])
        assert out == "- ginger (also called: dry ginger, green ginger, shunthi, sunthi, ardraka)"


class TestHandAuthoredCautions:
    def test_legacy_contraindication_declares_no_source(self):
        from app.nodes.safety import LEGACY_CONTRAINDICATIONS

        for herb, caution in LEGACY_CONTRAINDICATIONS.items():
            assert "no cited source" in caution, f"{herb} legacy caution hides its origin"

    def test_uncovered_herb_declares_absence_of_data(self):
        """A herb with no monograph falls through to an app-authored caution.

        Asserted at check_safety, not _build_flags: the uncovered string is built
        at the call site, and _build_flags("h", {}) correctly returns [] because
        there is no data to report. Probing SAFETY_DB for a genuinely uncovered
        herb is not possible either, since every herb in herbs.json now has a
        monograph, so the branch is forced with a patched herb set.
        """
        from app.nodes import safety as safety_mod

        herb = "some_unknown_herb"
        verse_id = "v-uncovered"
        original_mentions = safety_mod.herbs_by_verse
        original_call = safety_mod._call_mcp_tool
        safety_mod.herbs_by_verse = {verse_id: [herb]}
        safety_mod._call_mcp_tool = lambda name: (None, "json_fallback")
        try:
            out = safety_mod.check_safety(
                {
                    "resolved_chapter": {"verse_id": verse_id, "text": ""},
                    "trace": [],
                }
            )
        finally:
            safety_mod.herbs_by_verse = original_mentions
            safety_mod._call_mcp_tool = original_call

        assert out["herbs_found"] == [herb]
        assert out["safety_sources"] == {herb: "uncovered"}
        assert "no safety monograph on file" in out["safety_flags"][0]
        assert "not a classical statement" in out["safety_flags"][0]


class TestCorpusLabelUnaffected:
    def test_primary_verse_still_unlabelled_as_corpus(self):
        """Provenance work must not clutter the actual classical citation."""
        ctx = build()
        assert "PRIMARY CONTEXT" in ctx
        assert "MODERN SAFETY FLAGS" in ctx

    def test_user_documents_still_labelled_non_corpus(self):
        st = state(user_docs=[{"doc": "notes.txt", "score": 0.9, "text": "content"}])
        ctx = build(st)
        assert "NOT the classical corpus" in ctx
        assert "[U1]" in ctx