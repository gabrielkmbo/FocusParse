"""EXPAND_CONTEXT stage — attach linked neighbors to each evidence region.

Phase 2 skeleton: identity pass-through. The real expander (sub-phase 2e)
consults the evidence graph and attaches legend/footnote/caption neighbors.

Phase 2e strategy:
  - For each inspected region, consult the evidence graph for known neighbors
    (legend, footnote, caption, header row).
  - For regions without graph data, heuristic margin-expand:
      * table rows: include top 30px header band + bottom 40px note band
      * chart crops: include surrounding legend + caption + axis strips
      * datasheet spec cells: include column header + condition column
  - Cap the per-packet neighbor count at 4 to keep packets compact.
"""

from __future__ import annotations

from focusparse.pipeline.events import EvidenceEvent


async def expand_context(evidence: EvidenceEvent) -> EvidenceEvent:
    """Skeleton: pass packets through unchanged."""
    return evidence
