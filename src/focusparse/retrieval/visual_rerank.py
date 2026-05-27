"""Optional visual page reranker seam.

The public paper path uses text/layout routing. This seam is retained for a
future visual-rerank ablation behind the optional `visual-rerank` extra; router
code should not import it by default.

Phase 5 ablation options:
  (a) deploy llamaindex/vdr-2b-multi-v1 to an HF Inference Endpoint
  (b) run locally via sentence-transformers behind [visual-rerank] extra

Decision deferred until we pick (a) vs (b) when we need the ablation row.
"""

from __future__ import annotations


class VisualReranker:
    """Deferred optional visual-rerank adapter."""

    def __init__(self) -> None:
        raise NotImplementedError("Visual rerank is deferred; do not import in default runs.")
