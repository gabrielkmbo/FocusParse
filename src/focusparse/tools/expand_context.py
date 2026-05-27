"""expand_context — fetch linked neighbors for a region.

Consult the evidence graph if one exists; otherwise heuristic margin-expansion.
TODO(Phase 2): implement graph-aware + heuristic paths.
"""

from __future__ import annotations

from pydantic import BaseModel


class ExpandContextInput(BaseModel):
    doc_id: str
    page: int
    bbox_norm: tuple[float, float, float, float]
    link_hints: list[str] = []  # e.g. ["legend", "footnote", "caption"]


class ExpandContextOutput(BaseModel):
    neighbor_refs: list[str] = []
    neighbor_types: list[str] = []


async def expand_context(inp: ExpandContextInput) -> ExpandContextOutput:
    raise NotImplementedError("expand_context — wire in Phase 2")
