import json
import logging
import os
from typing import Any, Dict, List, Optional

from orchestration.graph_builder import GraphBuilder, GraphBuilderError
from orchestration.state_management import StateManager, get_state_manager
from orchestration.visualizer import Visualizer
from orchestration.workflow_executor import WorkflowExecutor

from ..schemas import orchestration_schemas as _schemas

logger = logging.getLogger(__name__)


class WorkflowServiceError(Exception):
    pass


class WorkflowService:
    """
    High-level service for workflow CRUD, execution and monitoring.
    - Stores workflow definitions on disk (JSON) under persist_dir
    - Keeps an in-memory registry of GraphBuilder instances for quick execution
    """

    def __init__(
        self,
        persist_dir: Optional[str] = None,
        state_manager: Optional[StateManager] = None,
    ):
        self.persist_dir = (
            persist_dir
            or os.getenv("WORKFLOW_DIR")
            or os.path.join(os.getcwd(), "data", "workflows")
        )
        os.makedirs(self.persist_dir, exist_ok=True)
        self._graphs: Dict[str, GraphBuilder] = {}
        self._defs: Dict[str, _schemas.WorkflowDefinition] = {}
        self.state_manager = state_manager or get_state_manager()
        self.executor = WorkflowExecutor(state_manager=self.state_manager)
        logger.debug("WorkflowService initialized persist_dir=%s", self.persist_dir)
        # load existing workflow files
        self._load_existing()

    def _path_for(self, name: str) -> str:
        safe = name.replace("/", "_")
        return os.path.join(self.persist_dir, f"{safe}.json")

    def _load_existing(self) -> None:
        for fname in os.listdir(self.persist_dir):
            if not fname.endswith(".json"):
                continue
            path = os.path.join(self.persist_dir, fname)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    payload = json.load(fh)
                defn = _schemas.WorkflowDefinition(**payload)
                self._defs[defn.name] = defn
                self._graphs[defn.name] = self._build_graph_from_definition(defn)
                logger.debug("Loaded workflow definition %s from %s", defn.name, path)
            except Exception:
                logger.debug("Failed to load workflow file %s", path, exc_info=True)

    def _persist_definition(self, defn: _schemas.WorkflowDefinition) -> None:
        path = self._path_for(defn.name)
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(defn.model_dump_json(indent=2))
            logger.info("Persisted workflow definition %s -> %s", defn.name, path)
        except Exception as e:
            logger.exception("Failed to persist workflow %s: %s", defn.name, e)
            raise WorkflowServiceError(str(e)) from e

    def _build_graph_from_definition(
        self, defn: _schemas.WorkflowDefinition
    ) -> GraphBuilder:
        g = GraphBuilder(name=defn.name)
        # register agents metadata if present
        for ag_name, meta in (defn.agents or {}).items():
            g.register_agent(ag_name, metadata=meta)
        # add nodes
        for node in defn.nodes:
            g.add_node(
                node.id,
                agent=node.agent,
                config=node.config or {},
                description=node.description,
            )
        # add edges
        for edge in defn.edges:
            g.add_edge(
                edge.src,
                edge.dst,
                condition=edge.condition,
                metadata=edge.metadata or {},
            )
        return g

    async def create_workflow(
        self, defn: _schemas.WorkflowDefinition
    ) -> Dict[str, Any]:
        if defn.name in self._defs:
            raise WorkflowServiceError(f"workflow exists: {defn.name}")
        try:
            graph = self._build_graph_from_definition(defn)
        except GraphBuilderError as e:
            raise WorkflowServiceError(str(e)) from e
        # store
        self._defs[defn.name] = defn
        self._graphs[defn.name] = graph
        self._persist_definition(defn)
        return {"name": defn.name, "nodes": len(defn.nodes), "edges": len(defn.edges)}

    async def update_workflow(
        self, defn: _schemas.WorkflowDefinition
    ) -> Dict[str, Any]:
        if defn.name not in self._defs:
            raise WorkflowServiceError(f"workflow not found: {defn.name}")
        try:
            graph = self._build_graph_from_definition(defn)
        except GraphBuilderError as e:
            raise WorkflowServiceError(str(e)) from e
        self._defs[defn.name] = defn
        self._graphs[defn.name] = graph
        self._persist_definition(defn)
        return {"name": defn.name, "updated": True}

    async def delete_workflow(self, name: str) -> None:
        if name in self._defs:
            del self._defs[name]
        if name in self._graphs:
            del self._graphs[name]
        path = self._path_for(name)
        try:
            if os.path.exists(path):
                os.remove(path)
                logger.info("Deleted workflow file %s", path)
        except Exception:
            logger.debug("Failed to remove workflow file %s", path, exc_info=True)

    async def list_workflows(self) -> List[Dict[str, Any]]:
        return [
            {"name": n, "nodes": len(d.nodes), "edges": len(d.edges)}
            for n, d in self._defs.items()
        ]

    async def get_workflow(self, name: str) -> Optional[_schemas.WorkflowDefinition]:
        return self._defs.get(name)

    async def start(
        self,
        workflow_name: str,
        start_node: str,
        initial_context: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        graph = self._graphs.get(workflow_name)
        if not graph:
            raise WorkflowServiceError(f"workflow not found: {workflow_name}")
        return await self.executor.start(
            graph=graph,
            start_node=start_node,
            initial_context=initial_context,
            metadata=metadata,
        )

    async def run_and_wait(
        self,
        workflow_name: str,
        start_node: str,
        initial_context: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        graph = self._graphs.get(workflow_name)
        if not graph:
            raise WorkflowServiceError(f"workflow not found: {workflow_name}")
        return await self.executor.run_and_wait(
            graph=graph,
            start_node=start_node,
            initial_context=initial_context,
            metadata=metadata,
            timeout=timeout,
        )

    async def get_instance(self, instance_id: str) -> Optional[Dict[str, Any]]:
        st = await self.state_manager.get_instance(instance_id)
        if not st:
            return None
        return {
            "id": st.id,
            "workflow_name": st.workflow_name,
            "context": st.context,
            "metadata": st.metadata,
            "created_at": st.created_at,
            "updated_at": st.updated_at,
        }

    async def list_instances(self) -> Dict[str, Any]:
        return await self.state_manager.list_instances()

    async def snapshot_instance(
        self, instance_id: str, out_path: Optional[str] = None
    ) -> str:
        return await self.state_manager.snapshot_instance(
            instance_id, out_path=out_path
        )

    async def export_visualization(
        self, workflow_name: str, out_dir: Optional[str] = None
    ) -> Dict[str, str]:
        graph = self._graphs.get(workflow_name)
        if not graph:
            raise WorkflowServiceError(f"workflow not found: {workflow_name}")
        out_dir = out_dir or os.path.join(self.persist_dir, "visuals")
        os.makedirs(out_dir, exist_ok=True)
        viz = Visualizer(graph)
        mermaid_p = os.path.join(out_dir, f"{workflow_name}.mmd")
        dot_p = os.path.join(out_dir, f"{workflow_name}.dot")
        viz.save_mermaid(mermaid_p)
        viz.save_dot(dot_p)
        svg_bytes = viz.render_svg()
        svg_p = None
        if svg_bytes:
            svg_p = os.path.join(out_dir, f"{workflow_name}.svg")
            viz.save_svg(svg_p, svg_bytes) if hasattr(viz, "save_svg") else None
        return {"mermaid": mermaid_p, "dot": dot_p, "svg": svg_p or ""}


# module-level singleton
_default_workflow_service: Optional[WorkflowService] = None


def get_workflow_service() -> WorkflowService:
    global _default_workflow_service
    if _default_workflow_service is None:
        _default_workflow_service = WorkflowService()
    return _default_workflow_service
