import logging
from typing import Any, Dict

from orchestration.graph_builder import GraphBuilder

logger = logging.getLogger(__name__)


def build_sales_pipeline_flow() -> GraphBuilder:
    """
    Sales pipeline workflow example:
      lead_capture -> qualify -> (research | outreach | nurture | lost) ->
      outreach -> negotiate -> (close_won | close_lost) -> crm_sync
    Conditions use workflow context keys like: qualified, needs_research, score, interested, deal
    """
    g = GraphBuilder(name="sales_pipeline_flow")

    # register agents (metadata is advisory)
    g.register_agent("lead_capture", {"entrypoint": "backend.services.crm_client.ingest_lead"})
    g.register_agent("lead_qualification", {"entrypoint": "backend.agents.sales_research.agent"})
    g.register_agent("sales_research", {"entrypoint": "backend.agents.sales_research.agent"})
    g.register_agent("outreach", {"entrypoint": "backend.agents.content_creation.agent"})
    g.register_agent("marketing", {"entrypoint": "backend.services.enrichment_service.nurture"})
    g.register_agent("sales", {"entrypoint": "backend.services.agent_service"})
    g.register_agent("crm_sync", {"entrypoint": "backend.services.kb_manager"})

    # nodes
    g.add_node("lead_capture", agent="lead_capture", config={}, description="Capture lead from forms/ads/CRM")
    g.add_node("qualify", agent="lead_qualification", config={"method": "score_and_rules"}, description="Score and qualify lead")
    g.add_node("research", agent="sales_research", config={"scope": "company_profile"}, description="Gather account intelligence")
    g.add_node("outreach", agent="outreach", config={"channel": "email"}, description="Perform outreach / outreach sequence")
    g.add_node("nurture", agent="marketing", config={"campaign": "drip"}, description="Place in nurture campaign")
    g.add_node("negotiate", agent="sales", config={"attempts": 3}, description="Handle negotiation / discovery calls")
    g.add_node("close_won", agent="crm_sync", config={"status": "won"}, description="Mark opportunity as won in CRM")
    g.add_node("close_lost", agent="crm_sync", config={"status": "lost"}, description="Mark opportunity as lost in CRM")

    # edges / conditional flows
    g.add_edge("lead_capture", "qualify")
    # qualification outcomes
    g.add_edge("qualify", "research", condition="qualified == True and needs_research == True")
    g.add_edge("qualify", "outreach", condition="qualified == True and not needs_research")
    g.add_edge("qualify", "nurture", condition="qualified == False and score >= 0.4")
    g.add_edge("qualify", "close_lost", condition="qualified == False and score < 0.4")

    # research -> outreach
    g.add_edge("research", "outreach")

    # outreach outcomes
    g.add_edge("outreach", "negotiate", condition="interested == True")
    g.add_edge("outreach", "nurture", condition="interested == False")

    # negotiation outcomes
    g.add_edge("negotiate", "close_won", condition="deal == 'won'")
    g.add_edge("negotiate", "close_lost", condition="deal == 'lost'")

    return g


if __name__ == "__main__":
    wf = build_sales_pipeline_flow()
    print(wf.export_mermaid())
    wf.save_json("sales_pipeline_flow.json")
