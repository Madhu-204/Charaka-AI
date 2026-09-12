from langgraph.graph import StateGraph, END

from app.state import AgentState
from app.nodes.emergency import check_emergency
from app.nodes.dosha import tag_dosha
from app.nodes.query_expansion import expand_query
from app.nodes.retriever import retrieve
from app.nodes.safety import check_safety
from app.nodes.synthesis import synthesize
from app.nodes.grounding import grounding
from app.nodes.attribution import attribution
from app.nodes.clarify import clarify
from app.nodes.tool_router import route_tools


def route_after_emergency(state):
    return END if state["is_emergency"] else "tag_dosha"


def route_after_retrieve(state):
    if (
        state["confidence"] == "low"
        and not state.get("canonical_term")
        and not state.get("is_clarification")
    ):
        return "clarify"
    return "check_safety"


graph = StateGraph(AgentState)
graph.add_node("check_emergency", check_emergency)
graph.add_node("tag_dosha", tag_dosha)
graph.add_node("expand_query", expand_query)
graph.add_node("route_tools", route_tools)
graph.add_node("retrieve", retrieve)
graph.add_node("clarify", clarify)
graph.add_node("check_safety", check_safety)
graph.add_node("synthesize", synthesize)
graph.add_node("grounding", grounding)
graph.add_node("attribution", attribution)

graph.set_entry_point("check_emergency")
graph.add_conditional_edges(
    "check_emergency",
    route_after_emergency,
    {"tag_dosha": "tag_dosha", END: END},
)
graph.add_edge("tag_dosha", "expand_query")
graph.add_edge("expand_query", "route_tools")
graph.add_edge("route_tools", "retrieve")
graph.add_conditional_edges(
    "retrieve",
    route_after_retrieve,
    {"clarify": "clarify", "check_safety": "check_safety"},
)
graph.add_edge("clarify", END)
graph.add_edge("check_safety", "synthesize")
graph.add_edge("synthesize", "grounding")
graph.add_edge("grounding", "attribution")
graph.add_edge("attribution", END)

charaka_agent = graph.compile()