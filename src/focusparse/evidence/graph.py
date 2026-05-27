"""Lightweight per-question evidence graph.

Nodes: evidence regions we inspected. Edges: linked-neighbor relations (legend→chart,
footnote→table, etc). Built incrementally during the INSPECT + EXPAND_CONTEXT stages.

TODO(Phase 2): implement graph-aware context expansion. For now this is a seam
other modules can import.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EvidenceNode:
    node_id: str
    page: int
    bbox_norm: tuple[float, float, float, float]
    region_type: str | None = None


@dataclass
class EvidenceEdge:
    source: str
    target: str
    edge_type: str  # parser_bench EdgeType value


@dataclass
class RunEvidenceGraph:
    """Per-question graph accumulated during a workflow run."""

    nodes: dict[str, EvidenceNode] = field(default_factory=dict)
    edges: list[EvidenceEdge] = field(default_factory=list)

    def add_node(self, node: EvidenceNode) -> None:
        self.nodes[node.node_id] = node

    def neighbors(self, node_id: str) -> list[EvidenceNode]:
        out: list[EvidenceNode] = []
        for e in self.edges:
            if e.source == node_id and e.target in self.nodes:
                out.append(self.nodes[e.target])
            elif e.target == node_id and e.source in self.nodes:
                out.append(self.nodes[e.source])
        return out
