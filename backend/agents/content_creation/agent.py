import logging
from typing import Any, Dict, List, Optional

from ...agents.base_agent import BaseAgent, AgentResult
from ...agents.interfaces import Step
from ...utils.llm_utils import apply_prompt_template, sanitize_prompt, is_safe_prompt
from ...services import template_manager  # optional, best-effort
from ...schemas.lm_schemas import LLMRequest, ChatMessage

logger = logging.getLogger("backend.agents.content_creation")


class ContentCreationAgent(BaseAgent):
    """
    ContentCreationAgent:
      - Generate an outline from a brief
      - Expand outline into a draft
      - Optionally refine/edit the draft using instructions or templates
    """

    def __init__(self, name: str = "content_creation", config: Optional[Dict[str, Any]] = None):
        super().__init__(name=name, config=config)

    async def _plan(self, brief: str, tone: str = "neutral", target_audience: str = "general", length: str = "short") -> List[Step]:
        b = sanitize_prompt(brief or "")
        return [
            {"type": "generate_outline", "payload": {"brief": b, "tone": tone, "audience": target_audience, "length": length}},
            {"type": "generate_draft", "payload": {"length": length, "tone": tone}},
            {"type": "refine", "payload": {"instructions": "Make concise, improve clarity, fix grammar."}},
        ]

    async def _execute_step(self, step: Step, **kwargs) -> Any:
        step_type = step.get("type")
        payload = step.get("payload", {}) or {}

        if step_type == "generate_outline":
            brief = payload.get("brief", "")
            tone = payload.get("tone", "neutral")
            audience = payload.get("audience", "general")
            if not brief:
                return {"outline": [], "note": "empty brief"}

            prompt_tpl = (
                "You are a content writer. Given the brief below, produce a clear outline with 5-10 numbered sections. "
                "Include short (1-2 sentence) notes describing each section.\n\nBrief:\n{brief}\n\nTone: {tone}\nAudience: {audience}\n\nOutline:"
            )
            prompt = apply_prompt_template(prompt_tpl, brief=brief, tone=tone, audience=audience)
            prompt = sanitize_prompt(prompt)
            if not is_safe_prompt(prompt):
                logger.warning("Blocked unsafe brief for content creation")
                return {"outline": [], "note": "blocked"}

            try:
                text = await self.llm_generate(task="content", prompt=prompt, model_hint=self.config.get("model_hint"))
                # best-effort split into lines
                outline_lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
                await self.remember(key="outline", value={"items": outline_lines})
                return {"outline": outline_lines, "raw": text}
            except Exception as e:
                logger.exception("Outline generation failed: %s", e)
                return {"outline": [], "error": str(e)}

        if step_type == "generate_draft":
            # load outline from memory if not provided
            outline = payload.get("outline")
            if outline is None:
                mem = await self.recall("outline", limit=1)
                outline = mem[0]["items"] if mem and isinstance(mem[0], dict) and mem[0].get("items") else []
            tone = payload.get("tone", "neutral")
            length = payload.get("length", "short")

            if not outline:
                return {"draft": "", "note": "no outline available"}

            outline_text = "\n".join(outline) if isinstance(outline, list) else str(outline)
            prompt_tpl = (
                "Expand the following outline into a well-structured article. Tone: {tone}. Target length: {length}.\n\nOutline:\n{outline}\n\nArticle:"
            )
            prompt = apply_prompt_template(prompt_tpl, tone=tone, length=length, outline=outline_text)
            prompt = sanitize_prompt(prompt)
            if not is_safe_prompt(prompt):
                logger.warning("Blocked unsafe draft prompt")
                return {"draft": "", "note": "blocked"}

            try:
                draft = await self.llm_generate(task="content", prompt=prompt, model_hint=self.config.get("model_hint"), params={"temperature": 0.3, "max_tokens": 1200})
                await self.remember(key="draft", value={"text": draft})
                return {"draft": draft}
            except Exception as e:
                logger.exception("Draft generation failed: %s", e)
                return {"draft": "", "error": str(e)}

        if step_type == "refine":
            instructions = payload.get("instructions", "Polish and improve.")
            # try to get draft
            draft_mem = await self.recall("draft", limit=1)
            draft_text = draft_mem[0]["text"] if draft_mem and isinstance(draft_mem[0], dict) and draft_mem[0].get("text") else payload.get("draft", "")
            if not draft_text:
                return {"refined": "", "note": "no draft to refine"}

            # if a template manager is available and a template name provided, render it
            template_name = payload.get("template_name")
            if template_name and hasattr(template_manager, "render_template"):
                try:
                    rendered = template_manager.render_template(template_name, {"content": draft_text})
                    # optionally ask LLM to refine rendered result
                    draft_text = rendered
                except Exception:
                    logger.debug("template_manager.render_template failed for %s", template_name)

            prompt_tpl = (
                "You are an editor. Apply the following edit instructions to the article below:\n\nInstructions: {instructions}\n\nArticle:\n{article}\n\nRefined article:"
            )
            prompt = apply_prompt_template(prompt_tpl, instructions=instructions, article=draft_text)
            prompt = sanitize_prompt(prompt)
            if not is_safe_prompt(prompt):
                logger.warning("Blocked unsafe refine prompt")
                return {"refined": "", "note": "blocked"}

            try:
                refined = await self.llm_generate(task="content", prompt=prompt, model_hint=self.config.get("model_hint"), params={"temperature": 0.1, "max_tokens": 1200})
                await self.remember(key="final", value={"text": refined})
                return {"refined": refined}
            except Exception as e:
                logger.exception("Refine step failed: %s", e)
                return {"refined": "", "error": str(e)}

        # fallback: try to call a tool
        try:
            tool_result = await self.call_tool(step_type, **payload)
            return {"tool_result": tool_result}
        except Exception as e:
            logger.debug("Unknown step/tool failed: %s", e)
            return {"error": f"unknown step {step_type}: {e}"}
