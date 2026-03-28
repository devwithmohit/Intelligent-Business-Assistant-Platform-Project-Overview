import logging
from typing import Any, Dict

from orchestration.graph_builder import GraphBuilder

logger = logging.getLogger(__name__)


def build_data_analysis_flow() -> GraphBuilder:
    """
    Data analysis workflow:
      collect -> preprocess -> analyze -> (visualize | summarize) -> report -> notify
    Context keys used in conditions: needs_visualization, summary_ok, confidence
    """
    g = GraphBuilder(name="data_analysis_flow")

    # register agents (metadata is advisory)
    g.register_agent(
        "data_collector", {"entrypoint": "backend.services.web_search_client"}
    )
    g.register_agent("preprocessor", {"entrypoint": "backend.services.content_tools"})
    g.register_agent("analyzer", {"entrypoint": "backend.agents.data_analysis.agent"})
    g.register_agent(
        "visualizer", {"entrypoint": "backend.services.enrichment_service.visualize"}
    )
    g.register_agent(
        "reporter", {"entrypoint": "backend.services.template_manager.publish"}
    )
    g.register_agent(
        "notifier", {"entrypoint": "backend.services.enrichment_service.notify"}
    )

    # nodes
    g.add_node(
        "collect",
        agent="data_collector",
        config={"sources": ["web", "crm"]},
        description="Collect raw data",
    )
    g.add_node(
        "preprocess",
        agent="preprocessor",
        config={"steps": ["clean", "normalize"]},
        description="Clean and normalize data",
    )
    g.add_node(
        "analyze",
        agent="analyzer",
        config={"method": "statistical_and_llm"},
        description="Run analysis / extract insights",
    )
    g.add_node(
        "visualize",
        agent="visualizer",
        config={"format": "charts"},
        description="Optional visualizations",
    )
    g.add_node(
        "summarize",
        agent="reporter",
        config={"format": "summary"},
        description="Generate textual summary",
    )
    g.add_node(
        "report",
        agent="reporter",
        config={"format": "detailed"},
        description="Produce final report",
    )
    g.add_node(
        "notify",
        agent="notifier",
        config={"channels": ["email", "slack"]},
        description="Notify stakeholders",
    )

    # edges / flow
    g.add_edge("collect", "preprocess")
    g.add_edge("preprocess", "analyze")
    # after analysis choose visualization or summarization/publishing
    g.add_edge("analyze", "visualize", condition="needs_visualization == True")
    g.add_edge("analyze", "summarize", condition="needs_visualization == False")
    # visualization typically leads to reporting (merge path)
    g.add_edge("visualize", "report")
    g.add_edge("summarize", "report", condition="summary_ok == True")
    # if summary was not ok, loop back to analyze for refinement
    g.add_edge("summarize", "analyze", condition="summary_ok == False")
    # final steps
    g.add_edge("report", "notify")

    return g


if __name__ == "__main__":
    wf = build_data_analysis_flow()
    print(wf.export_mermaid())
    wf.save_json("data_analysis_flow.json")
