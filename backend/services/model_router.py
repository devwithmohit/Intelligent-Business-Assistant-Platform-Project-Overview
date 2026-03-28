"""
Model router - simple rule/score based selection of LLM provider + model.

Provides:
- select_model(task_type, constraints=None) -> dict with keys:
    { "provider": str, "model": str, "reason": str }
- fallback_for(provider) -> str (fallback provider name)

This is intentionally lightweight and uses static catalog + optional overrides
from core.config.settings if available.
"""
from typing import Any, Dict, Iterable, Optional, Tuple
import os
import logging

logger = logging.getLogger(__name__)

# try to load runtime settings (optional)
try:
    from ..core import config as core_config  # type: ignore
    SETTINGS = core_config.settings
except Exception:
    SETTINGS = None  # type: ignore

# Default provider preference order
_DEFAULT_PREFERENCES: Iterable[str] = getattr(SETTINGS, "MODEL_PREFERENCES", ["openrouter", "deepseek"])

# Static model catalog (task -> provider/model). Update as needed.
_MODEL_CATALOG: Dict[str, Dict[str, Tuple[str, str]]] = {
    # task_type: { provider: (provider_name, model_name) }
    "chat": {
        "openrouter": ("openrouter", "gemini-chat-1"),
        "deepseek": ("deepseek", "deeps-chat-1"),
    },
    "content": {
        "openrouter": ("openrouter", "gemini-1"),
        "deepseek": ("deepseek", "deeps-content-1"),
    },
    "embeddings": {
        "deepseek": ("deepseek", "deeps-embed-1"),
        "openrouter": ("openrouter", "text-embedding-3"),
    },
    # default mapping used when task not recognized
    "default": {
        "openrouter": ("openrouter", "gemini-chat-1"),
        "deepseek": ("deepseek", "deeps-chat-1"),
    },
}

# Optional static provider metadata (cost/latency rough estimates)
_PROVIDER_STATS: Dict[str, Dict[str, Any]] = {
    "openrouter": {"cost_score": 2.0, "latency_ms": 200, "reliability": 0.98},
    "deepseek": {"cost_score": 1.5, "latency_ms": 300, "reliability": 0.97},
}


def _available_providers_for(task_type: str) -> Dict[str, Tuple[str, str]]:
    return _MODEL_CATALOG.get(task_type, _MODEL_CATALOG["default"])


def _score_provider(provider: str, constraints: Optional[Dict[str, Any]] = None) -> float:
    """
    Produce a simple score (higher is better) for provider based on static stats
    and constraints. constraints may include max_latency_ms, prefer_low_cost (bool),
    prefer_provider (str), avoid_providers (list).
    """
    stats = _PROVIDER_STATS.get(provider, {"cost_score": 2.0, "latency_ms": 500, "reliability": 0.9})
    score = 0.0

    # reliability contributes positively
    score += stats.get("reliability", 0.9) * 100

    # lower cost_score is better -> invert
    cost_score = stats.get("cost_score", 2.0)
    score += max(0.0, 50 - cost_score * 10)

    # lower latency slightly favored
    latency = stats.get("latency_ms", 500)
    score += max(0.0, 30 - (latency / 50))

    if not constraints:
        return score

    # prefer provider explicit hint
    prefer = constraints.get("prefer_provider")
    if prefer and provider == prefer:
        score += 50

    avoid = constraints.get("avoid_providers") or []
    if provider in avoid:
        score -= 1000

    max_latency = constraints.get("max_latency_ms")
    if max_latency is not None and latency > max_latency:
        score -= 200

    if constraints.get("prefer_low_cost"):
        # favor lower cost_score
        score += max(0.0, 20 - cost_score * 5)

    return score


def fallback_for(provider: str) -> Optional[str]:
    """
    Return a fallback provider name for a given provider according to preference order.
    """
    prefs = list(_DEFAULT_PREFERENCES)
    if provider not in prefs:
        prefs.insert(0, provider)
    for p in prefs:
        if p != provider:
            return p
    return None


def select_model(task_type: str, constraints: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Select the best provider+model for a given task_type.
    constraints (optional) can include:
      - prefer_provider: str
      - avoid_providers: list[str]
      - max_latency_ms: int
      - prefer_low_cost: bool
      - model_hint: str (explicit model name to prefer)
    Returns a dict: { provider, model, reason }
    """
    task_key = task_type if task_type in _MODEL_CATALOG else "default"
    candidates = _available_providers_for(task_key)

    if not candidates:
        # fallback to preferences
        provider = next(iter(_DEFAULT_PREFERENCES), "openrouter")
        model = _MODEL_CATALOG["default"].get(provider, ("openrouter", "gemini-chat-1"))[1]
        return {"provider": provider, "model": model, "reason": "no candidates, using default"}

    # if explicit model_hint provided, try to honor it by picking provider that exposes it
    model_hint = (constraints or {}).get("model_hint")
    if model_hint:
        for p, (_pname, model) in candidates.items():
            if model_hint.lower() in model.lower():
                return {"provider": p, "model": model, "reason": f"model_hint matched on provider {p}"}

    # score each candidate
    scored: Dict[str, float] = {}
    for p in candidates.keys():
        scored[p] = _score_provider(p, constraints)

    # choose highest score
    best_provider = max(scored.items(), key=lambda kv: kv[1])[0]
    provider_entry = candidates.get(best_provider)
    if not provider_entry:
        # defensive fallback to first candidate
        provider_entry = next(iter(candidates.values()))

    provider_name, model_name = provider_entry
    reason = f"selected by score ({best_provider})"
    logger.debug("model_router: task=%s candidates=%s scores=%s selected=%s", task_key, list(candidates.keys()), scored, best_provider)
    return {"provider": provider_name, "model": model_name, "reason": reason}
