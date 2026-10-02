"""Corpus-coverage gate: refuse questions about herbs the text never discusses.

herbs.json is keyed by Sanskrit/modern names while the corpus is an English
translation naming plants in common English, so 22 herbs in herbs.json occur
under no name and no alias. Retrieval for those returned a weak, topically
wrong verse at low confidence -- an answer that reads as grounded but is not.

The gate reads the generated herb_terminology.json rather than a hand list, so
a corpus rebuild that starts discussing a herb lifts the refusal automatically.
"""

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.nodes.scope import (  # noqa: E402
    ABSENT_HERBS,
    HERB_NAMES,
    check_corpus_coverage,
    check_scope,
)

TERMINOLOGY = BACKEND / "reference" / "herb_terminology.json"


class TestCoverageGateRefuses:
    def test_refuses_absent_herb(self):
        out = check_corpus_coverage({"query": "What are the benefits of bibhitaki?", "trace": []})
        assert out["is_out_of_scope"] is True
        assert out["scope_category"] == "not_in_corpus"

    def test_refusal_asserts_no_corpus_content(self):
        """The refusal must not smuggle in a claim about the herb itself."""
        out = check_corpus_coverage({"query": "explain rasna", "trace": []})
        answer = out["final_answer"].lower()
        assert "not discussed" in answer
        assert "no verse to ground" in answer

    def test_refusal_points_at_translation_not_the_plant(self):
        """Blame belongs to the corpus's scope, never to the herb."""
        answer = check_corpus_coverage({"query": "priyangu", "trace": []})["final_answer"].lower()
        assert "translation" in answer
        assert "not a judgement about the plant" in answer

    def test_multiple_absent_herbs_refuse(self):
        for h in ("bibhitaki", "rasna", "priyangu", "eranda", "surasa"):
            assert check_corpus_coverage(
                {"query": f"{h} benefits", "trace": []}
            )["is_out_of_scope"] is True, h


class TestCoverageGateAllows:
    def test_discussed_herb_allowed(self):
        out = check_corpus_coverage({"query": "benefits of ginger for fever", "trace": []})
        assert out["is_out_of_scope"] is False

    def test_corpus_english_name_allowed(self):
        """asparagus is how the corpus names shatavari."""
        out = check_corpus_coverage({"query": "asparagus benefits", "trace": []})
        assert out["is_out_of_scope"] is False

    def test_non_herb_question_allowed(self):
        out = check_corpus_coverage({"query": "what is a hot remedy for cough?", "trace": []})
        assert out["is_out_of_scope"] is False

    def test_absent_plus_discussed_stays_in_scope(self):
        """Partial coverage is still coverage; refusing would over-refuse."""
        out = check_corpus_coverage(
            {"query": "bibhitaki and ginger for cough", "trace": []}
        )
        assert out["is_out_of_scope"] is False

    def test_every_discussed_herb_allowed(self):
        discussed = sorted(HERB_NAMES - ABSENT_HERBS)
        assert len(discussed) >= 60
        bad = [
            h for h in discussed
            if check_corpus_coverage({"query": f"benefits of {h}", "trace": []})["is_out_of_scope"]
        ]
        assert bad == [], f"discussed herbs wrongly refused: {bad}"


class TestCoverageIntegratedWithScope:
    def test_scope_surfaces_coverage_refusal(self):
        out = check_scope({"query": "Tell me about rasna", "trace": []})
        assert out["is_out_of_scope"] is True
        assert out["scope_category"] == "not_in_corpus"
        assert out["final_answer"]

    def test_medication_still_takes_priority(self):
        """A medication refusal must not be reported as a coverage gap."""
        out = check_scope({"query": "Should I stop my diabetes tablets?", "trace": []})
        assert out["scope_category"] == "medication"

    def test_dosage_still_takes_priority(self):
        out = check_scope({"query": "how much turmeric for cough?", "trace": []})
        assert out["scope_category"] == "dosage"

    def test_offdomain_still_takes_priority(self):
        out = check_scope({"query": "quantum computing scheduling", "trace": []})
        assert out["scope_category"] == "offdomain"

    def test_trace_records_the_reason(self):
        out = check_scope({"query": "explain priyangu", "trace": []})
        assert any("not_in_corpus" in t for t in out["trace"])


class TestCoverageIsDataDriven:
    def test_absent_set_comes_from_generated_file(self):
        data = json.load(open(TERMINOLOGY, encoding="utf-8"))
        expected = {
            n for n, e in data["herbs"].items() if e["status"] == "not_in_corpus"
        }
        assert ABSENT_HERBS == expected

    def test_no_hand_list_in_source(self):
        """The gate must not hardcode herb names; data drives it."""
        src = (BACKEND / "app" / "nodes" / "scope.py").read_text(encoding="utf-8")
        for h in ("bibhitaki", "rasna", "priyangu", "shatavari"):
            assert f'"{h}"' not in src, f"{h} is hardcoded; the gate must read the table"