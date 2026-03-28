import logging
from typing import Any, Dict

from orchestration.graph_builder import GraphBuilder

logger = logging.getLogger(__name__)


def build_content_creation_flow() -> GraphBuilder:
    """
    Content creation pipeline:
      research -> draft -> (auto_publish | review) -> publish -> notify
    Conditions use the workflow context (e.g. context['quality_ok'], context['needs_review'])
    """
    g = GraphBuilder(name="content_creation_flow")

    # register agents
    g.register_agent("research", {"entrypoint": "backend.agents.data_analysis.agent"})
    g.register_agent(
        "content_creation", {"entrypoint": "backend.agents.content_creation.agent"}
    )
    g.register_agent(
        "reviewer", {"entrypoint": "backend.agents.project_management.agent"}
    )
    g.register_agent(
        "publisher", {"entrypoint": "backend.services.template_manager.publish"}
    )
    g.register_agent(
        "notifier", {"entrypoint": "backend.services.enrichment_service.notify"}
    )

    # nodes
    g.add_node(
        "research",
        agent="research",
        config={"scope": "web_crm"},
        description="Collect research and facts",
    )
    g.add_node(
        "draft",
        agent="content_creation",
        config={"tone": "informative"},
        description="Draft content",
    )
    g.add_node(
        "review",
        agent="reviewer",
        config={"role": "editor"},
        description="Human/editor review",
    )
    g.add_node(
        "publish", agent="publisher", config={}, description="Publish final content"
    )
    g.add_node(
        "notify",
        agent="notifier",
        config={"channels": ["email", "slack"]},
        description="Notify stakeholders",
    )

    # edges / flow
    g.add_edge("research", "draft")
    # after drafting decide whether review required
    g.add_edge("draft", "review", condition="needs_review == True")
    # if quality ok and no review required, publish
    g.add_edge(
        "draft", "publish", condition="needs_review == False and quality_ok == True"
    )
    # review leads to publish or back to draft for revisions
    g.add_edge("review", "publish", condition="approved == True")
    g.add_edge("review", "draft", condition="approved == False")
    # after publish, notify
    g.add_edge("publish", "notify")

    return g


if __name__ == "__main__":
    wf = build_content_creation_flow()
    print(wf.export_mermaid())
    wf.save_json("content_creation_flow.json")
