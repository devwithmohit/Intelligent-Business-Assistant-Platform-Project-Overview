import logging
from typing import Any, Dict, List, Optional

from ...agents.base_agent import BaseAgent, AgentResult
from ...agents.interfaces import Step
from ...schemas.lm_schemas import LLMRequest, ChatMessage
from ...utils.llm_utils import apply_prompt_template, sanitize_prompt, is_safe_prompt
from ...services import crm_client  # backend.services.crm_client

logger = logging.getLogger("backend.agents.customer_service")


class CustomerServiceAgent(BaseAgent):
    """
    Simple customer service agent:
    - Summarizes incoming customer message
    - Creates a CRM ticket
    - Drafts a suggested response using the LLM
    """

    def __init__(self, name: str = "customer_service", config: Optional[Dict[str, Any]] = None):
        super().__init__(name=name, config=config)

    async def _plan(self, customer_message: str, customer_id: Optional[str] = None, priority: str = "normal") -> List[Step]:
        """
        Create a small, deterministic plan from input.
        Expect: customer_message (raw), optional customer_id and priority.
        """
        message = sanitize_prompt(customer_message or "")
        return [
            {"type": "summarize", "payload": {"message": message}},
            {"type": "create_ticket", "payload": {"customer_id": customer_id, "priority": priority}},
            {"type": "draft_response", "payload": {"message": message}},
        ]

    async def _execute_step(self, step: Step, **kwargs) -> Any:
        t = step.get("type")
        payload = step.get("payload", {}) or {}

        if t == "summarize":
            message = payload.get("message", "")
            if not is_safe_prompt(message):
                logger.warning("Blocked unsafe customer message during summarize")
                return {"summary": "", "note": "blocked unsafe content"}

            prompt_tpl = (
                "You are a customer support assistant. Summarize the customer's message in 2-3 sentences, "
                "extract the intent and list key facts as bullet points.\n\nCustomer message:\n{message}"
            )
            prompt = apply_prompt_template(prompt_tpl, message=message)
            req = LLMRequest(task="content", prompt=prompt, params={"temperature": 0.0})
            try:
                resp = await self.llm.generate(req)
                summary = (resp.text or "").strip()
                return {"summary": summary, "raw": resp.raw if getattr(resp, "raw", None) else None}
            except Exception as e:
                logger.exception("LLM summarize failed: %s", e)
                return {"summary": "", "error": str(e)}

        if t == "create_ticket":
            # expects that a prior summarize step was run — attempt to read last_run memory
            customer_id = payload.get("customer_id")
            priority = payload.get("priority", "normal")
            # try to fetch summary saved in memory (best-effort)
            last = await self.recall("last_run", limit=1)
            summary_text = ""
            if last and isinstance(last, list) and last[0].get("result"):
                # best-effort extraction
                try:
                    summary_text = str(last[0]["result"].get("output") or "")
                except Exception:
                    summary_text = ""
            subject = summary_text.split("\n", 1)[0][:120] or "Customer inquiry"
            description = summary_text or "Customer message attached in ticket."
            try:
                ticket = await crm_client.create_ticket(customer_id=customer_id, subject=subject, description=description, priority=priority)
                return {"ticket": ticket}
            except Exception as e:
                logger.exception("CRM create_ticket failed: %s", e)
                return {"ticket": None, "error": str(e)}

        if t == "draft_response":
            message = payload.get("message", "")
            if not is_safe_prompt(message):
                logger.warning("Blocked unsafe customer message during draft_response")
                return {"response": "", "note": "blocked unsafe content"}

            prompt_tpl = (
                "You are a professional, empathetic customer support agent. Given the customer message below, "
                "draft a concise (2-4 sentences) helpful response that addresses the customer's needs and suggests next steps.\n\n"
                "Customer message:\n{message}"
            )
            prompt = apply_prompt_template(prompt_tpl, message=message)
            req = LLMRequest(task="chat", prompt=prompt, params={"temperature": 0.2, "max_tokens": 400})
            try:
                resp = await self.llm.generate(req)
                draft = (resp.text or "").strip()
                # store suggested response in memory for auditing
                await self.remember(key="last_suggested_response", value={"response": draft})
                return {"response": draft, "raw": resp.raw if getattr(resp, "raw", None) else None}
            except Exception as e:
                logger.exception("LLM draft_response failed: %s", e)
                return {"response": "", "error": str(e)}

        # Unknown step type: attempt to call a tool with that name
        try:
            result = await self.call_tool(t, **payload)
            return {"tool_result": result}
        except Exception as e:
            logger.debug("Unknown step/tool failed: %s", e)
            return {"error": f"unknown step {t}: {e}"}
