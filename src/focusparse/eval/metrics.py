"""Aggregate metrics across a run.

Two flavors:

- `aggregate(per_example)` — one set of numbers across all examples.
- `aggregate_by_domain(per_example)` — bucketed by `record["domain"]` so the
  headline 4-method × 2-task × 2-metric table can be filled per domain.
  Always includes `_overall` as the union for sanity-checking.

Both flavors carry 95% bootstrap CIs on `accuracy` and `usd_per_correct` so
small slices (e.g. n=47 finance) report sampling noise honestly. CI seed is
fixed at 42 for reproducibility.

TODO(Phase 4): per-family / per-stress_type breakdown, `compute_diagnostic_gaps`.
"""

from __future__ import annotations

import random
from statistics import mean
from typing import Any

from pydantic import BaseModel, Field

# Default 1000 resamples is the sweet spot for n in [30, 200] — fast (<1s per
# cell) and stable (CI moves < 1pp across re-seeds at this resample count).
_DEFAULT_BOOTSTRAP_RESAMPLES = 1000
_DEFAULT_BOOTSTRAP_SEED = 42


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
    # 95% bootstrap CIs (lo, hi). Empty tuples on n < 2 — bootstrap is
    # undefined for a single sample. The caller writes them as JSON-friendly
    # `[lo, hi]` lists.
    accuracy_ci: tuple[float, float] = Field(default=(0.0, 0.0))
    usd_per_correct_ci: tuple[float, float] | None = None


def bootstrap_ci(
    values: list[float],
    *,
    n_resamples: int = _DEFAULT_BOOTSTRAP_RESAMPLES,
    seed: int = _DEFAULT_BOOTSTRAP_SEED,
    confidence: float = 0.95,
) -> tuple[float, float]:
    """95% percentile-bootstrap CI on the mean of `values`.

    Returns (lo, hi). Falls back to (0.0, 0.0) when n < 2 because the
    bootstrap is undefined for a single sample.
    """
    if len(values) < 2:
        return (0.0, 0.0)
    rng = random.Random(seed)
    n = len(values)
    means: list[float] = []
    for _ in range(n_resamples):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    alpha = (1.0 - confidence) / 2.0
    lo_idx = max(0, int(alpha * n_resamples))
    hi_idx = min(n_resamples - 1, int((1.0 - alpha) * n_resamples))
    return (means[lo_idx], means[hi_idx])


def _bootstrap_usd_per_correct_ci(
    correct: list[float],
    usd: list[float],
    *,
    n_resamples: int = _DEFAULT_BOOTSTRAP_RESAMPLES,
    seed: int = _DEFAULT_BOOTSTRAP_SEED,
    confidence: float = 0.95,
) -> tuple[float, float] | None:
    """Bootstrap CI on `sum(usd) / sum(correct)` (ratio statistic).

    Resample the (correct, usd) pair so the numerator and denominator are
    bootstrapped together. Returns None when no resample produces any
    correct example (CI undefined for divide-by-zero).
    """
    if len(correct) < 2 or len(correct) != len(usd):
        return None
    rng = random.Random(seed)
    n = len(correct)
    ratios: list[float] = []
    for _ in range(n_resamples):
        sample_correct = 0.0
        sample_usd = 0.0
        for _ in range(n):
            j = rng.randrange(n)
            sample_correct += correct[j]
            sample_usd += usd[j]
        if sample_correct > 0:
            ratios.append(sample_usd / sample_correct)
    if not ratios:
        return None
    ratios.sort()
    alpha = (1.0 - confidence) / 2.0
    n_kept = len(ratios)
    lo_idx = max(0, int(alpha * n_kept))
    hi_idx = min(n_kept - 1, int((1.0 - alpha) * n_kept))
    return (ratios[lo_idx], ratios[hi_idx])


def aggregate(
    per_example: list[dict[str, Any]],
    *,
    bootstrap_resamples: int = _DEFAULT_BOOTSTRAP_RESAMPLES,
    bootstrap_seed: int = _DEFAULT_BOOTSTRAP_SEED,
) -> AggregateMetrics:
    """Aggregate a list of per-example records into a single `AggregateMetrics`."""
    if not per_example:
        return AggregateMetrics(
            n=0,
            accuracy=0.0,
            page_recall_mean=0.0,
            bbox_iou_mean=0.0,
            evidence_reward_mean=0.0,
            lazy_answer_rate=0.0,
            tool_calls_mean=0.0,
            tokens_in_mean=0.0,
            tokens_out_mean=0.0,
            usd_total=0.0,
            usd_per_correct=None,
        )

    def col(k: str, default: float = 0.0) -> list[float]:
        return [float(r.get(k, default) or 0.0) for r in per_example]

    correct_vals = col("answer_correct")
    usd_vals = col("usd")
    accuracy = mean(correct_vals)
    n_correct = sum(1 for r in per_example if r.get("answer_correct"))
    usd_total = sum(usd_vals)

    accuracy_ci = bootstrap_ci(correct_vals, n_resamples=bootstrap_resamples, seed=bootstrap_seed)
    usd_per_correct_ci = _bootstrap_usd_per_correct_ci(
        correct_vals, usd_vals, n_resamples=bootstrap_resamples, seed=bootstrap_seed
    )

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
        accuracy_ci=accuracy_ci,
        usd_per_correct_ci=usd_per_correct_ci,
    )


def _domain_stem(value: object) -> str:
    """Normalize an example.domain value to a lowercase stem.

    Accepts: a `Domain` enum (`Domain.DATASHEET`), its str-repr
    (`"Domain.DATASHEET"`), or a plain string (`"datasheet"`). Returns
    `"datasheet"`, `"finance"`, or `"?"` for empty/unknown.
    """
    if value is None or value == "":
        return "?"
    s = str(value)
    if "." in s:
        s = s.split(".")[-1]
    return s.lower() or "?"


def aggregate_by_domain(
    per_example: list[dict[str, Any]],
    *,
    bootstrap_resamples: int = _DEFAULT_BOOTSTRAP_RESAMPLES,
    bootstrap_seed: int = _DEFAULT_BOOTSTRAP_SEED,
) -> dict[str, AggregateMetrics]:
    """Bucket records by `record["domain"]` and aggregate each bucket.

    The returned dict always contains an `_overall` key with the union (so
    callers don't need to call `aggregate` separately). Domain stems are
    lowercased (`"datasheet"`, `"finance"`, `"?"` for missing).

    Each bucket gets its own bootstrapped CIs — n=47 finance has wider CIs
    than n=101 datasheet, which is what we want to surface in the
    headline table.
    """
    buckets: dict[str, list[dict[str, Any]]] = {"_overall": list(per_example)}
    for r in per_example:
        d = _domain_stem(r.get("domain"))
        buckets.setdefault(d, []).append(r)
    return {
        key: aggregate(rows, bootstrap_resamples=bootstrap_resamples, bootstrap_seed=bootstrap_seed)
        for key, rows in buckets.items()
    }
