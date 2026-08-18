from typing import TypedDict, List, Optional


class AgentState(TypedDict, total=False):
    query: str
    followup_context: Optional[str]
    is_emergency: bool
    emergency_reason: Optional[str]
    expanded_query: str
    canonical_term: Optional[str]
    retrieved: List[dict]
    resolved_chapter: Optional[dict]
    herbs_found: List[str]
    safety_flags: List[str]
    confidence: str
    final_answer: str