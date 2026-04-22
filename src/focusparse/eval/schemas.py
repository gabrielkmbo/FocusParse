"""Per-config and per-run output schemas for HF matrix evaluation.

Shape chosen to mirror parser-bench's `EvalRunResults` so `matrix_summary.json`
is trivially comparable between the two repos. FocusParse-specific columns
(`evidence_reward_mean`, `lazy_answer_rate`, `tool_calls_mean`) are optional
and populated only on `focus` agent rows; `simple` rows leave them null so
side-by-side tables read cleanly.

These schemas are produced by `scripts/run_hf_eval.py` and consumed by
`scripts/run_hf_matrix.py` — the harness itself still returns its existing
`dict[str, Any]` shape and is not aware of this module.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PerProtocolResults(BaseModel):
    """Per-protocol aggregate. Matches parser-bench's `EvalRunResults` fields
    plus FocusParse additions."""

    accuracy: float
    abstain_rate: float
    page_recall: float
    bbox_iou: float
    count: int
    total_cost_usd: float | None = None
    cost_per_correct_usd: float | None = None
    total_input_tokens: int = 0
    total_output_tokens: int = 0

    # FocusParse additions — populated only for focus-agent runs.
    evidence_reward_mean: float | None = None
    lazy_answer_rate: float | None = None
    tool_calls_mean: float | None = None


class EvalRunResults(BaseModel):
    """One config's run. Filename: `focusparse_<agent>_<protocol>_<tier_sha8>.json`.

    `resolved_tiers` captures the full `{role: {provider, model, ...}}` snapshot
    after `--tier-override` + env; hashing this (sha256 → first 8 chars) is the
    source of `tier_sha8`, guaranteeing that any tier change produces a new
    filename and a cold prediction cache.
    """

    config_key: str
    agent: str
    protocol: str
    tier_sha8: str
    resolved_tiers: dict[str, dict] = Field(default_factory=dict)
    hf_repo: str
    hf_split: str
    hf_revision: str | None = None
    dataset_fingerprint: dict = Field(default_factory=dict)
    overall: PerProtocolResults
    per_example: list[dict] | None = None


__all__ = ["PerProtocolResults", "EvalRunResults"]
