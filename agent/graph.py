from langgraph.graph import END, StateGraph

from agent.nodes.creator import creator_node
from agent.nodes.planner import planner_node
from agent.nodes.publisher import publisher_node
from agent.nodes.research import research_node
from agent.state import AgentState


def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("research", research_node)
    graph.add_node("planner", planner_node)
    graph.add_node("creator", creator_node)
    graph.add_node("publisher", publisher_node)

    graph.set_entry_point("research")
    graph.add_edge("research", "planner")
    graph.add_edge("planner", "creator")
    graph.add_edge("creator", "publisher")
    graph.add_edge("publisher", END)

    return graph.compile()


agent_graph = build_graph()
