"""Stage-level metrics for the focus pipeline.

Pulled forward from Phase 4 on 2026-04-27 per user directive: without
per-stage metrics we ship the verifier loop / region reranker / evidence
graph blind. Each item ships with a measurable A/B delta against a stable
baseline via `scripts/diff_runs.py`.

Metrics are computed once per example from the per-example record the
harness already writes (citations + trajectory steps + telemetry) plus
the gold `BenchmarkExample`. Pure functions — no I/O, no LLM calls,
fully unit-testable.

Aggregation across examples lives in `aggregate_stage_metrics()`. Means
for floats; rate (mean of bool→0/1) for booleans; sums for counts.

Hard rule per `plans/2026-04-27-phase2-sota-leverage.md`: items 3-5 don't
ship without a positive delta on the metric they were supposed to improve,
measured against a baseline captured before item 3 lands.
"""

from __future__ import annotations

from statistics import mean
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from focusparse._parser_bench import BenchmarkExample


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class RoutingMetrics(BaseModel):
    """`route_pages` stage. None = couldn't compute (no gold pages, etc.)."""

    page_recall_at_1: float | None = None
    page_recall_at_3: float | None = None
    page_recall_at_5: float | None = None
    page_precision_at_5: float | None = None
    pages_inspected: int = 0


class LocalizationMetrics(BaseModel):
    """`localize` (+ future `rerank`) stages."""

    region_recall: float | None = None  # any pred bbox covers ≥ 50% of any gold
    region_precision: float | None = None  # frac of preds that intersect a gold
    bbox_iou_max: float = 0.0  # alias for the existing max IoU metric
    lazy_full_page_rate: float = 0.0  # frac of preds covering > 60% of page
    duplicate_crop_rate: float = 0.0  # frac of pred pairs with IoU > 0.7


class EvidenceMetrics(BaseModel):
    """`inspect` + `expand_context` evidence sufficiency.

    Both fields default to None for v1 — they need richer per-citation
    tracking (cited packet bodies, neighbor→answer attribution) that lands
    alongside item 5 (evidence graph) when the citation schema gets richer.
    """

    cited_evidence_completeness: float | None = None
    expansion_useful_rate: float | None = None


class ReasoningMetrics(BaseModel):
    """`answer` + `verify` stages."""

    answer_correct: float = 0.0
    is_abstention: bool = False
    is_correct_abstention: bool = False  # gold=unanswerable AND pred abstained
    verifier_caught_unsupported: bool = False  # answer wrong AND verifier said so


class LoopMetrics(BaseModel):
    """`accepted` is the only happy-path terminator. `no_loop` covers the
    pre-item-3 baseline where the workflow is a one-shot cascade."""

    loop_retries: int = 0
    loop_terminated: Literal["no_loop", "accepted", "abstained", "exhausted"] = "no_loop"
    loop_retry_helped: bool | None = None  # null when retries=0


class StageEfficiency(BaseModel):
    """Per-stage cost/latency/tool counts; sourced from TrajectoryStep."""

    tokens: int = 0
    usd: float = 0.0
    latency_ms: int = 0
    tool_calls: int = 0


class StageMetrics(BaseModel):
    """All stage-level metrics for one example."""

    routing: RoutingMetrics = Field(default_factory=RoutingMetrics)
    localization: LocalizationMetrics = Field(default_factory=LocalizationMetrics)
    evidence: EvidenceMetrics = Field(default_factory=EvidenceMetrics)
    reasoning: ReasoningMetrics = Field(default_factory=ReasoningMetrics)
    loop: LoopMetrics = Field(default_factory=LoopMetrics)
    efficiency_by_stage: dict[str, StageEfficiency] = Field(default_factory=dict)


class AggregateStageMetrics(BaseModel):
    """Mean (or rate, for bools) of each metric across a run."""

    n: int = 0
    routing: dict[str, float | None] = Field(default_factory=dict)
    localization: dict[str, float | None] = Field(default_factory=dict)
    evidence: dict[str, float | None] = Field(default_factory=dict)
    reasoning: dict[str, float | None] = Field(default_factory=dict)
    loop: dict[str, float | None] = Field(default_factory=dict)
    loop_terminated_distribution: dict[str, float] = Field(default_factory=dict)
    efficiency_by_stage: dict[str, StageEfficiency] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Per-example computation
# ---------------------------------------------------------------------------


def compute_stage_metrics(
    record: dict[str, Any],
    example: BenchmarkExample,
    *,
    image_dims_by_page: dict[int, tuple[int, int]] | None = None,
) -> StageMetrics:
    """Compute all stage-level metrics for one example.

    `record` is the per-example dict produced by `harness._score_and_record`
    (citations, tool_calls, answer_correct, etc.). `example` is the gold
    `BenchmarkExample`. `image_dims_by_page` lets us normalize pixel-space
    gold bboxes against [0,1] predicted bboxes (same convention used by
    `eval/scoring.py`).

    Returns `StageMetrics` with None for fields we can't compute (e.g.
    no gold pages → no recall@k). Caller decides how to display None.
    """
    routing = _routing_metrics(record, example)
    localization = _localization_metrics(record, example, image_dims_by_page)
    evidence = EvidenceMetrics()  # v1: defer; richer schema with item 5
    reasoning = _reasoning_metrics(record, example)
    loop = _loop_metrics(record)
    efficiency = _efficiency_by_stage(record)

    return StageMetrics(
        routing=routing,
        localization=localization,
        evidence=evidence,
        reasoning=reasoning,
        loop=loop,
        efficiency_by_stage=efficiency,
    )


def _routing_metrics(record: dict[str, Any], example: BenchmarkExample) -> RoutingMetrics:
    """Page-routing recall + precision @ {1, 3, 5} from the route_pages step."""
    gold_pages = {int(p) for p in (example.supporting_pages or [])}
    if not gold_pages:
        return RoutingMetrics()  # nothing to score

    routed = _routed_pages(record)  # ordered top-k
    if not routed:
        return RoutingMetrics(
            page_recall_at_1=0.0,
            page_recall_at_3=0.0,
            page_recall_at_5=0.0,
            page_precision_at_5=0.0,
            pages_inspected=0,
        )

    def recall_at(k: int) -> float:
        top = set(routed[:k])
        if not top:
            return 0.0
        return float(bool(top & gold_pages))

    def precision_at(k: int) -> float:
        top = routed[:k]
        if not top:
            return 0.0
        return sum(1 for p in top if p in gold_pages) / len(top)

    return RoutingMetrics(
        page_recall_at_1=recall_at(1),
        page_recall_at_3=recall_at(3),
        page_recall_at_5=recall_at(5),
        page_precision_at_5=precision_at(5),
        pages_inspected=len(routed),
    )


def _routed_pages(record: dict[str, Any]) -> list[int]:
    """Pull the page candidates the router emitted from the trajectory.

    Looks for the `route_pages` trajectory step's `args["candidates"]`.
    Returns [] when not found (e.g. the simple agent doesn't have this
    stage; the metrics caller treats missing routing as 'not measured').
    """
    trace = record.get("trace") or {}
    for step in trace.get("steps", []):
        if step.get("stage") == "route_pages":
            candidates = (step.get("args") or {}).get("candidates") or []
            return [int(p) for p in candidates]
    return []


def _localization_metrics(
    record: dict[str, Any],
    example: BenchmarkExample,
    image_dims_by_page: dict[int, tuple[int, int]] | None,
) -> LocalizationMetrics:
    """Region-level metrics over the reasoner's citations."""
    citations = record.get("citations") or []
    if not citations:
        return LocalizationMetrics(bbox_iou_max=float(record.get("bbox_iou") or 0.0))

    pred_bboxes_unit = _normalize_citations_to_unit(
        citations, image_dims_by_page=image_dims_by_page
    )
    gold_bboxes_unit = _normalize_gold_to_unit(example, image_dims_by_page)

    return LocalizationMetrics(
        region_recall=_region_recall(pred_bboxes_unit, gold_bboxes_unit),
        region_precision=_region_precision(pred_bboxes_unit, gold_bboxes_unit),
        bbox_iou_max=float(record.get("bbox_iou") or 0.0),
        lazy_full_page_rate=_lazy_full_page_rate(pred_bboxes_unit),
        duplicate_crop_rate=_duplicate_crop_rate(pred_bboxes_unit),
    )


def _normalize_citations_to_unit(
    citations: list[dict[str, Any]],
    *,
    image_dims_by_page: dict[int, tuple[int, int]] | None,
) -> list[tuple[int, tuple[float, float, float, float]]]:
    out: list[tuple[int, tuple[float, float, float, float]]] = []
    for c in citations:
        bbox = c.get("bbox")
        if not (isinstance(bbox, list) and len(bbox) == 4):
            continue
        try:
            page = int(c.get("page"))
            x0, y0, x1, y1 = (float(v) for v in bbox)
        except (TypeError, ValueError):
            continue
        max_v = max(x0, y0, x1, y1)
        if max_v > 1.0 and image_dims_by_page is not None:
            dims = image_dims_by_page.get(page)
            if dims and dims[0] > 0 and dims[1] > 0:
                w, h = dims
                x0, y0, x1, y1 = x0 / w, y0 / h, x1 / w, y1 / h
        out.append((page, (x0, y0, x1, y1)))
    return out


def _normalize_gold_to_unit(
    example: BenchmarkExample,
    image_dims_by_page: dict[int, tuple[int, int]] | None,
) -> list[tuple[int, tuple[float, float, float, float]]]:
    """Same convention as `eval/scoring._to_unit_interval_bbox`. Pixel-space
    gold (max coord > 1) gets normalized when image dims are available."""
    out: list[tuple[int, tuple[float, float, float, float]]] = []
    for b in example.supporting_bboxes or []:
        x0, y0, x1, y1 = float(b.x0), float(b.y0), float(b.x1), float(b.y1)
        page = int(b.page)
        if max(x0, y0, x1, y1) > 1.0 and image_dims_by_page is not None:
            dims = image_dims_by_page.get(page)
            if dims and dims[0] > 0 and dims[1] > 0:
                w, h = dims
                x0, y0, x1, y1 = x0 / w, y0 / h, x1 / w, y1 / h
        out.append((page, (x0, y0, x1, y1)))
    return out


def _region_recall(
    preds: list[tuple[int, tuple[float, float, float, float]]],
    golds: list[tuple[int, tuple[float, float, float, float]]],
) -> float | None:
    """For each gold region, did any prediction cover ≥ 50% of it?"""
    if not golds:
        return None
    if not preds:
        return 0.0
    hits = 0
    for g_page, g_bbox in golds:
        g_area = max(0.0, (g_bbox[2] - g_bbox[0]) * (g_bbox[3] - g_bbox[1]))
        if g_area <= 0:
            continue
        for p_page, p_bbox in preds:
            if p_page != g_page:
                continue
            inter = _intersection_area(p_bbox, g_bbox)
            if inter / g_area >= 0.5:
                hits += 1
                break
    return hits / len(golds)


def _region_precision(
    preds: list[tuple[int, tuple[float, float, float, float]]],
    golds: list[tuple[int, tuple[float, float, float, float]]],
) -> float | None:
    """Fraction of predictions that intersect any gold (IoU > 0)."""
    if not preds:
        return None
    if not golds:
        return 0.0
    matches = 0
    for p_page, p_bbox in preds:
        for g_page, g_bbox in golds:
            if p_page != g_page:
                continue
            if _intersection_area(p_bbox, g_bbox) > 0:
                matches += 1
                break
    return matches / len(preds)


def _intersection_area(
    a: tuple[float, float, float, float], b: tuple[float, float, float, float]
) -> float:
    x0 = max(a[0], b[0])
    y0 = max(a[1], b[1])
    x1 = min(a[2], b[2])
    y1 = min(a[3], b[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    return (x1 - x0) * (y1 - y0)


def _bbox_area(bbox: tuple[float, float, float, float]) -> float:
    return max(0.0, (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]))


def _bbox_iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    inter = _intersection_area(a, b)
    union = _bbox_area(a) + _bbox_area(b) - inter
    return inter / union if union > 0 else 0.0


def _lazy_full_page_rate(
    preds: list[tuple[int, tuple[float, float, float, float]]],
    *,
    threshold: float = 0.6,
) -> float:
    """Frac of citations whose unit-space area > threshold (default 60%).

    A predicted bbox covering > 60% of the page is the AgenticOCR-style
    "lazy full page" anti-pattern — we cited "the page" rather than the
    actual region.
    """
    if not preds:
        return 0.0
    n_lazy = sum(1 for _, b in preds if _bbox_area(b) > threshold)
    return n_lazy / len(preds)


def _duplicate_crop_rate(
    preds: list[tuple[int, tuple[float, float, float, float]]],
    *,
    threshold: float = 0.7,
) -> float:
    """Pairwise IoU > threshold across same-page predictions.

    Returns the fraction of citations involved in a near-duplicate pair.
    Same predictor citing the same region twice (intentionally or by
    bug) shows up here.
    """
    if len(preds) < 2:
        return 0.0
    flagged: set[int] = set()
    for i in range(len(preds)):
        for j in range(i + 1, len(preds)):
            if preds[i][0] != preds[j][0]:
                continue
            if _bbox_iou(preds[i][1], preds[j][1]) > threshold:
                flagged.add(i)
                flagged.add(j)
    return len(flagged) / len(preds)


def _reasoning_metrics(record: dict[str, Any], example: BenchmarkExample) -> ReasoningMetrics:
    """answer/verify-level signals.

    - `is_abstention`: predicted text is recognizably an abstention
    - `is_correct_abstention`: gold answer_type == "unanswerable" AND pred abstained
    - `verifier_caught_unsupported`: answer wrong AND verifier said supported=false
    """
    pred = (record.get("answer_pred") or "").strip()
    is_abstain = _looks_abstention(pred)

    gold_answer_type = str(getattr(example, "answer_type", "") or "").lower()
    is_unanswerable = gold_answer_type.endswith("unanswerable")
    is_correct_abstain = is_unanswerable and is_abstain

    answer_correct = float(record.get("answer_correct") or 0.0)
    verifier_supported = _verifier_supported(record)
    # Caught-it iff the answer was wrong AND the verifier flagged it.
    verifier_caught = (answer_correct < 1.0) and (verifier_supported is False)

    return ReasoningMetrics(
        answer_correct=answer_correct,
        is_abstention=is_abstain,
        is_correct_abstention=is_correct_abstain,
        verifier_caught_unsupported=verifier_caught,
    )


def _looks_abstention(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    return any(
        kw in lowered
        for kw in (
            "unanswerable",
            "cannot be determined",
            "not enough information",
            "n/a",
            "i don't know",
            "insufficient",
        )
    )


def _verifier_supported(record: dict[str, Any]) -> bool | None:
    """Pull the verifier's `supported` field from the trajectory.

    Returns None when the verify step isn't present (e.g. simple agent),
    so the caller can distinguish "not measured" from "verifier said
    supported".
    """
    trace = record.get("trace") or {}
    for step in trace.get("steps", []):
        if step.get("stage") == "verify":
            args = step.get("args") or {}
            if "supported" in args:
                return bool(args["supported"])
    return None


def _loop_metrics(record: dict[str, Any]) -> LoopMetrics:
    """Loop telemetry (filled in by item 3; defaults are 'no_loop' baseline).

    Looks for a `telemetry.loop_terminated` and `telemetry.retries_used`
    block on the per-example record. The baseline cascade workflow has
    `retries_used=0` and `loop_terminated="no_loop"`.
    """
    telemetry = record.get("telemetry") or {}
    retries = int(telemetry.get("retries_used") or 0)
    terminated = str(telemetry.get("loop_terminated") or "no_loop")
    if terminated not in {"no_loop", "accepted", "abstained", "exhausted"}:
        terminated = "no_loop"
    retry_helped: bool | None = None
    if retries > 0:
        # Filled by item 3 once the workflow tracks retry-improvement.
        retry_helped = bool(telemetry.get("loop_retry_helped"))
    return LoopMetrics(
        loop_retries=retries,
        loop_terminated=terminated,  # type: ignore[arg-type]
        loop_retry_helped=retry_helped,
    )


def _efficiency_by_stage(record: dict[str, Any]) -> dict[str, StageEfficiency]:
    """Sum tokens/usd/latency/tool_calls per stage from the trajectory steps.

    Multiple steps for the same stage (the verifier-loop case) get summed,
    so a stage that retried twice shows the cumulative cost of all attempts.
    """
    trace = record.get("trace") or {}
    by_stage: dict[str, StageEfficiency] = {}
    for step in trace.get("steps", []):
        stage = str(step.get("stage") or "")
        if not stage:
            continue
        cur = by_stage.setdefault(stage, StageEfficiency())
        cur.tokens += int(step.get("tokens_in") or 0) + int(step.get("tokens_out") or 0)
        cur.usd += float(step.get("usd") or 0.0)
        cur.latency_ms += int(step.get("latency_ms") or 0)
        if step.get("tool") or step.get("action") == "tool_call":
            cur.tool_calls += 1
    return by_stage


# ---------------------------------------------------------------------------
# Aggregation across a run
# ---------------------------------------------------------------------------


def aggregate_stage_metrics(
    per_example_stages: list[StageMetrics],
) -> AggregateStageMetrics:
    """Mean (rate for bools) of each metric across a list of example metrics.

    None values are excluded from the mean — a metric that's "not measured"
    on some examples doesn't drag the average down. The aggregate field
    is None iff every example was None for that field.
    """
    if not per_example_stages:
        return AggregateStageMetrics()

    def _mean_floats(values: list[float | None]) -> float | None:
        kept = [v for v in values if v is not None]
        return float(mean(kept)) if kept else None

    def _mean_bools(values: list[bool]) -> float:
        return float(mean(int(v) for v in values))

    def _mean_ints(values: list[int]) -> float:
        return float(mean(values)) if values else 0.0

    def _routing_block() -> dict[str, float | None]:
        return {
            "page_recall_at_1": _mean_floats(
                [s.routing.page_recall_at_1 for s in per_example_stages]
            ),
            "page_recall_at_3": _mean_floats(
                [s.routing.page_recall_at_3 for s in per_example_stages]
            ),
            "page_recall_at_5": _mean_floats(
                [s.routing.page_recall_at_5 for s in per_example_stages]
            ),
            "page_precision_at_5": _mean_floats(
                [s.routing.page_precision_at_5 for s in per_example_stages]
            ),
            "pages_inspected_mean": _mean_ints(
                [s.routing.pages_inspected for s in per_example_stages]
            ),
        }

    def _localization_block() -> dict[str, float | None]:
        return {
            "region_recall": _mean_floats(
                [s.localization.region_recall for s in per_example_stages]
            ),
            "region_precision": _mean_floats(
                [s.localization.region_precision for s in per_example_stages]
            ),
            "bbox_iou_mean": _mean_floats(
                [s.localization.bbox_iou_max for s in per_example_stages]
            ),
            "lazy_full_page_rate": _mean_floats(
                [s.localization.lazy_full_page_rate for s in per_example_stages]
            ),
            "duplicate_crop_rate": _mean_floats(
                [s.localization.duplicate_crop_rate for s in per_example_stages]
            ),
        }

    def _evidence_block() -> dict[str, float | None]:
        return {
            "cited_evidence_completeness": _mean_floats(
                [s.evidence.cited_evidence_completeness for s in per_example_stages]
            ),
            "expansion_useful_rate": _mean_floats(
                [s.evidence.expansion_useful_rate for s in per_example_stages]
            ),
        }

    def _reasoning_block() -> dict[str, float | None]:
        return {
            "answer_correct": _mean_floats(
                [s.reasoning.answer_correct for s in per_example_stages]
            ),
            "abstention_rate": _mean_bools([s.reasoning.is_abstention for s in per_example_stages]),
            "correct_abstention_rate": _mean_bools(
                [s.reasoning.is_correct_abstention for s in per_example_stages]
            ),
            "verifier_caught_unsupported_rate": _mean_bools(
                [s.reasoning.verifier_caught_unsupported for s in per_example_stages]
            ),
        }

    def _loop_block() -> dict[str, float | None]:
        retries = [s.loop.loop_retries for s in per_example_stages]
        helped = [
            s.loop.loop_retry_helped
            for s in per_example_stages
            if s.loop.loop_retry_helped is not None
        ]
        return {
            "retries_mean": _mean_ints(retries),
            "retry_helped_rate": (float(mean(int(b) for b in helped)) if helped else None),
        }

    def _terminated_distribution() -> dict[str, float]:
        counts: dict[str, int] = {}
        for s in per_example_stages:
            counts[s.loop.loop_terminated] = counts.get(s.loop.loop_terminated, 0) + 1
        n = len(per_example_stages)
        return {k: v / n for k, v in counts.items()}

    def _efficiency_block() -> dict[str, StageEfficiency]:
        sums: dict[str, StageEfficiency] = {}
        counts: dict[str, int] = {}
        for s in per_example_stages:
            for stage_name, eff in s.efficiency_by_stage.items():
                cur = sums.setdefault(stage_name, StageEfficiency())
                cur.tokens += eff.tokens
                cur.usd += eff.usd
                cur.latency_ms += eff.latency_ms
                cur.tool_calls += eff.tool_calls
                counts[stage_name] = counts.get(stage_name, 0) + 1
        # Convert sums to means
        means: dict[str, StageEfficiency] = {}
        for name, total in sums.items():
            n = counts[name]
            means[name] = StageEfficiency(
                tokens=int(total.tokens / n),
                usd=total.usd / n,
                latency_ms=int(total.latency_ms / n),
                tool_calls=int(total.tool_calls / n),
            )
        return means

    return AggregateStageMetrics(
        n=len(per_example_stages),
        routing=_routing_block(),
        localization=_localization_block(),
        evidence=_evidence_block(),
        reasoning=_reasoning_block(),
        loop=_loop_block(),
        loop_terminated_distribution=_terminated_distribution(),
        efficiency_by_stage=_efficiency_block(),
    )
