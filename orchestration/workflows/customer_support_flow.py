import logging
from typing import Any, Dict

from backend.orchestration.graph_builder import GraphBuilder

logger = logging.getLogger(__name__)


def build_customer_support_flow() -> GraphBuilder:
    """
    Example customer support workflow:
      intake -> triage -> (research | draft_response | escalate) -> (draft_response -> close_ticket)
      escalate -> human_operator -> close_ticket
    Conditions use the workflow context (e.g. context['priority'], context['need_research'], context['confidence'])
    """
    g = GraphBuilder(name="customer_support_flow")

    # register agents (metadata is advisory and can include import path / capabilities)
    g.register_agent(
        "customer_service", {"entrypoint": "backend.agents.customer_service.agent"}
    )
    g.register_agent(
        "sales_research", {"entrypoint": "backend.agents.sales_research.agent"}
    )
    g.register_agent(
        "content_creation", {"entrypoint": "backend.agents.content_creation.agent"}
    )
    g.register_agent(
        "human_operator",
        {"entrypoint": "manual.handoff", "capabilities": ["review", "respond"]},
    )

    # nodes
    g.add_node(
        "intake",
        agent="customer_service",
        config={"step": "ingest"},
        description="Receive and normalize customer message",
    )
    g.add_node(
        "triage",
        agent="customer_service",
        config={"step": "triage"},
        description="Determine priority, intent, and whether research is needed",
    )
    g.add_node(
        "research",
        agent="sales_research",
        config={"scope": "web_and_crm"},
        description="Gather contextual info for the case",
    )
    g.add_node(
        "draft_response",
        agent="content_creation",
        config={"tone": "helpful"},
        description="Draft a response to the customer",
    )
    g.add_node(
        "escalate",
        agent="human_operator",
        config={"notify": True},
        description="Escalate to human operator",
    )
    g.add_node(
        "close_ticket",
        agent="customer_service",
        config={"finalize": True},
        description="Finalize and close the ticket",
    )

    # edges (src -> dst) with optional condition expressions evaluated against context
    g.add_edge("intake", "triage")  # unconditional
    # triage decisions
    g.add_edge("triage", "escalate", condition="priority >= 8 or escalate == True")
    g.add_edge("triage", "research", condition="need_research == True")
    g.add_edge(
        "triage",
        "draft_response",
        condition="not need_research and not (priority >= 8 or escalate == True)",
    )

    # research feeds drafting
    g.add_edge("research", "draft_response")

    # draft -> close or escalate depending on confidence/satisfaction
    g.add_edge(
        "draft_response",
        "close_ticket",
        condition="satisfied == True or confidence >= 0.85",
    )
    g.add_edge(
        "draft_response",
        "escalate",
        condition="satisfied == False and confidence < 0.6",
    )

    # escalate handled then close
    g.add_edge("escalate", "close_ticket")

    return g


if __name__ == "__main__":
    wf = build_customer_support_flow()
    # quick visual preview (Mermaid)
    print(wf.export_mermaid())
    # persist a JSON definition next to this workflow for inspection
    wf.save_json("customer_support_flow.json")
