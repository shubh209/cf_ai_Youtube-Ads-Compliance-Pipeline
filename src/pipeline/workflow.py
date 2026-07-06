"""
LangGraph workflow: Indexer -> Enrich -> Auditor
"""

from langgraph.graph import END, StateGraph

from src.pipeline.nodes import audit_content_node, enrich_content_node, index_video_node
from src.pipeline.state import VideoAuditState


def create_graph():
    workflow = StateGraph(VideoAuditState)
    workflow.add_node("indexer", index_video_node)
    workflow.add_node("enrich", enrich_content_node)
    workflow.add_node("auditor", audit_content_node)
    workflow.set_entry_point("indexer")
    workflow.add_edge("indexer", "enrich")
    workflow.add_edge("enrich", "auditor")
    workflow.add_edge("auditor", END)
    return workflow.compile()


app = create_graph()
