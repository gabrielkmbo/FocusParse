"""Tests for `focusparse.eval.stage_metrics`.

Pure-function tests for each stage-level metric. No I/O, no mocks beyond
constructing fake per-example records. The harness wiring is tested
separately in `tests/test_focus_harness.py`.

Coverage:
  * Routing: page_recall@k for hit/miss/partial; precision@5;
    pages_inspected counter; missing route_pages step → all None
  * Localization: region_recall (50% coverage threshold); region_precision
    (intersection > 0); lazy_full_page_rate (60% area threshold);
    duplicate_crop_rate (IoU 0.7 threshold + same-page constraint);
    coordinate-space normalization (pixel gold + unit pred)
  * Reasoning: abstention detection; correct_abstention requires both
    gold=unanswerable AND pred-abstain; verifier_caught_unsupported
    requires answer wrong + verifier supported=false
  * Loop: defaults to 'no_loop' baseline; reads telemetry when present
  * Efficiency: per-stage token/usd/latency sums; multi-step-per-stage
    accumulates (the verifier-loop case)
  * Aggregate: mean of floats; rate of bools; sum-mean of efficiency;
    None values excluded; loop_terminated distribution computed
"""

from __future__ import annotations

import pytest

from focusparse.eval.stage_metrics import (
    AggregateStageMetrics,
    StageEfficiency,
    StageMetrics,
    aggregate_stage_metrics,
    compute_stage_metrics,
)


@pytest.fixture()
def example(parser_bench_submodule_present):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required for BenchmarkExample")

    from focusparse._parser_bench import (
        AnswerType,
        BBox,
        BenchmarkExample,
        DifficultyScores,
        Domain,
    )

    return BenchmarkExample(
        id="ex-stage-1",
        domain=Domain.DATASHEET,
        source_pdf="fake.pdf",
        page_images=["fake_page_1.png"],
        question="What is VCC max?",
        answer="3.6",
        answer_type=AnswerType.NUMERIC,
        answer_unit="V",
        tolerance=0.01,
        supporting_pages=[3],
        # Pixel-space gold at 300 DPI on a 3000x2250 page.
        supporting_bboxes=[BBox(page=3, x0=1500.0, y0=500.0, x1=2500.0, y1=1500.0)],
        difficulty=DifficultyScores(visual=2, reasoning=1, localization=2),
        question_family="single_value_lookup",
    )


@pytest.fixture()
def unanswerable_example(parser_bench_submodule_present):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    from focusparse._parser_bench import (
        AnswerType,
        BenchmarkExample,
        DifficultyScores,
        Domain,
    )

    return BenchmarkExample(
        id="ex-unans",
        domain=Domain.DATASHEET,
        source_pdf="fake.pdf",
        page_images=["fake_page_1.png"],
        question="What is the price of XYZ?",
        answer="Unanswerable",
        answer_type=AnswerType.UNANSWERABLE,
        supporting_pages=[],
        supporting_bboxes=[],
        difficulty=DifficultyScores(visual=1, reasoning=1, localization=1),
        question_family="unanswerable",
    )


def _record(
    *,
    citations: list | None = None,
    routed: list[int] | None = None,
    answer_pred: str = "3.6",
    answer_correct: float = 1.0,
    bbox_iou: float = 0.0,
    verifier_supported: bool | None = None,
    telemetry: dict | None = None,
    extra_steps: list | None = None,
) -> dict:
    """Construct a minimal per-example record for tests."""
    steps: list = []
    if routed is not None:
        steps.append(
            {
                "stage": "route_pages",
                "args": {"candidates": routed},
                "tokens_in": 0,
                "tokens_out": 0,
                "usd": 0.0,
                "latency_ms": 0,
            }
        )
    if verifier_supported is not None:
        steps.append(
            {
                "stage": "verify",
                "args": {"supported": verifier_supported, "next_action": "accept"},
                "tokens_in": 100,
                "tokens_out": 30,
                "usd": 0.001,
                "latency_ms": 50,
            }
        )
    if extra_steps:
        steps.extend(extra_steps)
    return {
        "example_id": "ex-stage-1",
        "answer_pred": answer_pred,
        "answer_correct": answer_correct,
        "bbox_iou": bbox_iou,
        "citations": citations or [],
        "telemetry": telemetry or {},
        "trace": {"steps": steps},
    }


# ---------------------------------------------------------------------------
# Routing metrics
# ---------------------------------------------------------------------------


def test_routing_page_recall_at_k_hit(example):
    rec = _record(routed=[3, 7, 12, 1, 2])
    sm = compute_stage_metrics(rec, example)
    # Page 3 is gold and is in top-1, top-3, top-5 → all 1.0
    assert sm.routing.page_recall_at_1 == 1.0
    assert sm.routing.page_recall_at_3 == 1.0
    assert sm.routing.page_recall_at_5 == 1.0
    # Of the 5 routed, only page 3 is gold → 0.2
    assert sm.routing.page_precision_at_5 == pytest.approx(0.2)
    assert sm.routing.pages_inspected == 5


def test_routing_page_recall_at_k_partial(example):
    """Gold page only appears in top-5, not top-1 or top-3."""
    rec = _record(routed=[7, 1, 12, 9, 3])
    sm = compute_stage_metrics(rec, example)
    assert sm.routing.page_recall_at_1 == 0.0
    assert sm.routing.page_recall_at_3 == 0.0
    assert sm.routing.page_recall_at_5 == 1.0


def test_routing_page_recall_miss(example):
    rec = _record(routed=[1, 2, 4, 5, 6])
    sm = compute_stage_metrics(rec, example)
    assert sm.routing.page_recall_at_1 == 0.0
    assert sm.routing.page_recall_at_5 == 0.0


def test_routing_no_gold_pages_yields_none(unanswerable_example):
    """Unanswerable examples have no gold pages → recall undefined."""
    rec = _record(routed=[1, 2])
    sm = compute_stage_metrics(rec, unanswerable_example)
    assert sm.routing.page_recall_at_1 is None
    assert sm.routing.page_recall_at_5 is None
    assert sm.routing.pages_inspected == 0  # default since no metric to compute


def test_routing_no_route_pages_step_yields_zero(example):
    """Simple agent records no route_pages step → no routed pages."""
    rec = _record(routed=None)  # no route_pages step at all
    sm = compute_stage_metrics(rec, example)
    assert sm.routing.page_recall_at_1 == 0.0
    assert sm.routing.pages_inspected == 0


# ---------------------------------------------------------------------------
# Localization metrics
# ---------------------------------------------------------------------------


def test_localization_region_recall_hit(example):
    """Predicted bbox covers the gold region → recall = 1.0.

    Gold: x0=1500/3000=0.5, y0=500/2250=0.222, x1=2500/3000=0.833, y1=1500/2250=0.667
    Pred: x0=0.5, y0=0.2, x1=0.85, y1=0.7 (slightly bigger than gold)
    Gold area = 0.333 × 0.444 = 0.148; intersection = 0.333 × 0.444 = 0.148.
    Coverage 0.148 / 0.148 = 100% ≥ 50% → recall = 1.0.
    """
    rec = _record(citations=[{"page": 3, "bbox": [0.5, 0.2, 0.85, 0.7]}])
    sm = compute_stage_metrics(rec, example, image_dims_by_page={3: (3000, 2250)})
    assert sm.localization.region_recall == pytest.approx(1.0)
    assert sm.localization.region_precision == pytest.approx(1.0)


def test_localization_region_recall_partial(example):
    """Pred covers only ~25% of gold → recall = 0.0 (below 50% threshold)."""
    # Gold normalized: (0.5, 0.222, 0.833, 0.667). Pred covers top-left quarter.
    rec = _record(citations=[{"page": 3, "bbox": [0.5, 0.222, 0.667, 0.444]}])
    sm = compute_stage_metrics(rec, example, image_dims_by_page={3: (3000, 2250)})
    # Pred covers 0.167 × 0.222 = 0.037 of gold's 0.148 area = 25%
    assert sm.localization.region_recall == 0.0
    # But it does intersect, so precision is 1.0 (1 of 1 preds intersect).
    assert sm.localization.region_precision == pytest.approx(1.0)


def test_localization_region_precision_with_misses(example):
    """Two preds, only one intersects gold → precision = 0.5."""
    rec = _record(
        citations=[
            {"page": 3, "bbox": [0.5, 0.2, 0.85, 0.7]},  # hits gold
            {"page": 3, "bbox": [0.0, 0.0, 0.1, 0.1]},  # off in the corner
        ]
    )
    sm = compute_stage_metrics(rec, example, image_dims_by_page={3: (3000, 2250)})
    assert sm.localization.region_precision == pytest.approx(0.5)


def test_localization_region_precision_wrong_page(example):
    """Pred on a different page from gold → no intersection."""
    rec = _record(citations=[{"page": 7, "bbox": [0.5, 0.5, 0.6, 0.6]}])
    sm = compute_stage_metrics(rec, example, image_dims_by_page={3: (3000, 2250), 7: (3000, 2250)})
    assert sm.localization.region_precision == 0.0
    assert sm.localization.region_recall == 0.0


def test_localization_lazy_full_page_rate(example):
    """A bbox covering > 60% of the page is the lazy-full-page anti-pattern."""
    rec = _record(
        citations=[
            {"page": 3, "bbox": [0.0, 0.0, 1.0, 1.0]},  # 100% lazy
            {"page": 3, "bbox": [0.5, 0.2, 0.85, 0.7]},  # 14.8%, fine
            {"page": 3, "bbox": [0.0, 0.0, 0.9, 0.9]},  # 81%, lazy
        ]
    )
    sm = compute_stage_metrics(rec, example, image_dims_by_page={3: (3000, 2250)})
    assert sm.localization.lazy_full_page_rate == pytest.approx(2 / 3)


def test_localization_lazy_full_page_rate_zero_when_tight(example):
    """All citations small → 0% lazy."""
    rec = _record(
        citations=[
            {"page": 3, "bbox": [0.5, 0.2, 0.6, 0.3]},
            {"page": 3, "bbox": [0.7, 0.4, 0.8, 0.5]},
        ]
    )
    sm = compute_stage_metrics(rec, example, image_dims_by_page={3: (3000, 2250)})
    assert sm.localization.lazy_full_page_rate == 0.0


def test_localization_duplicate_crop_rate(example):
    """Two near-identical crops → both flagged as duplicates."""
    rec = _record(
        citations=[
            {"page": 3, "bbox": [0.5, 0.2, 0.85, 0.7]},  # original
            {"page": 3, "bbox": [0.51, 0.21, 0.84, 0.69]},  # near-duplicate
            {"page": 3, "bbox": [0.0, 0.0, 0.1, 0.1]},  # unrelated
        ]
    )
    sm = compute_stage_metrics(rec, example, image_dims_by_page={3: (3000, 2250)})
    # 2 of 3 citations are part of a duplicate pair
    assert sm.localization.duplicate_crop_rate == pytest.approx(2 / 3)


def test_localization_duplicate_crop_rate_ignores_cross_page(example):
    """Identical bboxes on different pages are NOT duplicates."""
    rec = _record(
        citations=[
            {"page": 3, "bbox": [0.5, 0.2, 0.85, 0.7]},
            {"page": 7, "bbox": [0.5, 0.2, 0.85, 0.7]},
        ]
    )
    sm = compute_stage_metrics(
        rec,
        example,
        image_dims_by_page={3: (3000, 2250), 7: (3000, 2250)},
    )
    assert sm.localization.duplicate_crop_rate == 0.0


def test_localization_handles_pixel_space_gold_with_unit_pred(example):
    """Coord-space autodetect: gold is pixel (max > 1), pred is unit ([0,1]).

    Without `image_dims_by_page` we fall through with no normalization,
    so the unit pred and pixel gold don't intersect → recall 0.
    """
    rec = _record(citations=[{"page": 3, "bbox": [0.5, 0.2, 0.85, 0.7]}])
    sm = compute_stage_metrics(rec, example)  # no image_dims passed
    # No normalization → unit pred vs pixel gold → no overlap
    assert sm.localization.region_recall == 0.0


def test_localization_no_citations_yields_none_for_recall(example):
    """No citations → recall is None (not 0); precision is None too."""
    rec = _record(citations=[], bbox_iou=0.0)
    sm = compute_stage_metrics(rec, example, image_dims_by_page={3: (3000, 2250)})
    # No preds → can't compute either metric
    assert sm.localization.region_recall is None
    assert sm.localization.region_precision is None


# ---------------------------------------------------------------------------
# Reasoning metrics
# ---------------------------------------------------------------------------


def test_reasoning_correct_answer(example):
    rec = _record(answer_pred="3.6", answer_correct=1.0)
    sm = compute_stage_metrics(rec, example)
    assert sm.reasoning.answer_correct == 1.0
    assert sm.reasoning.is_abstention is False
    assert sm.reasoning.is_correct_abstention is False
    assert sm.reasoning.verifier_caught_unsupported is False


def test_reasoning_abstention_detected():
    """Abstention keywords → is_abstention=True."""
    from focusparse._parser_bench import (
        AnswerType,
        BenchmarkExample,
        DifficultyScores,
        Domain,
    )

    ex = BenchmarkExample(
        id="x",
        domain=Domain.DATASHEET,
        source_pdf="x.pdf",
        page_images=["x.png"],
        question="?",
        answer="anything",
        answer_type=AnswerType.EXACT_MATCH,
        supporting_pages=[],
        supporting_bboxes=[],
        difficulty=DifficultyScores(visual=1, reasoning=1, localization=1),
        question_family="single_value_lookup",
    )
    rec = _record(answer_pred="The question is unanswerable", answer_correct=0.0)
    sm = compute_stage_metrics(rec, ex)
    assert sm.reasoning.is_abstention is True


def test_reasoning_correct_abstention_requires_both(unanswerable_example):
    """is_correct_abstention iff gold=unanswerable AND pred-abstain."""
    # Gold IS unanswerable, pred IS abstain → correct abstention
    rec = _record(answer_pred="N/A — cannot be determined", answer_correct=1.0)
    sm = compute_stage_metrics(rec, unanswerable_example)
    assert sm.reasoning.is_abstention is True
    assert sm.reasoning.is_correct_abstention is True

    # Gold IS unanswerable but pred is a number → is_correct_abstention=False
    rec2 = _record(answer_pred="42", answer_correct=0.0)
    sm2 = compute_stage_metrics(rec2, unanswerable_example)
    assert sm2.reasoning.is_abstention is False
    assert sm2.reasoning.is_correct_abstention is False


def test_reasoning_verifier_caught_unsupported(example):
    """Wrong answer + verifier said supported=false → verifier earned its keep."""
    rec = _record(
        answer_pred="9.9",
        answer_correct=0.0,
        verifier_supported=False,
    )
    sm = compute_stage_metrics(rec, example)
    assert sm.reasoning.verifier_caught_unsupported is True


def test_reasoning_verifier_did_not_catch_correct_answer(example):
    """Right answer + verifier said supported=true → not 'caught unsupported'."""
    rec = _record(
        answer_pred="3.6",
        answer_correct=1.0,
        verifier_supported=True,
    )
    sm = compute_stage_metrics(rec, example)
    assert sm.reasoning.verifier_caught_unsupported is False


def test_reasoning_no_verifier_step_no_catch(example):
    """No verify step (simple agent) → verifier_caught defaults to False."""
    rec = _record(
        answer_pred="9.9",
        answer_correct=0.0,
        verifier_supported=None,  # no verify step in trace
    )
    sm = compute_stage_metrics(rec, example)
    assert sm.reasoning.verifier_caught_unsupported is False


# ---------------------------------------------------------------------------
# Loop metrics
# ---------------------------------------------------------------------------


def test_loop_baseline_no_loop(example):
    """Without telemetry telling us otherwise, default to no_loop."""
    rec = _record()
    sm = compute_stage_metrics(rec, example)
    assert sm.loop.loop_terminated == "no_loop"
    assert sm.loop.loop_retries == 0
    assert sm.loop.loop_retry_helped is None


def test_loop_telemetry_passes_through(example):
    """Item 3's verifier loop will populate this telemetry."""
    rec = _record(
        telemetry={
            "retries_used": 2,
            "loop_terminated": "accepted",
            "loop_retry_helped": True,
        }
    )
    sm = compute_stage_metrics(rec, example)
    assert sm.loop.loop_retries == 2
    assert sm.loop.loop_terminated == "accepted"
    assert sm.loop.loop_retry_helped is True


def test_loop_invalid_terminated_falls_back_to_no_loop(example):
    rec = _record(telemetry={"loop_terminated": "garbage_value"})
    sm = compute_stage_metrics(rec, example)
    assert sm.loop.loop_terminated == "no_loop"


# ---------------------------------------------------------------------------
# Efficiency per stage
# ---------------------------------------------------------------------------


def test_efficiency_sums_per_stage(example):
    """Multiple steps for the same stage (verifier-loop case) accumulate."""
    rec = _record(
        extra_steps=[
            {
                "stage": "answer",
                "tokens_in": 1000,
                "tokens_out": 50,
                "usd": 0.005,
                "latency_ms": 800,
                "tool": None,
                "action": "llm_call",
            },
            {
                "stage": "answer",
                "tokens_in": 500,
                "tokens_out": 30,
                "usd": 0.002,
                "latency_ms": 400,
                "tool": None,
                "action": "llm_call",
            },
        ]
    )
    sm = compute_stage_metrics(rec, example)
    answer_eff = sm.efficiency_by_stage["answer"]
    assert answer_eff.tokens == 1580  # 1000+50+500+30
    assert answer_eff.usd == pytest.approx(0.007)
    assert answer_eff.latency_ms == 1200


def test_efficiency_counts_tool_calls(example):
    rec = _record(
        extra_steps=[
            {"stage": "inspect", "action": "tool_call", "tool": "inspector"},
            {"stage": "inspect", "action": "tool_call", "tool": "inspector"},
            {"stage": "expand_context", "action": "deterministic", "tool": None},
        ]
    )
    sm = compute_stage_metrics(rec, example)
    assert sm.efficiency_by_stage["inspect"].tool_calls == 2
    assert sm.efficiency_by_stage["expand_context"].tool_calls == 0


# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------


def test_aggregate_means_floats_and_rates_bools(example):
    sms = [
        StageMetrics(),  # all defaults
        StageMetrics(),
    ]
    sms[0].reasoning.answer_correct = 1.0
    sms[0].reasoning.is_abstention = True
    sms[1].reasoning.answer_correct = 0.0
    sms[1].reasoning.is_abstention = False
    sms[0].localization.region_recall = 0.8
    sms[1].localization.region_recall = 0.6
    sms[0].localization.region_precision = 0.5
    sms[1].localization.region_precision = None  # excluded from mean

    agg = aggregate_stage_metrics(sms)
    assert agg.n == 2
    assert agg.reasoning["answer_correct"] == pytest.approx(0.5)
    assert agg.reasoning["abstention_rate"] == pytest.approx(0.5)
    assert agg.localization["region_recall"] == pytest.approx(0.7)
    # Only one example had a non-None precision; the other is excluded.
    assert agg.localization["region_precision"] == pytest.approx(0.5)


def test_aggregate_all_none_yields_none(example):
    sms = [StageMetrics(), StageMetrics()]
    # Both have None for routing recall (default)
    agg = aggregate_stage_metrics(sms)
    assert agg.routing["page_recall_at_1"] is None


def test_aggregate_loop_terminated_distribution(example):
    sms = [StageMetrics(), StageMetrics(), StageMetrics()]
    sms[0].loop.loop_terminated = "accepted"
    sms[1].loop.loop_terminated = "accepted"
    sms[2].loop.loop_terminated = "abstained"
    agg = aggregate_stage_metrics(sms)
    assert agg.loop_terminated_distribution["accepted"] == pytest.approx(2 / 3)
    assert agg.loop_terminated_distribution["abstained"] == pytest.approx(1 / 3)


def test_aggregate_efficiency_by_stage_means_per_example():
    """Efficiency aggregates as the mean per-example sum (cost across examples
    averaged, not summed)."""
    sms = [StageMetrics(), StageMetrics()]
    sms[0].efficiency_by_stage["answer"] = StageEfficiency(
        tokens=2000, usd=0.01, latency_ms=1000, tool_calls=1
    )
    sms[1].efficiency_by_stage["answer"] = StageEfficiency(
        tokens=1000, usd=0.005, latency_ms=500, tool_calls=1
    )
    agg = aggregate_stage_metrics(sms)
    answer_eff = agg.efficiency_by_stage["answer"]
    assert answer_eff.tokens == 1500  # mean of 2000 + 1000
    assert answer_eff.usd == pytest.approx(0.0075)


def test_aggregate_empty_input_returns_n_zero():
    agg = aggregate_stage_metrics([])
    assert agg.n == 0
    assert agg.routing == {}
    assert agg.loop_terminated_distribution == {}


def test_aggregate_round_trip_serializes_with_pydantic():
    """The bundle should round-trip JSON cleanly so the harness can persist it."""
    sms = [StageMetrics()]
    sms[0].reasoning.answer_correct = 1.0
    agg = aggregate_stage_metrics(sms)
    serialized = agg.model_dump_json()
    rebuilt = AggregateStageMetrics.model_validate_json(serialized)
    assert rebuilt.reasoning["answer_correct"] == pytest.approx(1.0)
