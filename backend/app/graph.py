from langgraph.graph import StateGraph, END

from app.state import AgentState
from app.nodes.emergency import check_emergency
from app.nodes.query_expansion import expand_query
from app.nodes.retriever import retrieve
from app.nodes.safety import check_safety
from app.nodes.synthesis import synthesize


def route_after_emergency(state):
    return END if state["is_emergency"] else "expand_query"


graph = StateGraph(AgentState)
graph.add_node("check_emergency", check_emergency)
graph.add_node("expand_query", expand_query)
graph.add_node("retrieve", retrieve)
graph.add_node("check_safety", check_safety)
graph.add_node("synthesize", synthesize)

graph.set_entry_point("check_emergency")
graph.add_conditional_edges(
    "check_emergency",
    route_after_emergency,
    {"expand_query": "expand_query", END: END},
)
graph.add_edge("expand_query", "retrieve")
graph.add_edge("retrieve", "check_safety")
graph.add_edge("check_safety", "synthesize")
graph.add_edge("synthesize", END)

charaka_agent = graph.compile()