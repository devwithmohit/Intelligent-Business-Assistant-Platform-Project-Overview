import ast
import asyncio
import logging
from typing import Any, Dict, List, Optional

from .graph_builder import GraphBuilder

logger = logging.getLogger(__name__)


class RoutingError(Exception):
    pass


def _eval_ast(node: ast.AST, ctx: Dict[str, Any]) -> Any:
    """Recursive safe AST evaluator. Supports bool/compare/binops, names -> ctx lookup, subscripts."""
    if isinstance(node, ast.Expression):
        return _eval_ast(node.body, ctx)
    if isinstance(node, ast.BoolOp):
        vals = [_eval_ast(v, ctx) for v in node.values]
        if isinstance(node.op, ast.And):
            return all(vals)
        if isinstance(node.op, ast.Or):
            return any(vals)
    if isinstance(node, ast.Compare):
        left = _eval_ast(node.left, ctx)
        for op, comparator in zip(node.ops, node.comparators):
            right = _eval_ast(comparator, ctx)
            if isinstance(op, ast.Eq) and not (left == right):
                return False
            if isinstance(op, ast.NotEq) and not (left != right):
                return False
            if isinstance(op, ast.Lt) and not (left < right):
                return False
            if isinstance(op, ast.LtE) and not (left <= right):
                return False
            if isinstance(op, ast.Gt) and not (left > right):
                return False
            if isinstance(op, ast.GtE) and not (left >= right):
                return False
            left = right
        return True
    if isinstance(node, ast.BinOp):
        a = _eval_ast(node.left, ctx)
        b = _eval_ast(node.right, ctx)
        if isinstance(node.op, ast.Add):
            return a + b
        if isinstance(node.op, ast.Sub):
            return a - b
        if isinstance(node.op, ast.Mult):
            return a * b
        if isinstance(node.op, ast.Div):
            return a / b
        if isinstance(node.op, ast.Mod):
            return a % b
    if isinstance(node, ast.UnaryOp):
        val = _eval_ast(node.operand, ctx)
        if isinstance(node.op, ast.Not):
            return not val
        if isinstance(node.op, ast.USub):
            return -val
        if isinstance(node.op, ast.UAdd):
            return +val
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        # lookup in context; missing -> None
        return ctx.get(node.id)
    if isinstance(node, ast.Subscript):
        container = _eval_ast(node.value, ctx)
        index = _eval_ast(node.slice, ctx) if not isinstance(node.slice, ast.Index) else _eval_ast(node.slice.value, ctx)
        try:
            return container[index]
        except Exception:
            return None
    if isinstance(node, ast.Index):  # type: ignore
        return _eval_ast(node.value, ctx)  # type: ignore
    if isinstance(node, ast.Call):
        # disallow calls for safety
        raise RoutingError("Function calls in conditions are not allowed")
    # unsupported node
    raise RoutingError(f"Unsupported expression node: {type(node).__name__}")


def evaluate_condition(condition: Optional[str], context: Dict[str, Any]) -> bool:
    """
    Safely evaluate a condition string against provided context.
    Condition examples:
      - "score > 0.8"
      - "intent == 'escalate'"
      - "context['priority'] >= 5 and success == True"
    Returns True if condition is empty/None (treat as unconditional).
    """
    if not condition:
        return True
    try:
        parsed = ast.parse(condition, mode="eval")
        return bool(_eval_ast(parsed, context))
    except RoutingError:
        logger.exception("Condition evaluation blocked or failed for: %s", condition)
        return False
    except Exception:
        logger.exception("Error evaluating condition: %s", condition)
        return False


def select_next_nodes(graph: GraphBuilder, current_node: str, context: Dict[str, Any]) -> List[str]:
    """
    Given a GraphBuilder instance, returns list of destination node ids whose
    edge conditions evaluate to true. If no outgoing edges, returns empty list.
    If one or more outgoing edges have no condition, those are preferred.
    """
    outs = [e for e in graph.edges if e["src"] == current_node]
    if not outs:
        return []
    # if any unconditional edges, return them
    unconditional = [e for e in outs if not e.get("condition")]
    if unconditional:
        return [e["dst"] for e in unconditional]
    # otherwise evaluate conditions
    next_nodes: List[str] = []
    for e in outs:
        cond = e.get("condition")
        try:
            if evaluate_condition(cond, context):
                next_nodes.append(e["dst"])
        except Exception:
            logger.debug("Condition evaluation error for edge %s->%s", e["src"], e["dst"])
            continue
    return next_nodes


class AgentRunner:
    """
    Thin adapter invoking agent execution. Implementation should provide async run_agent(agent_name, instance_id, node_config, context)
    Try to import project agent_service; fallback to raise if not available.
    """

    def __init__(self):
        try:
            from backend.services import agent_service  # type: ignore
            self._svc = agent_service
        except Exception:
            self._svc = None

    async def run_agent(self, agent_name: str, instance_id: str, node_config: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Run an agent node and return a result dict. Expected result keys:
          - context_updates: Dict[str, Any] (partial context to merge)
          - handoff_to_node: Optional[str] (explicit next node override)
          - status: "ok" | "error"
          - detail: optional message
        """
        if self._svc and getattr(self._svc, "run_agent_node", None):
            return await self._svc.run_agent_node(agent_name=agent_name, instance_id=instance_id, config=node_config, context=context)
        raise RoutingError("No agent_service.run_agent_node available to execute agent")

    
async def route_and_execute(
    instance_id: str,
    current_node: str,
    graph: GraphBuilder,
    state_manager,
    agent_runner: Optional[AgentRunner] = None,
) -> List[str]:
    """
    Determine next nodes from current_node, execute corresponding agents, update state,
    and return the list of nodes to continue execution from (may be empty).
    - state_manager: object with get_instance & update_instance async methods
    - agent_runner: optional AgentRunner instance
    """
    agent_runner = agent_runner or AgentRunner()
    state = await state_manager.get_instance(instance_id)
    if not state:
        raise RoutingError(f"Workflow instance not found: {instance_id}")
    context = dict(state.context or {})
    next_nodes = select_next_nodes(graph, current_node, context)

    resolved_next: List[str] = []
    for node_id in next_nodes:
        node = graph.nodes.get(node_id)
        if not node:
            logger.warning("Node not found in graph: %s", node_id)
            continue
        agent_name = node.get("agent")
        config = node.get("config", {}) or {}
        try:
            result = await agent_runner.run_agent(agent_name=agent_name, instance_id=instance_id, node_config=config, context=context)
        except Exception as e:
            logger.exception("Agent run failed for %s on node %s: %s", agent_name, node_id, e)
            # record failure into state metadata and continue
            await state_manager.update_instance(instance_id, {"metadata": {"last_error": str(e)}})
            continue

        # apply context updates
        updates = result.get("context_updates") or {}
        if updates:
            await state_manager.update_instance(instance_id, {"context": updates}, merge=True)
            # refresh context for subsequent nodes in same step
            context.update(updates)

        # explicit handoff override
        handoff = result.get("handoff_to_node")
        if handoff:
            if isinstance(handoff, str):
                resolved_next.append(handoff)
            elif isinstance(handoff, list):
                resolved_next.extend(handoff)
        else:
            # default: follow outgoing edges from this node in next iteration
            downstream = select_next_nodes(graph, node_id, context)
            resolved_next.extend(downstream)

    # dedupe while preserving order
    seen = set()
    deduped = []
    for n in resolved_next:
        if n not in seen:
            seen.add(n)
            deduped.append(n)
    return deduped
