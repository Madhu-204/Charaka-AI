"""The semantic verifier: does the cited verse actually state the claim?

The structural citation check (`grounding.py`) cannot catch a well-formed
citation to a verse that does not say what was claimed. These tests pin the
verifier's contract, and the contract is deliberately narrow: it must never turn
a provider failure into a request failure, and it must never report a claim as
supported unless the model actually said so.

`_cited_claims` and `_parse` are pure, so they are tested directly. The node
itself is exercised with a stubbed LLM and with the check disabled, which is the
default and therefore the path that must cost nothing.
"""

import pytest

from app.nodes import semantic_check as sc


class _Msg:
    def __init__(self, content):
        self.content = content


class _StubLLM:
    def __init__(self, reply):
        self.reply = reply
        self.seen = None

    def invoke(self, messages):
        self.seen = messages
        return _Msg(self.reply)


VERSE = {"verse_id": "cs_x_1_1-2", "text": "Pippali taken with honey alleviates colic."}
OTHER = {"verse_id": "cs_x_9_4", "text": "Musta is said to be bitter and cooling."}


def _cited_claims(answer, retrieved, limit=sc.MAX_CLAIMS):
    return sc._cited_claims(answer, retrieved, limit)


# --- claim extraction -------------------------------------------------------


def test_pairs_each_cited_sentence_with_the_verse_it_names():
    answer = "Pippali relieves colic [1]. Musta is bitter and cooling [2]."
    pairs = _cited_claims(answer, [VERSE, OTHER], limit=5)
    assert [p[1] for p in pairs] == [1, 2]
    assert "colic" in pairs[0][0]
    # The marker itself must be stripped from the claim before it is judged.
    assert "[" not in pairs[0][0]


def test_ignores_markers_outside_the_retrieved_range():
    answer = "Nothing was said about this [7]."
    assert _cited_claims(answer, [VERSE, OTHER], limit=5) == []


def test_distinct_claims_citing_one_verse_are_all_checked():
    """Two claims against [1] are two things that can independently be wrong.

    Deduplicating per verse would check only the first, which is precisely the
    wrong one to skip: a safe-sounding summary followed by an unsupported
    pregnancy or dosing claim is the failure mode worth catching.
    """
    answer = "Pippali relieves colic [1]. It is safe in pregnancy [1]."
    pairs = _cited_claims(answer, [VERSE], limit=5)
    assert [p[0] for p in pairs] == ["Pippali relieves colic.", "It is safe in pregnancy."]


def test_only_the_first_marker_in_a_sentence_is_used():
    answer = "Colic is relieved [1] and bitter [2]."
    assert [p[1] for p in _cited_claims(answer, [VERSE, OTHER], limit=5)] == [1]


def test_respects_the_claim_limit():
    answer = " ".join(f"Claim number {i} [1]." for i in range(10))
    assert len(_cited_claims(answer, [VERSE], limit=3)) == 3


def test_skips_a_citation_whose_verse_has_no_text():
    pairs = _cited_claims("A claim [1].", [{"verse_id": "v", "text": "   "}], limit=5)
    assert pairs == []


# --- verdict parsing --------------------------------------------------------


def test_parses_one_verdict_per_claim():
    reply = "CLAIM 1: SUPPORTED\nCLAIM 2: UNSUPPORTED\nCLAIM 3: PARTIAL"
    assert sc._parse(reply, 3) == {1: "SUPPORTED", 2: "UNSUPPORTED", 3: "PARTIAL"}


def test_an_unparseable_reply_never_reads_as_supported():
    """A garbled verifier reply must not become a false assurance.

    Defaulting an absent verdict to SUPPORTED would mean a truncated or refused
    response silently certifies claims nobody checked. PARTIAL is the honest
    default: it stays visible as unverified.
    """
    assert sc._parse("I cannot help with that.", 2) == {1: "PARTIAL", 2: "PARTIAL"}
    assert sc._parse("", 1) == {1: "PARTIAL"}


def test_ignores_verdicts_for_claims_that_do_not_exist():
    reply = "CLAIM 1: SUPPORTED\nCLAIM 9: UNSUPPORTED"
    assert sc._parse(reply, 1) == {1: "SUPPORTED"}


def test_tolerates_reasoning_text_around_the_verdicts():
    reply = "Let me consider each claim.\n\nCLAIM 1: PARTIAL\n\nThat is my assessment."
    assert sc._parse(reply, 1) == {1: "PARTIAL"}


# --- the node ---------------------------------------------------------------


def _state(**over):
    base = {
        "final_answer": "Pippali relieves colic [1].",
        "retrieved": [VERSE],
        "trace": [],
    }
    base.update(over)
    return base


def test_disabled_by_default_costs_nothing(monkeypatch):
    """The default path must not touch the provider at all."""
    monkeypatch.delenv("CHARAKA_SEMANTIC_CHECK", raising=False)
    monkeypatch.setattr(sc, "_enabled", lambda: False)

    def _boom(*a, **k):
        raise AssertionError("verifier must not call the LLM when disabled")

    monkeypatch.setattr(sc, "ChatGroq", _boom)
    out = sc.semantic_check(_state())
    assert out["grounding_semantic"] == []
    assert any("skipped" in step for step in out["trace"])


def test_records_a_verdict_per_cited_claim(monkeypatch):
    monkeypatch.setattr(sc, "_enabled", lambda: True)
    stub = _StubLLM("CLAIM 1: SUPPORTED")
    monkeypatch.setattr(sc, "ChatGroq", lambda **k: stub)
    out = sc.semantic_check(_state())
    assert out["grounding_semantic"] == [
        {"claim": "Pippali relieves colic.", "marker": 1, "verdict": "SUPPORTED", "verse_id": "cs_x_1_1-2"}
    ]
    assert "grounding_retry_instruction" not in out


def test_unsupported_claim_requests_a_rewrite(monkeypatch):
    monkeypatch.setattr(sc, "_enabled", lambda: True)
    monkeypatch.setattr(sc, "ChatGroq", lambda **k: _StubLLM("CLAIM 1: UNSUPPORTED"))
    out = sc.semantic_check(_state())
    assert out["grounding_semantic"][0]["verdict"] == "UNSUPPORTED"
    instruction = out["grounding_retry_instruction"]
    assert instruction
    # It must quote the offending claim and name the verse it was wrongly tied to.
    assert "Pippali relieves colic" in instruction
    assert "[1]" in instruction


def test_skips_when_a_citation_retry_is_already_pending(monkeypatch):
    """A pending structural retry addresses the more fundamental fault.

    Spending a verification call on a draft that is about to be discarded buys
    nothing, and the rewrite is never re-verified because the attempt budget is
    spent by then.
    """
    monkeypatch.setattr(sc, "_enabled", lambda: True)

    def _boom(*a, **k):
        raise AssertionError("must not verify a draft that is about to be rewritten")

    monkeypatch.setattr(sc, "ChatGroq", _boom)
    out = sc.semantic_check(_state(grounding_retry_instruction="fix your citations"))
    assert out["grounding_semantic"] == []
    assert any("retry already pending" in step for step in out["trace"])


def test_skips_the_rewrite_so_the_cost_stays_at_one_call(monkeypatch):
    """Only the first draft is verified.

    A flag on the first draft triggers a rewrite, and that rewrite is a response
    to the criticism rather than an independently checked answer. Verifying it
    too would double the call count on exactly the requests that are already the
    most expensive.
    """
    monkeypatch.setattr(sc, "_enabled", lambda: True)

    def _boom(*a, **k):
        raise AssertionError("must not re-verify a rewritten draft")

    monkeypatch.setattr(sc, "ChatGroq", _boom)
    out = sc.semantic_check(_state(synthesis_attempts=2))
    assert out["grounding_semantic"] == []
    assert any("first draft" in step for step in out["trace"])


@pytest.mark.parametrize(
    "over",
    [
        pytest.param({"final_answer": ""}, id="empty_answer"),
        pytest.param({"retrieved": []}, id="nothing_retrieved"),
        pytest.param({"final_answer": "No citation here at all."}, id="no_cited_claims"),
    ],
)
def test_nothing_to_verify_is_not_an_error(monkeypatch, over):
    monkeypatch.setattr(sc, "_enabled", lambda: True)

    def _boom(*a, **k):
        raise AssertionError("must not call the LLM with nothing to verify")

    monkeypatch.setattr(sc, "ChatGroq", _boom)
    out = sc.semantic_check(_state(**over))
    assert out["grounding_semantic"] == []


def test_provider_failure_degrades_to_unverified(monkeypatch):
    """The answer is already drafted and checked; losing the verifier must not
    fail the request. It must also not claim the claims were verified."""
    monkeypatch.setattr(sc, "_enabled", lambda: True)

    class _RateLimited:
        def __init__(self, **k):
            pass

        def invoke(self, messages):
            raise RuntimeError("rate limit exceeded")

    monkeypatch.setattr(sc, "ChatGroq", _RateLimited)
    out = sc.semantic_check(_state())
    assert out["grounding_semantic"] == []
    assert "grounding_retry_instruction" not in out
    assert any("unavailable" in step for step in out["trace"])


def test_prompt_asks_for_verbatim_verdict_lines(monkeypatch):
    """The parser is strict, so the prompt has to elicit exactly that shape."""
    monkeypatch.setattr(sc, "_enabled", lambda: True)
    stub = _StubLLM("CLAIM 1: SUPPORTED")
    monkeypatch.setattr(sc, "ChatGroq", lambda **k: stub)
    sc.semantic_check(_state())
    system, human = stub.seen
    assert "CLAIM <n>: SUPPORTED" in system.content
    assert "do not explain" in system.content.lower()
    # The verse text must be in the prompt, or the model is judging blind.
    assert VERSE["text"] in human.content