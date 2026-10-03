from langgraph.graph import StateGraph, END

from app.state import AgentState
from app.nodes.emergency import check_emergency
from app.nodes.scope import check_scope
from app.nodes.dosha import tag_dosha
from app.nodes.query_expansion import expand_query
from app.nodes.retriever import retrieve
from app.nodes.safety import check_safety
from app.nodes.synthesis import synthesize
from app.nodes.grounding import grounding
from app.nodes.semantic_check import semantic_check
from app.nodes.attribution import attribution
from app.nodes.clarify import clarify
from app.nodes.direct import direct_answer
from app.nodes.tool_router import route_tools

# One retry, so at most two synthesis calls per request. The second pass only
# happens when the first draft failed the citation check, so this is a ceiling on
# a failure path rather than an added cost on a good one. Kept at one because each
# attempt is a full synthesis call against Groq's shared free-tier token window —
# a third attempt would cost more than it is worth.
MAX_SYNTHESIS_ATTEMPTS = 2


def route_after_emergency(state):
    return END if state["is_emergency"] else "check_scope"


def route_after_scope(state):
    return END if state.get("is_out_of_scope") else "tag_dosha"


def route_after_retrieve(state):
    if (
        state["confidence"] == "low"
        and not state.get("canonical_term")
        and not state.get("is_clarification")
    ):
        return "clarify"
    return "check_safety"


def route_after_tools(state):
    """Split the router's three outcomes onto three different paths.

    `direct_answer` skips retrieval entirely — there is no verse to find for a
    greeting. `needs_clarification` also skips retrieval, and that is the point:
    asking first costs no synthesis call, whereas retrieving for an empty question
    spends one to produce something unfocused. Everything else retrieves as before.
    """
    if state.get("direct_answer"):
        return "direct_answer"
    if state.get("needs_clarification"):
        return "clarify"
    return "retrieve"


def route_after_grounding(state):
    """Retry synthesis once when the citation check rejected the draft.

    The grounding node decides *whether* a retry is worth attempting (it writes
    `grounding_retry_instruction` only for faults a rewrite can fix); this
    function decides whether budget remains. Both conditions must hold, so the
    loop terminates after MAX_SYNTHESIS_ATTEMPTS no matter what the model returns.
    """
    if (
        state.get("grounding_retry_instruction")
        and state.get("synthesis_attempts", 1) < MAX_SYNTHESIS_ATTEMPTS
    ):
        return "synthesize"
    return "attribution"


graph = StateGraph(AgentState)
graph.add_node("check_emergency", check_emergency)
graph.add_node("check_scope", check_scope)
graph.add_node("tag_dosha", tag_dosha)
graph.add_node("expand_query", expand_query)
graph.add_node("route_tools", route_tools)
graph.add_node("direct_answer", direct_answer)
graph.add_node("retrieve", retrieve)
graph.add_node("clarify", clarify)
graph.add_node("check_safety", check_safety)
graph.add_node("synthesize", synthesize)
graph.add_node("grounding", grounding)
graph.add_node("semantic_check", semantic_check)
graph.add_node("attribution", attribution)

graph.set_entry_point("check_emergency")
graph.add_conditional_edges(
    "check_emergency",
    route_after_emergency,
    {"check_scope": "check_scope", END: END},
)
graph.add_conditional_edges(
    "check_scope",
    route_after_scope,
    {"tag_dosha": "tag_dosha", END: END},
)
graph.add_edge("tag_dosha", "expand_query")
graph.add_edge("expand_query", "route_tools")
graph.add_conditional_edges(
    "route_tools",
    route_after_tools,
    {
        "direct_answer": "direct_answer",
        "clarify": "clarify",
        "retrieve": "retrieve",
    },
)
graph.add_edge("direct_answer", END)
graph.add_conditional_edges(
    "retrieve",
    route_after_retrieve,
    {"clarify": "clarify", "check_safety": "check_safety"},
)
graph.add_edge("clarify", END)
graph.add_edge("check_safety", "synthesize")
graph.add_edge("synthesize", "grounding")
# Semantic verification sits between the structural citation check and the retry
# router, so an unsupported-but-well-cited claim can request a rewrite through the
# same single retry edge rather than a second loop. It is a no-op (and costs no
# tokens) unless CHARAKA_SEMANTIC_CHECK=1.
graph.add_edge("grounding", "semantic_check")
# Retry edge. Loops back to synthesize only when grounding asked for it and the
# attempt budget is unspent; otherwise falls through to attribution as before.
graph.add_conditional_edges(
    "semantic_check",
    route_after_grounding,
    {"synthesize": "synthesize", "attribution": "attribution"},
)
graph.add_edge("attribution", END)

charaka_agent = graph.compile()