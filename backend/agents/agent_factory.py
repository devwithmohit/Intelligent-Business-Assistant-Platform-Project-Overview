import importlib
import inspect
import logging
from typing import Any, Dict, List, Optional, Type

from .base_agent import BaseAgent

logger = logging.getLogger(__name__)

# static registry: agent_type -> Agent class (populated lazily)
_AGENT_REGISTRY: Dict[str, Type[BaseAgent]] = {}


class AgentFactoryError(Exception):
    pass


class AgentNotFound(AgentFactoryError):
    pass


def register_agent(agent_type: str, cls: Type[BaseAgent]) -> None:
    """
    Register an Agent class for a given agent_type key.
    """
    if not issubclass(cls, BaseAgent):
        raise TypeError("cls must be subclass of BaseAgent")
    _AGENT_REGISTRY[agent_type] = cls
    logger.debug("Registered agent type=%s class=%s", agent_type, cls.__name__)


def _discover_agent_class(module_name: str) -> Optional[Type[BaseAgent]]:
    """
    Import module and return first subclass of BaseAgent found.
    """
    try:
        mod = importlib.import_module(module_name)
    except Exception as e:
        logger.debug("Failed to import agent module %s: %s", module_name, e)
        return None

    for _, obj in inspect.getmembers(mod, inspect.isclass):
        if issubclass(obj, BaseAgent) and obj is not BaseAgent:
            logger.debug("Discovered agent class %s in %s", obj.__name__, module_name)
            return obj
    return None


def _ensure_registered(agent_type: str) -> None:
    """
    Ensure registry has an entry for agent_type by attempting to import common module locations.
    Common module paths:
      backend.agents.<agent_type>.agent
      backend.agents.<agent_type>
    """
    if agent_type in _AGENT_REGISTRY:
        return

    candidates: List[str] = [
        f"backend.agents.{agent_type}.agent",
        f"backend.agents.{agent_type}",
        f"backend.agents.{agent_type}.agent_module",
    ]
    for mod in candidates:
        cls = _discover_agent_class(mod)
        if cls:
            register_agent(agent_type, cls)
            return


def create_agent(agent_type: str, name: Optional[str] = None, config: Optional[Dict[str, Any]] = None) -> BaseAgent:
    """
    Instantiate an agent by type.
    - agent_type: e.g. "customer_service", "sales_research", "content_creation"
    - name: optional human-readable name
    - config: optional config dict passed to agent constructor
    Raises AgentNotFound if no agent implementation is available.
    """
    _ensure_registered(agent_type)
    cls = _AGENT_REGISTRY.get(agent_type)
    if not cls:
        raise AgentNotFound(f"No agent implementation found for type: {agent_type}")
    try:
        return cls(name=name or agent_type, config=config or {})
    except Exception as e:
        logger.exception("Failed to instantiate agent type=%s", agent_type)
        raise AgentFactoryError(f"Failed to instantiate agent {agent_type}: {e}") from e


def available_agent_types() -> List[str]:
    """
    Return list of currently registered/discoverable agent types.
    """
    # attempt to discover common directories under backend.agents
    # (this keeps discovery lazy; callers can still register manually)
    try:
        import pkgutil
        import backend.agents as agents_pkg  # type: ignore

        for finder, name, ispkg in pkgutil.iter_modules(agents_pkg.__path__):  # type: ignore
            # only register if not already present
            if name not in _AGENT_REGISTRY:
                _ensure_registered(name)
    except Exception:
        # non-fatal
        pass

    return list(_AGENT_REGISTRY.keys())
