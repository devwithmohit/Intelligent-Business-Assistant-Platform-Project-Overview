import argparse
import asyncio
import importlib
import logging
import pkgutil
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from orchestration.graph_builder import GraphBuilder
from orchestration.state_management import StateManager
from orchestration.workflow_executor import WorkflowExecutor

logger = logging.getLogger("backend.cli.workflow_tool")
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def discover_builtin_workflows(
    pkg_name: str = "orchestration.workflows",
) -> Dict[str, Callable[[], GraphBuilder]]:
    """
    Discover modules under orchestration.workflows and return mapping name->builder_fn.
    """
    builders: Dict[str, Callable[[], GraphBuilder]] = {}
    try:
        pkg = importlib.import_module(pkg_name)
    except Exception:
        return builders
    for finder, name, ispkg in pkgutil.iter_modules(pkg.__path__):
        mod_name = f"{pkg_name}.{name}"
        try:
            mod = importlib.import_module(mod_name)
            # common convention: build_<workflow> functions or build_<name> matching module
            for attr in dir(mod):
                if attr.startswith("build_"):
                    fn = getattr(mod, attr)
                    if callable(fn):
                        key = getattr(fn, "__name__", attr)
                        builders[key] = fn  # caller can inspect builder name
        except Exception:
            logger.debug("Failed to import workflow module %s", mod_name, exc_info=True)
    return builders


class _MockAgentRunner:
    """Simple deterministic runner for CLI demo/testing."""

    async def run_agent(
        self,
        agent_name: str,
        instance_id: str,
        node_config: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        # minimal: record that node ran and optionally mark finished
        await asyncio.sleep(0)  # cooperative yield
        # if node indicates finalize, set finished flag
        updates = {}
        if node_config.get("finalize") or node_config.get("step") == "finalize":
            updates["finished"] = True
        return {"context_updates": updates, "status": "ok"}


async def _run_builder(
    builder_fn: Callable[[], GraphBuilder],
    start_node: str,
    wait: bool,
    timeout: Optional[float],
    mock_agents: bool,
    out_dir: Optional[Path],
) -> None:
    g = builder_fn()
    # show mermaid when requested
    logger.info("Workflow: %s (nodes=%d edges=%d)", g.name, len(g.nodes), len(g.edges))
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        mpath = out_dir / f"{g.name}.mmd"
        g.save_json(str(out_dir / f"{g.name}.json"))
        with open(mpath, "w", encoding="utf-8") as fh:
            fh.write(g.export_mermaid())
        logger.info("Saved mermaid to %s", mpath)

    state_mgr = StateManager(persist_dir=str(Path.cwd() / "data" / "workflow_states"))
    agent_runner = _MockAgentRunner() if mock_agents else None
    executor = WorkflowExecutor(state_manager=state_mgr, agent_runner=agent_runner)

    if wait:
        res = await executor.run_and_wait(
            graph=g, start_node=start_node, timeout=timeout
        )
        logger.info(
            "Run complete instance=%s context=%s", res.get("id"), res.get("context")
        )
    else:
        inst_id = await executor.start(graph=g, start_node=start_node)
        logger.info("Started instance %s (background)", inst_id)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="CLI to run/test workflow templates locally"
    )
    ap.add_argument(
        "--list", "-l", action="store_true", help="List discovered built-in workflows"
    )
    ap.add_argument(
        "--show",
        "-s",
        metavar="WORKFLOW",
        help="Show mermaid for a named builder (use function name e.g. build_customer_support_flow)",
    )
    ap.add_argument(
        "--run",
        "-r",
        metavar="WORKFLOW",
        help="Run selected workflow (builder function name)",
    )
    ap.add_argument(
        "--start-node", "-n", default="start", help="Start node id to execute from"
    )
    ap.add_argument(
        "--wait", action="store_true", help="Run and wait for completion (blocking)"
    )
    ap.add_argument(
        "--timeout", type=float, default=30.0, help="Timeout seconds for run-and-wait"
    )
    ap.add_argument(
        "--mock-agents",
        action="store_true",
        help="Use a mock agent runner instead of project agent_service (good for local testing)",
    )
    ap.add_argument(
        "--out-dir",
        type=str,
        default=None,
        help="Directory to dump workflow visuals/JSON",
    )
    args = ap.parse_args()

    builders = discover_builtin_workflows("orchestration.workflows")
    if args.list:
        if not builders:
            logger.info("No built-in workflows discovered")
            return
        logger.info("Discovered workflow builders:")
        for k in sorted(builders.keys()):
            logger.info("  %s", k)
        return

    if args.show:
        fn = builders.get(args.show)
        if not fn:
            logger.error("Workflow builder not found: %s", args.show)
            return
        g = fn()
        print(g.export_mermaid())
        return

    if args.run:
        fn = builders.get(args.run)
        if not fn:
            logger.error("Workflow builder not found: %s", args.run)
            return
        out_dir = Path(args.out_dir) if args.out_dir else None
        try:
            asyncio.run(
                _run_builder(
                    fn,
                    start_node=args.start_node,
                    wait=args.wait,
                    timeout=args.timeout,
                    mock_agents=args.mock_agents,
                    out_dir=out_dir,
                )
            )
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        return

    ap.print_help()


if __name__ == "__main__":
    main()
