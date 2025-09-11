import asyncio
import logging
import math
import random
import re
from typing import Any, Callable, Iterable, List, Optional, Sequence

logger = logging.getLogger(__name__)

# try to load project configured unsafe tokens / blocklist
try:
    from ..core import config as core_config  # type: ignore

    DEFAULT_BLOCKLIST: List[str] = getattr(core_config.settings, "LLM_PROMPT_BLOCKLIST", [])
except Exception:
    DEFAULT_BLOCKLIST = ["<script>", "eval(", "DROP TABLE", "passwd", "token"]


def apply_prompt_template(template: str, /, **kwargs) -> str:
    """
    Simple safe formatting for prompt templates. Uses python format with braces.
    Avoids evaluating arbitrary expressions by using str() on values.
    """
    safe_kwargs = {k: str(v) for k, v in kwargs.items()}
    try:
        return template.format(**safe_kwargs)
    except Exception:
        # Fallback: naive replacement of {key} occurrences
        out = template
        for k, v in safe_kwargs.items():
            out = out.replace("{" + k + "}", v)
        return out


def sanitize_prompt(prompt: str) -> str:
    """Normalize whitespace and trim length for safety."""
    if not prompt:
        return ""
    p = prompt.strip()
    # collapse many whitespace/newlines
    p = re.sub(r"\s{2,}", " ", p)
    # remove non-printable chars
    p = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]+", "", p)
    return p


def _contains_blocked(prompt: str, blocklist: Sequence[str]) -> Optional[str]:
    low = prompt.lower()
    for token in blocklist:
        if token and token.lower() in low:
            return token
    return None


def is_safe_prompt(prompt: str, blocklist: Optional[Sequence[str]] = None) -> bool:
    """
    Basic safety check against a configurable blocklist.
    Returns False when a blocked token is found.
    """
    if not prompt:
        return True
    bl = list(blocklist) if blocklist is not None else DEFAULT_BLOCKLIST
    matched = _contains_blocked(prompt, bl)
    if matched:
        logger.warning("Prompt blocked due to token=%s", matched)
        return False
    return True


def normalize_response(resp: Any) -> str:
    """
    Best-effort normalization of provider responses to a single text string.
    Mirrors normalization used in llm_service but kept decoupled to avoid circular imports.
    """
    if resp is None:
        return ""
    # if it's already a string
    if isinstance(resp, str):
        return resp
    # dict-like responses: try common shapes
    try:
        if isinstance(resp, dict):
            choices = resp.get("choices")
            if isinstance(choices, list) and choices:
                first = choices[0]
                # chat-like message.content
                if isinstance(first, dict):
                    msg = first.get("message") or first.get("delta") or {}
                    if isinstance(msg, dict):
                        content = msg.get("content") or msg.get("text") or msg.get("content_text")
                        if content:
                            return str(content)
                    if first.get("text"):
                        return str(first.get("text"))
                if isinstance(first, str):
                    return first
            # fallback keys
            for k in ("output", "text", "data", "result"):
                v = resp.get(k)
                if isinstance(v, str):
                    return v
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    txt = v[0].get("text") or v[0].get("content")
                    if txt:
                        return txt
        # list of strings
        if isinstance(resp, list) and resp and isinstance(resp[0], str):
            return " ".join(resp)
    except Exception:
        logger.exception("normalize_response failed to parse resp")
    # fallback to string conversion
    return str(resp)


def _jitter_sleep_seconds(base: float, factor: float, attempt: int) -> float:
    # exponential backoff with jitter
    exp = base * (2 ** attempt)
    jitter = random.uniform(0, factor)
    return exp + jitter


def async_retry(
    retries: int = 3,
    base_delay: float = 0.5,
    jitter: float = 0.1,
    exceptions: Iterable[Exception] = (Exception,),
):
    """
    Async decorator for retrying functions with exponential backoff + jitter.
    Usage:
      @async_retry(retries=3)
      async def call(...): ...
    """
    def decorator(fn: Callable):
        async def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(retries + 1):
                try:
                    return await fn(*args, **kwargs)
                except tuple(exceptions) as exc:
                    last_exc = exc
                    if attempt >= retries:
                        logger.debug("async_retry: exhausted retries for %s", fn)
                        raise
                    delay = _jitter_sleep_seconds(base_delay, jitter, attempt)
                    logger.debug("async_retry: attempt=%d failed, sleeping %.2fs then retrying: %s", attempt + 1, delay, exc)
                    await asyncio.sleep(delay)
            # unreachable, but satisfy type check
            raise last_exc  # type: ignore
        return wrapper
    return decorator


def sync_retry(
    fn: Callable,
    retries: int = 3,
    base_delay: float = 0.5,
    jitter: float = 0.1,
    exceptions: Iterable[Exception] = (Exception,),
):
    """
    Synchronous retry helper: call sync functions with retries.
    """
    last_exc = None
    for attempt in range(retries + 1):
        try:
            return fn()
        except tuple(exceptions) as exc:
            last_exc = exc
            if attempt >= retries:
                raise
            delay = _jitter_sleep_seconds(base_delay, jitter, attempt)
            logger.debug("sync_retry: attempt=%d failed, sleeping %.2fs then retrying: %s", attempt + 1, delay, exc)
            # blocking sleep for sync path
            import time
            time.sleep(delay)
    raise last_exc  