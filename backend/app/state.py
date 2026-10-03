from typing import TypedDict, List, Optional


class AgentState(TypedDict, total=False):
    query: str
    history: List[dict]
    followup_context: Optional[str]
    dosha_profile: Optional[str]
    is_emergency: bool
    emergency_reason: Optional[str]
    is_out_of_scope: bool
    scope_category: Optional[str]
    dosha: Optional[str]
    dosha_scores: Optional[dict]
    expanded_query: str
    canonical_term: Optional[str]
    metadata_filter: Optional[dict]
    tool_decision: Optional[str]
    retrieved: List[dict]
    resolved_chapter: Optional[dict]
    herbs_found: List[str]
    safety_flags: List[str]
    safety_sources: Optional[dict]
    verification_notes: List[str]
    source_disagreements: List[str]
    confidence_score: Optional[float]
    confidence: str
    trace: List[str]
    final_answer: str
    grounding_score: Optional[float]
    grounding_notes: List[str]
    grounding_cited: List[int]
    # Set by the grounding node when the draft answer failed in a way a second
    # pass could plausibly fix (no usable citation, or invented out-of-range
    # ones). The synthesis node reads it as a correction instruction and the graph
    # uses it as the retry signal. Empty/absent means "ship this answer".
    grounding_retry_instruction: Optional[str]
    # How many times synthesis has run for this request. Guards the retry edge so
    # a persistently ungroundable answer cannot loop.
    synthesis_attempts: int
    is_clarification: bool
    clarification: Optional[str]
    # Set by the router when the question is a greeting/capability question that
    # no verse can answer, so the graph can skip retrieval entirely.
    direct_answer: bool
    # Set once the direct_answer node has run. Distinct from `direct_answer`
    # (the router's request) so build_response can tell a terminal conversational
    # reply apart from a grounded answer with no chapter.
    is_direct_answer: bool
    # Set by the router when the question names nothing concrete to retrieve
    # against. Consumed by the clarify node, which turns it into a question.
    needs_clarification: bool
    clarification_hint: Optional[str]
    attribution: List[dict]
    lang: Optional[str]
    doc_session: Optional[str]
    user_docs: List[dict]
    used_documents: bool