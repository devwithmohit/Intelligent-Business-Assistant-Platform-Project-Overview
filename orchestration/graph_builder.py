import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


try:
    # try to use LangGraph if available
    from langgraph import Graph as LGGraph  # type: ignore
    _LANGGRAPH_AVAILABLE = True
except Exception:
    LGGraph = None  # type: ignore
    _LANGGRAPH_AVAILABLE = False


class GraphBuilderError(Exception):
    pass


class GraphBuilder:
    """
    Build workflows as node/edge graphs. If LangGraph is installed this will
    produce a LangGraph.Graph instance; otherwise keeps a minimal in-memory
    representation and can export to JSON or Mermaid for visualization.
    """

    def __init__(self, name: str = "workflow"):
        self.name = name
        self.nodes: Dict[str, Dict[str, Any]] = {}
        self.edges: List[Dict[str, Any]] = []
        self._agents: Dict[str, Dict[str, Any]] = {}  # agent_name -> metadata
        logger.debug("GraphBuilder initialized name=%s langgraph=%s", name, _LANGGRAPH_AVAILABLE)

    def register_agent(self, agent_name: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """
        Register an agent type that can be referenced by nodes.
        metadata can include entrypoint, version, capabilities.
        """
        self._agents[agent_name] = metadata or {}
        logger.debug("Registered agent %s metadata=%s", agent_name, metadata)

    def add_node(self, node_id: str, agent: str, config: Optional[Dict[str, Any]] = None, description: Optional[str] = None) -> None:
        """
        Add a node representing an agent/task in the workflow.
        node_id must be unique.
        """
        if node_id in self.nodes:
            raise GraphBuilderError(f"node already exists: {node_id}")
        if agent not in self._agents:
            logger.debug("Adding node referencing unregistered agent: %s", agent)
        self.nodes[node_id] = {"agent": agent, "config": config or {}, "description": description or ""}
        logger.debug("Added node %s -> agent=%s", node_id, agent)

    def add_edge(self, src: str, dst: str, condition: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> None:
        """
        Add a directed edge from src -> dst. Optional condition (string expression)
        can be used by executor to decide handoffs.
        """
        if src not in self.nodes or dst not in self.nodes:
            raise GraphBuilderError("both src and dst nodes must exist to create an edge")
        self.edges.append({"src": src, "dst": dst, "condition": condition, "metadata": metadata or {}})
        logger.debug("Added edge %s -> %s condition=%s", src, dst, condition)

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "agents": self._agents, "nodes": self.nodes, "edges": self.edges}

    def save_json(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        logger.info("Saved workflow JSON to %s", path)

    def export_mermaid(self) -> str:
        """
        Produce a simple Mermaid flowchart representation for quick visualization.
        Nodes are labeled with node_id and agent.
        """
        lines = ["flowchart LR"]
        for node_id, info in self.nodes.items():
            label = f"{node_id}\\n({info.get('agent')})"
            lines.append(f'    {node_id}["{label}"]')
        for e in self.edges:
            cond = f'|{e["condition"]}|' if e.get("condition") else ""
            lines.append(f'    {e["src"]} -->{cond} {e["dst"]}')
        return "\n".join(lines)

    def build_langgraph(self):
        """
        If LangGraph is available, convert the internal representation into a LangGraph.Graph.
        Returns the LangGraph graph instance.
        """
        if not _LANGGRAPH_AVAILABLE:
            raise GraphBuilderError("LangGraph not installed; cannot build LangGraph graph")

        g = LGGraph(name=self.name)
        # add nodes; store mapping in case LG node objects required
        lg_nodes = {}
        for nid, info in self.nodes.items():
            # minimal node representation: id + metadata
            lg_node = g.add_node(nid, {"agent": info.get("agent"), "config": info.get("config"), "description": info.get("description")})
            lg_nodes[nid] = lg_node

        for e in self.edges:
            src = e["src"]
            dst = e["dst"]
            cond = e.get("condition")
            # langgraph add_edge signature may differ; attempt common API
            if hasattr(g, "add_edge"):
                try:
                    g.add_edge(src, dst, condition=cond, metadata=e.get("metadata"))
                except TypeError:
                    # fallback: add_edge(src, dst)
                    g.add_edge(src, dst)
            else:
                logger.warning("LangGraph Graph has no add_edge method; skipping edge %s->%s", src, dst)
        return g
