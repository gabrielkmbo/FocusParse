"""Visual page reranker — DEFERRED per plan §8.2.

v1 skips visual rerank entirely. This file exists only as a seam so future
ablation code has a stable import path. DO NOT import in v1; router.py must
not reference this module.

Phase 5 ablation options:
  (a) deploy llamaindex/vdr-2b-multi-v1 to an HF Inference Endpoint
  (b) run locally via sentence-transformers behind [visual-rerank] extra

Decision deferred until we pick (a) vs (b) when we need the ablation row.
"""

from __future__ import annotations


class VisualReranker:
    """Stub — do not import in v1."""

    def __init__(self) -> None:
        raise NotImplementedError(
            "Visual rerank is deferred (plan §8.2). Do not import in v1."
        )
