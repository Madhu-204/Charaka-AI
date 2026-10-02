"""Tests for the synthesis context budget.

Observed failure: Groq returned "Limit 8000, Requested 8321" (413) and
synthesis raised SynthesisUnavailable, so the user got a 503 instead of an
answer. Nothing bounded the prompt.

These verify the budget holds, and - more importantly - that trimming sacrifices
only redundant context. Safety warnings must never be dropped to save tokens.
"""

import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.nodes.synthesis import (  # noqa: E402
    MAX_CONTEXT_TOKENS,
    SYSTEM_PROMPT,
    _approx_tokens,
    _build_context,
    _truncate_middle,
)


def verse(i, chars=350):
    return {
        "verse_id": f"v{i}",
        "text": f"Verse {i}: " + ("classical text " * (chars // 15)),
        "meta": {
            "sthana": "chikitsasthana",
            "chapter": i,
            "traditional_condition": "Jwara",
            "category_tag": "fever_acute",
        },
    }


def state(**over):
    s = {
        "resolved_chapter": verse(1),
        "retrieved": [verse(i) for i in range(1, 6)],
        "confidence": "high",
        "herbs_found": [],
        "safety_flags": [],
        "verification_notes": [],
        "source_disagreements": [],
        "user_docs": [],
        "history": [],
        "query": "test",
    }
    s.update(over)
    return s


class TestHelpers:
    def test_approx_tokens_scales(self):
        assert _approx_tokens("x" * 400) == 100
        assert _approx_tokens("") == 1

    def test_truncate_middle_keeps_tail(self):
        """Verse citations sit at the end, so the tail must survive."""
        out = _truncate_middle("HEAD" + "y" * 500 + "TAIL", 100)
        assert len(out) <= 160  # includes the truncation marker
        assert "TAIL" in out

    def test_truncate_middle_noop_when_short(self):
        assert _truncate_middle("short", 900) == "short"

    def test_truncate_middle_marks_the_cut(self):
        assert "truncated" in _truncate_middle("x" * 500, 100)


class TestBudgetHolds:
    def test_large_retrieved_set_stays_under_limit(self):
        """The crash case: ~40 blocks overflowed the 8000 TPM ceiling."""
        st = state(retrieved=[verse(i) for i in range(1, 45)])
        ctx = _build_context(st["resolved_chapter"], st["retrieved"][:12], st, [], "none", [])
        total = _approx_tokens(SYSTEM_PROMPT) + _approx_tokens(ctx)
        assert total <= MAX_CONTEXT_TOKENS

    def test_many_uploaded_docs_bounded(self):
        docs = [{"doc": f"f{i}.txt", "score": 0.9, "text": "z" * 6000} for i in range(20)]
        st = state(user_docs=docs)
        ctx = _build_context(st["resolved_chapter"], [], st, [], "none", [])
        total = _approx_tokens(SYSTEM_PROMPT) + _approx_tokens(ctx)
        assert total <= MAX_CONTEXT_TOKENS

    def test_long_history_bounded(self):
        hist = [{"role": "user", "content": "w" * 3000} for _ in range(40)]
        st = state(history=hist)
        ctx = _build_context(st["resolved_chapter"], [], st, [], "none", hist[-6:])
        total = _approx_tokens(SYSTEM_PROMPT) + _approx_tokens(ctx)
        assert total <= MAX_CONTEXT_TOKENS

    def test_normal_query_is_well_under_limit(self):
        """The common case must not be trimmed at all."""
        st = state()
        ctx = _build_context(st["resolved_chapter"], st["retrieved"][:3], st, [], "none", [])
        total = _approx_tokens(SYSTEM_PROMPT) + _approx_tokens(ctx)
        assert total < MAX_CONTEXT_TOKENS / 2


class TestSafetyNeverTrimmed:
    """Losing a warning to save a token makes the answer worse, not shorter."""

    def test_safety_flags_always_present(self):
        flag = "arka: TOXIC - cardiac glycosides, heart block risk"
        st = state(safety_flags=[flag])
        ctx = _build_context(st["resolved_chapter"], [], st, [], "none", [])
        assert flag in ctx

    def test_safety_flags_survive_max_context_pressure(self):
        flag = "arka: TOXIC - cardiac glycosides"
        st = state(safety_flags=[flag], retrieved=[verse(i) for i in range(1, 45)])
        # Simulate the fallback loop: shed all additional blocks.
        ctx = _build_context(st["resolved_chapter"], [], st, [], "none", [])
        assert flag in ctx

    def test_verification_notes_always_present(self):
        note = "Disclose that arka is the closest-match species"
        st = state(verification_notes=[note])
        ctx = _build_context(st["resolved_chapter"], [], st, [], "none", [])
        assert note in ctx

    def test_source_disagreements_always_present(self):
        d = "classical texts describe use, but modern sources flag a strong caution"
        st = state(source_disagreements=[d])
        ctx = _build_context(st["resolved_chapter"], [], st, [], "none", [])
        assert d in ctx

    def test_primary_verse_always_present(self):
        st = state(retrieved=[verse(i) for i in range(1, 45)])
        ctx = _build_context(st["resolved_chapter"], [], st, [], "none", [])
        assert "PRIMARY CONTEXT" in ctx
        assert st["resolved_chapter"]["verse_id"] in ctx or "Verse 1" in ctx


class TestContextStructure:
    def test_single_source_of_truth_no_duplication(self):
        """The normal path and the fallback must not append sections twice."""
        st = state(safety_flags=["flag one"], verification_notes=["note one"])
        ctx = _build_context(st["resolved_chapter"], st["retrieved"][:3], st, [], "none", [])
        assert ctx.count("PRIMARY CONTEXT") == 1
        assert ctx.count("Safety flags:") == 1
        assert ctx.count("VERIFICATION NOTES") == 1

    def test_documents_labelled_as_non_corpus(self):
        st = state(user_docs=[{"doc": "notes.txt", "score": 0.9, "text": "some content"}])
        ctx = _build_context(st["resolved_chapter"], [], st, [], "none", [])
        assert "NOT the classical corpus" in ctx
        assert "[U1]" in ctx

    def test_empty_additional_says_none(self):
        st = state()
        ctx = _build_context(st["resolved_chapter"], [], st, [], "none", [])
        assert "ADDITIONAL CONTEXT:\nnone" in ctx

    def test_confidence_always_present(self):
        st = state(confidence="low")
        ctx = _build_context(st["resolved_chapter"], [], st, [], "none", [])
        assert "Confidence: low" in ctx