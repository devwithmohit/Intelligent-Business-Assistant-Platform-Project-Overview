import asyncio
import logging
import os
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ContentToolError(Exception):
    pass


class ContentTools:
    """
    Lightweight helpers for content workflows: SEO analysis, grammar checks, paraphrase,
    and image generation hooks. Integrations are best-effort and optional (use env/config keys).
    """

    def __init__(
        self, grammar_key: Optional[str] = None, image_key: Optional[str] = None
    ) -> None:
        self.grammar_key = grammar_key or os.getenv("GRAMMAR_API_KEY")
        self.image_key = image_key or os.getenv("IMAGE_API_KEY")

        # try optional local libraries
        try:
            import language_tool_python  # type: ignore

            self._langtool = language_tool_python.LanguageTool("en-US")
        except Exception:
            self._langtool = None

    async def analyze_seo(
        self, text: str, keywords: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Basic SEO heuristics: word count, estimated reading time, simple keyword density,
        and suggestions (title/headers, meta length).
        """
        if not text:
            return {
                "word_count": 0,
                "reading_minutes": 0,
                "keyword_density": {},
                "suggestions": [],
            }

        # normalize
        plain = re.sub(r"<[^>]+>", " ", text)
        words = re.findall(r"\w+", plain)
        word_count = len(words)
        reading_minutes = max(1, int(word_count / 200))  # rough estimate (200 wpm)

        kd: Dict[str, float] = {}
        if keywords:
            low_text = " ".join(words).lower()
            for k in keywords:
                if not k:
                    continue
                count = low_text.count(k.lower())
                kd[k] = round((count / word_count) * 100 if word_count > 0 else 0.0, 2)

        suggestions: List[str] = []
        # title suggestion: first line length
        first_line = (text.splitlines()[0] if text.splitlines() else "")[:200]
        if len(first_line.split()) < 3:
            suggestions.append("Add a descriptive title/first line.")
        # meta description length heuristic
        if len(plain) > 0 and len(plain) < 50:
            suggestions.append("Consider adding a longer introduction for SEO.")
        if word_count < 300:
            suggestions.append(
                "Content is short (<300 words); consider expanding for SEO."
            )
        # headings heuristic
        if not re.search(r"<h[1-6]>|^#{1,6}\s", text, flags=re.I | re.M):
            suggestions.append("Add H1/H2 headings to structure the content.")
        return {
            "word_count": word_count,
            "reading_minutes": reading_minutes,
            "keyword_density": kd,
            "suggestions": suggestions,
        }

    async def grammar_check(self, text: str, language: str = "en-US") -> Dict[str, Any]:
        """
        Run grammar/style check. Uses language_tool_python if available; otherwise performs
        a very small set of heuristics (double spaces, repeated words).
        """
        if not text:
            return {"matches": [], "corrected": "", "issues": 0}

        if self._langtool:
            # run in thread to avoid blocking event loop
            def _check():
                matches = self._langtool.check(text)
                return matches

            matches = await asyncio.to_thread(_check)
            # map to simple structure
            simplified = []
            for m in matches:
                simplified.append(
                    {
                        "message": str(m.message),
                        "offset": m.offset,
                        "length": m.errorLength,
                        "replacements": m.replacements,
                    }
                )
            # optionally produce a naive corrected string using first replacement
            corrected = text
            try:
                corrected = self._langtool.correct(text)
            except Exception:
                pass
            return {
                "matches": simplified,
                "corrected": corrected,
                "issues": len(simplified),
            }

        # fallback heuristics
        issues = []
        # double spaces
        if "  " in text:
            issues.append({"message": "Double spaces detected", "example": "  "})
        # repeated words (very naive)
        rep = re.findall(r"\b(\w+)\s+\1\b", text, flags=re.I)
        for r in set(rep):
            issues.append({"message": f"Repeated word: {r}", "example": r})
        corrected = re.sub(r"\s{2,}", " ", text)
        corrected = re.sub(r"\b(\w+)\s+\1\b", r"\1", corrected, flags=re.I)
        return {"matches": issues, "corrected": corrected, "issues": len(issues)}

    async def paraphrase(self, text: str, style: Optional[str] = None) -> str:
        """
        Best-effort paraphrase. This is a stub that will call an external provider if configured.
        If no provider is configured, performs simple synonym-like replacements (very naive).
        """
        if not text:
            return ""

        # If a configured LLM/image key exists we could call llm_service externally.
        # To avoid circular imports, we keep this simple: naive paraphrase
        # Replace some common phrases to simulate paraphrasing
        replacements = {
            "in order to": "to",
            "due to the fact that": "because",
            "as a result": "consequently",
        }
        out = text
        for k, v in replacements.items():
            out = re.sub(re.escape(k), v, out, flags=re.I)
        # small shuffle of sentences for variety (if >1 sentence)
        sents = re.split(r"(?<=[.!?])\s+", out.strip())
        if len(sents) > 1 and style == "short":
            # keep first two sentences
            out = " ".join(sents[:2])
        else:
            out = " ".join(sents)
        return out

    async def generate_image(
        self, prompt: str, size: str = "1024x1024", provider: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Hook for image generation. If an IMAGE_API_KEY is configured for a known provider,
        call it. Otherwise return a placeholder response indicating image generation not available.
        Implementations for specific providers can be added later.
        """
        if not prompt:
            raise ContentToolError("prompt required for image generation")

        # quick provider dispatch (placeholder)
        prov = (provider or os.getenv("IMAGE_PROVIDER") or "none").lower()
        if prov in ("none", "local", "") and not self.image_key:
            # no provider configured
            logger.debug("No image provider configured, returning placeholder")
            return {
                "provider": "none",
                "url": None,
                "message": "No image provider configured in environment",
            }

        # Example: stub for Stability or OpenAI image endpoints could be implemented here.
        # Since keys and APIs vary, return a standardized "queued" response for now.
        logger.info(
            "Image generation requested provider=%s size=%s prompt=%s",
            prov,
            size,
            prompt[:80],
        )
        # If a real provider integration is desired, implement here (httpx calls, streaming, S3 upload, etc.)
        return {
            "provider": prov,
            "status": "queued",
            "prompt": prompt,
            "size": size,
            "url": None,
        }


# module-level singleton
_default_tools: Optional[ContentTools] = None


def get_tools() -> ContentTools:
    global _default_tools
    if _default_tools is None:
        _default_tools = ContentTools(
            grammar_key=os.getenv("GRAMMAR_API_KEY"),
            image_key=os.getenv("IMAGE_API_KEY"),
        )
    return _default_tools


# convenience wrappers
async def analyze_seo(
    text: str, keywords: Optional[List[str]] = None
) -> Dict[str, Any]:
    return await get_tools().analyze_seo(text=text, keywords=keywords)


async def grammar_check(text: str, language: str = "en-US") -> Dict[str, Any]:
    return await get_tools().grammar_check(text=text, language=language)


async def paraphrase(text: str, style: Optional[str] = None) -> str:
    return await get_tools().paraphrase(text=text, style=style)


async def generate_image(
    prompt: str, size: str = "1024x1024", provider: Optional[str] = None
) -> Dict[str, Any]:
    return await get_tools().generate_image(prompt=prompt, size=size, provider=provider)
