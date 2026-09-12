from typing import TypedDict, List, Optional


class AgentState(TypedDict, total=False):
    query: str
    history: List[dict]
    followup_context: Optional[str]
    dosha_profile: Optional[str]
    is_emergency: bool
    emergency_reason: Optional[str]
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
    is_clarification: bool
    clarification: Optional[str]