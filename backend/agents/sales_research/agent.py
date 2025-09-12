import logging
from typing import Any, Dict, List, Optional

from ...agents.base_agent import BaseAgent, AgentResult
from ...agents.interfaces import Step
from ...schemas.lm_schemas import LLMRequest, ChatMessage
from ...utils.llm_utils import apply_prompt_template, sanitize_prompt, is_safe_prompt

# local tools (search + enrichment) — import as siblings if present
try:
    from . import web_search_client  # type: ignore
except Exception:
    web_search_client = None  # type: ignore

try:
    from . import enrichment_service  # type: ignore
except Exception:
    enrichment_service = None  # type: ignore

logger = logging.getLogger("backend.agents.sales_research")


class SalesResearchAgent(BaseAgent):
    """
    SalesResearchAgent:
      - search for prospects based on a query
      - enrich prospects with additional data (email, company info)
      - draft personalized outreach messages via LLM
    """

    def __init__(self, name: str = "sales_research", config: Optional[Dict[str, Any]] = None):
        super().__init__(name=name, config=config)

    async def _plan(self, query: str, limit: int = 10, outreach_tone: str = "friendly") -> List[Step]:
        q = sanitize_prompt(query or "")
        return [
            {"type": "search", "payload": {"query": q, "limit": limit}},
            {"type": "enrich", "payload": {}},
            {"type": "draft_outreach", "payload": {"tone": outreach_tone}},
        ]

    async def _execute_step(self, step: Step, **kwargs) -> Any:
        t = step.get("type")
        payload = step.get("payload", {}) or {}

        if t == "search":
            query = payload.get("query", "")
            limit = int(payload.get("limit", 10))
            if not query:
                return {"prospects": [], "note": "empty query"}

            if web_search_client and getattr(web_search_client, "search", None):
                try:
                    prospects = await web_search_client.search(query=query, limit=limit)
                except Exception as e:
                    logger.exception("web_search_client.search failed: %s", e)
                    prospects = []
            else:
                logger.debug("No web_search_client available for sales_research")
                prospects = []

            # persist prospects to agent memory for downstream steps/audit
            try:
                await self.remember(key="prospects", value={"items": prospects})
            except Exception:
                logger.debug("Failed to persist prospects to memory")

            return {"prospects": prospects}

        if t == "enrich":
            # load prospects from memory if available, otherwise expect payload
            prospects = payload.get("prospects")
            if prospects is None:
                mem = await self.recall("prospects", limit=1)
                prospects = mem[0]["items"] if mem and isinstance(mem[0], dict) and mem[0].get("items") else []

            enriched = []
            if enrichment_service and getattr(enrichment_service, "enrich_prospect", None):
                for p in prospects:
                    try:
                        e = await enrichment_service.enrich_prospect(p)
                        enriched.append({**p, **(e or {})})
                    except Exception as e:
                        logger.debug("enrichment failed for prospect %s: %s", p, e)
                        enriched.append(p)
            else:
                logger.debug("No enrichment_service available; returning raw prospects")
                enriched = prospects

            # store enriched prospects
            try:
                await self.remember(key="enriched_prospects", value={"items": enriched})
            except Exception:
                logger.debug("Failed to persist enriched prospects")

            return {"enriched": enriched}

        if t == "draft_outreach":
            tone = payload.get("tone", "friendly")
            # load enriched prospects
            mem = await self.recall("enriched_prospects", limit=1)
            prospects = mem[0]["items"] if mem and isinstance(mem[0], dict) and mem[0].get("items") else []
            drafts = []

            for p in prospects:
                name = p.get("name") or p.get("contact_name") or "there"
                company = p.get("company") or p.get("org") or ""
                pain = p.get("pain_points") or p.get("notes") or ""
                # Build safe prompt
                prompt_tpl = (
                    "Write a {tone} personalized outreach email of 3-4 sentences to {name} at {company}.\n\n"
                    "Context / pain points: {pain}\n\n"
                    "Keep it concise, include a single clear CTA, and a one-line subject suggestion.\n\n"
                )
                prompt = apply_prompt_template(prompt_tpl, tone=tone, name=name, company=company or "their company", pain=pain or "no additional context")
                prompt = sanitize_prompt(prompt)
                if not is_safe_prompt(prompt):
                    logger.warning("Blocked unsafe prompt for outreach to %s", name)
                    drafts.append({"prospect": p, "draft": "", "note": "blocked"})
                    continue

                try:
                    req = LLMRequest(task="chat", prompt=prompt, params={"temperature": 0.3, "max_tokens": 400})
                    resp = await self.llm.generate(req)
                    text = (resp.text or "").strip()
                    drafts.append({"prospect": p, "draft": text, "raw": getattr(resp, "raw", None)})
                except Exception as e:
                    logger.exception("LLM draft_outreach failed for %s: %s", name, e)
                    drafts.append({"prospect": p, "draft": "", "error": str(e)})

            # persist drafts
            try:
                await self.remember(key="outreach_drafts", value={"items": drafts})
            except Exception:
                logger.debug("Failed to persist outreach drafts")

            return {"drafts": drafts}

        # fallback: try tools
        try:
            result = await self.call_tool(t, **payload)
            return {"tool_result": result}
        except Exception as e:
            logger.debug("Unknown step/tool failed: %s", e)
            return {"error": f"unknown step {t}: {e}"}
