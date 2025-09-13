import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _ensure_graph_dict(graph: Any) -> Dict[str, Any]:
    """
    Accept GraphBuilder instance or plain dict produced by GraphBuilder.to_dict()
    and return a normalized dict with 'nodes' and 'edges'.
    """
    if hasattr(graph, "to_dict"):
        return graph.to_dict()
    if isinstance(graph, dict):
        return graph
    raise TypeError("graph must be GraphBuilder or dict")


def graph_to_mermaid(graph: Any) -> str:
    """
    Produce a Mermaid flowchart string for the graph.
    If the graph object implements export_mermaid(), use that.
    """
    if hasattr(graph, "export_mermaid"):
        try:
            return graph.export_mermaid()
        except Exception:
            logger.debug("export_mermaid failed; falling back to dict->mermaid")
    g = _ensure_graph_dict(graph)
    lines = ["flowchart LR"]
    for nid, info in (g.get("nodes") or {}).items():
        agent = info.get("agent") if isinstance(info, dict) else None
        label = f"{nid}\\n({agent})" if agent else nid
        lines.append(f'    {nid}["{label}"]')
    for e in g.get("edges") or []:
        cond = f"|{e.get('condition')}| " if e.get("condition") else ""
        lines.append(f"    {e['src']} -->{cond}{e['dst']}")
    return "\n".join(lines)


def graph_to_dot(graph: Any) -> str:
    """
    Produce a Graphviz DOT representation for the graph.
    """
    g = _ensure_graph_dict(graph)
    lines = ["digraph workflow {", "  rankdir=LR;"]
    # nodes
    for nid, info in (g.get("nodes") or {}).items():
        agent = info.get("agent") if isinstance(info, dict) else None
        label = f"{nid}\\n({agent})" if agent else nid
        lines.append(f'  "{nid}" [label="{label}", shape=box];')
    # edges with optional condition as label
    for e in g.get("edges") or []:
        lbl = ""
        if e.get("condition"):
            lbl = f' [label="{e.get("condition")}"]'
        lines.append(f'  "{e["src"]}" -> "{e["dst"]}"{lbl};')
    lines.append("}")
    return "\n".join(lines)


def render_dot_to_svg(dot_src: str) -> Optional[bytes]:
    """
    Try to render DOT -> SVG using graphviz Python bindings. Returns SVG bytes or None.
    """
    try:
        import graphviz  # type: ignore

        src = graphviz.Source(dot_src)
        return src.pipe(format="svg")
    except Exception:
        logger.debug(
            "graphviz not available or render failed; returning None", exc_info=True
        )
        return None


def save_text(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    logger.info("Saved visualization to %s", path)


def save_svg(path: str, svg_bytes: bytes) -> None:
    with open(path, "wb") as fh:
        fh.write(svg_bytes)
    logger.info("Saved SVG to %s", path)


class Visualizer:
    """
    Convenience wrapper to generate and persist workflow visualizations.
    """

    def __init__(self, graph: Any) -> None:
        self.graph = graph

    def mermaid(self) -> str:
        return graph_to_mermaid(self.graph)

    def dot(self) -> str:
        return graph_to_dot(self.graph)

    def render_svg(self) -> Optional[bytes]:
        return render_dot_to_svg(self.dot())

    def save_mermaid(self, path: str) -> None:
        save_text(path, self.mermaid())

    def save_dot(self, path: str) -> None:
        save_text(path, self.dot())

    def save_svg(self, path: str) -> None:
        svg = self.render_svg()
        if svg:
            save_svg(path, svg)
        else:
            # fallback: write DOT if SVG render not available
            logger.warning("SVG render unavailable, saving DOT as fallback to %s", path)
            save_text(path, self.dot())
