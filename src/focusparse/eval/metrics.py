"""Aggregate metrics across a run.

TODO(Phase 4): add `compute_diagnostic_gaps` (full_doc vs oracle_page vs
oracle_crop), `lazy_answer_rate`, per-family / per-stress_type breakdown.
"""

from __future__ import annotations

from statistics import mean
from typing import Any

from pydantic import BaseModel


class AggregateMetrics(BaseModel):
    n: int
    accuracy: float
    page_recall_mean: float
    bbox_iou_mean: float
    evidence_reward_mean: float
    lazy_answer_rate: float
    tool_calls_mean: float
    tokens_in_mean: float
    tokens_out_mean: float
    usd_total: float
    usd_per_correct: float | None


def aggregate(per_example: list[dict[str, Any]]) -> AggregateMetrics:
    if not per_example:
        return AggregateMetrics(
            n=0, accuracy=0.0, page_recall_mean=0.0, bbox_iou_mean=0.0,
            evidence_reward_mean=0.0, lazy_answer_rate=0.0, tool_calls_mean=0.0,
            tokens_in_mean=0.0, tokens_out_mean=0.0, usd_total=0.0, usd_per_correct=None,
        )

    def col(k: str, default: float = 0.0) -> list[float]:
        return [float(r.get(k, default) or 0.0) for r in per_example]

    accuracy = mean(col("answer_correct"))
    n_correct = sum(1 for r in per_example if r.get("answer_correct"))
    usd_total = sum(col("usd"))

    return AggregateMetrics(
        n=len(per_example),
        accuracy=accuracy,
        page_recall_mean=mean(col("page_recall")),
        bbox_iou_mean=mean(col("bbox_iou")),
        evidence_reward_mean=mean(col("evidence_reward")),
        lazy_answer_rate=mean(col("is_lazy")),
        tool_calls_mean=mean(col("tool_calls")),
        tokens_in_mean=mean(col("tokens_in")),
        tokens_out_mean=mean(col("tokens_out")),
        usd_total=usd_total,
        usd_per_correct=(usd_total / n_correct) if n_correct else None,
    )
