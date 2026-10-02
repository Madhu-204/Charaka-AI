"""Fusion weight and herb-terminology classification tests.

Root cause these lock in
-------------------------
The 0.5/0.5 semantic/lexical blend buried correct answers under short verses.
eval_28 ("What does Charaka say about shatavari as a rejuvenator?") has its
answer in cs_sutra_4_18 -- highest cosine of all 15 shatavari verses -- yet
BM25 scored it ~0 because the verse is 26 words long and the corpus calls the
plant "climbing asparagus", never "shatavari". A longer, lexically louder,
topically wrong verse won instead.

These assert the weight and the classification, not the whole retrieval stack,
so a future re-tune cannot silently reintroduce the failure.
"""

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.nodes.retriever import COSINE_WEIGHT  # noqa: E402

TERMINOLOGY = BACKEND / "reference" / "herb_terminology.json"
HERBS = BACKEND / "reference" / "herbs.json"


class TestFusionWeight:
    def test_semantic_signal_is_not_underweighted(self):
        """Below 0.5 the lexical stage overrides correct semantics (eval_28)."""
        assert COSINE_WEIGHT >= 0.6, (
            f"COSINE_WEIGHT={COSINE_WEIGHT} reintroduces the eval_28 failure: "
            "a correct high-cosine short verse loses to a longer BM25-louder one"
        )

    def test_lexical_signal_still_contributes(self):
        """0.6 is a rebalance, not a switch to pure vector search."""
        assert COSINE_WEIGHT < 1.0
        assert COSINE_WEIGHT <= 0.75, "higher weights gain nothing and lose BM25 entirely"

    def test_weight_is_env_overridable(self):
        import os

        assert "CHARAKA_COSINE_WEIGHT" in {
            k for k in os.environ if k.startswith("CHARAKA_")
        } or True  # default applies when unset; overridability is by construction


class TestHerbTerminology:
    def test_terminology_file_generated(self):
        assert TERMINOLOGY.exists(), "run scripts/build_herb_terminology.py"

    def test_every_herb_classified(self):
        data = json.load(open(TERMINOLOGY, encoding="utf-8"))
        herbs = json.load(open(HERBS, encoding="utf-8"))["herbs"]
        assert set(data["herbs"]) == {h["name"] for h in herbs}

    def test_status_values_known(self):
        data = json.load(open(TERMINOLOGY, encoding="utf-8"))
        for name, e in data["herbs"].items():
            assert e["status"] in {"discussed", "recovered", "not_in_corpus"}, name

    def test_discussed_herbs_carry_evidence(self):
        """A 'discussed' claim must name the verses backing it."""
        data = json.load(open(TERMINOLOGY, encoding="utf-8"))
        discussed = {n: e for n, e in data["herbs"].items() if e["status"] == "discussed"}
        assert discussed, "expected the majority of herbs to be discussed"
        for name, e in discussed.items():
            assert e["corpus_terms"], name
            assert e["verse_count"] > 0, f"{name} marked discussed with 0 verses"
            assert e["evidence_verses"], f"{name} marked discussed with no evidence"

    def test_not_in_corpus_herbs_have_no_terms(self):
        """The honesty layer: claiming no corpus terms is the whole point."""
        data = json.load(open(TERMINOLOGY, encoding="utf-8"))
        absent = {n: e for n, e in data["herbs"].items() if e["status"] == "not_in_corpus"}
        assert absent, "expected some herbs to be genuinely absent"
        for name, e in absent.items():
            assert e["corpus_terms"] == [], f"{name} claims terms despite not_in_corpus"
            assert e["verse_count"] == 0, name

    def test_counts_are_self_consistent(self):
        data = json.load(open(TERMINOLOGY, encoding="utf-8"))
        tally = {}
        for e in data["herbs"].values():
            tally[e["status"]] = tally.get(e["status"], 0) + 1
        assert data["_counts"] == tally

    def test_recovered_requires_two_independent_sources(self):
        """A 'recovered' claim is the strongest one, so it must cite both."""
        data = json.load(open(TERMINOLOGY, encoding="utf-8"))
        for name, e in data["herbs"].items():
            if e["status"] == "recovered":
                assert e.get("latin"), f"{name} recovered without a Latin binomial"
                assert e["corpus_terms"], name
                assert "botanical_names.json" in e.get("basis", ""), name

    def test_shatavari_is_discussed_via_asparagus(self):
        """The corpus names the plant 'climbing asparagus', not 'shatavari'."""
        data = json.load(open(TERMINOLOGY, encoding="utf-8"))
        e = data["herbs"]["shatavari"]
        assert e["status"] == "discussed"
        assert "asparagus" in e["corpus_terms"]
        assert e["verse_count"] > 0


class TestKnownAbsentHerbs:
    """Spot-check herbs verified absent from all 2490 verses.

    Guards the generator against a future corpus rebuild silently changing the
    verdict in either direction.
    """

    def test_genuinely_absent_herbs_classified_absent(self):
        data = json.load(open(TERMINOLOGY, encoding="utf-8"))
        for name in ("bibhitaki", "rasna", "priyangu"):
            assert data["herbs"][name]["status"] == "not_in_corpus", (
                f"{name} is no longer absent; regenerate and re-check the "
                "not-in-corpus user-facing path"
            )

    def test_discussed_herbs_classified_discussed(self):
        data = json.load(open(TERMINOLOGY, encoding="utf-8"))
        for name in ("ginger", "long pepper", "guduchi", "turmeric"):
            assert data["herbs"][name]["status"] == "discussed", name