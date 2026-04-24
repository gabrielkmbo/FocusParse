"""Unit tests for the evidence-reward scoring function.

These tests exercise the lazy-answer penalty and evidence-reward math without
hitting any API. They require the parser-bench submodule for the schema.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


@pytest.fixture()
def minimal_example(parser_bench_submodule_present):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule not present (see README init)")
    from focusparse._parser_bench import (
        AnswerType,
        BBox,
        BenchmarkExample,
        DifficultyScores,
        Domain,
    )

    return BenchmarkExample(
        id="test-0001",
        domain=Domain.FINANCE,
        source_pdf="fake.pdf",
        page_images=["fake_page_1.png"],
        question="What is the reported value in millions?",
        answer="1096",
        answer_type=AnswerType.NUMERIC,
        answer_unit="millions",
        tolerance=0.01,
        supporting_pages=[1],
        supporting_bboxes=[BBox(page=1, x0=100, y0=100, x1=300, y1=200)],
        difficulty=DifficultyScores(visual=2, reasoning=1, localization=2),
        question_family="direct_label_reading",
    )


def test_lazy_answer_yields_zero_reward(minimal_example):
    from focusparse._parser_bench import BBox
    from focusparse.eval.scoring import score_evidence_reward

    # Answer correct but no tool calls and no predicted bboxes → lazy.
    reward = score_evidence_reward(
        prediction_text="1096",
        predicted_pages=[1],
        predicted_bboxes=[],
        tool_calls=[],
        example=minimal_example,
    )
    assert reward == 0.0

    # Tool calls but no predicted bboxes → still lazy.
    reward = score_evidence_reward(
        prediction_text="1096",
        predicted_pages=[1],
        predicted_bboxes=[BBox(page=1, x0=0, y0=0, x1=10, y1=10)],
        tool_calls=[],
        example=minimal_example,
    )
    assert reward == 0.0


def test_perfect_answer_full_reward(minimal_example):
    from focusparse._parser_bench import BBox
    from focusparse.eval.scoring import score_evidence_reward

    # Perfect localization + correct answer → IoU = 1.0, reward = 1.0.
    reward = score_evidence_reward(
        prediction_text="1096",
        predicted_pages=[1],
        predicted_bboxes=[BBox(page=1, x0=100, y0=100, x1=300, y1=200)],
        tool_calls=[{"tool": "inspect_region", "args": {}}],
        example=minimal_example,
        largest_crop_area_ratio=0.1,
    )
    assert reward == pytest.approx(1.0)


def test_lazy_full_page_penalty(minimal_example):
    from focusparse._parser_bench import BBox
    from focusparse.eval.scoring import score_evidence_reward

    # Correct + IoU=1.0 but crop covers 80% of page → penalty kicks in.
    reward = score_evidence_reward(
        prediction_text="1096",
        predicted_pages=[1],
        predicted_bboxes=[BBox(page=1, x0=100, y0=100, x1=300, y1=200)],
        tool_calls=[{"tool": "inspect_region", "args": {}}],
        example=minimal_example,
        largest_crop_area_ratio=0.8,
    )
    assert reward == pytest.approx(0.8)


def test_wrong_answer_zero_reward(minimal_example):
    from focusparse._parser_bench import BBox
    from focusparse.eval.scoring import score_evidence_reward

    reward = score_evidence_reward(
        prediction_text="9999",
        predicted_pages=[1],
        predicted_bboxes=[BBox(page=1, x0=100, y0=100, x1=300, y1=200)],
        tool_calls=[{"tool": "inspect_region", "args": {}}],
        example=minimal_example,
    )
    assert reward == 0.0


# ---------------------------------------------------------------------------
# Coordinate-space handling (focus agent vs simple agent convention)
# ---------------------------------------------------------------------------


def test_max_iou_handles_mixed_coord_spaces(parser_bench_submodule_present):
    """Gold bboxes are absolute pixel coords; focus-agent predictions are
    normalized [0,1]. IoU must still match when `image_dims_by_page` is
    provided — this was the bug the smoke test exposed.
    """
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required for BenchmarkExample")

    from focusparse._parser_bench import (
        AnswerType,
        BBox,
        BenchmarkExample,
        DifficultyScores,
        Domain,
    )
    from focusparse.eval.scoring import max_iou_over_alternates

    example = BenchmarkExample(
        id="mix-0001",
        domain=Domain.DATASHEET,
        source_pdf="fake.pdf",
        page_images=["fake_page_1.png"],
        question="q?",
        answer="x",
        answer_type=AnswerType.EXACT_MATCH,
        supporting_pages=[1],
        # Pixel-space gold: 1650-2842 x 532-1478 on a 3000x2250 image.
        supporting_bboxes=[BBox(page=1, x0=1650.0, y0=532.0, x1=2842.0, y1=1478.0)],
        difficulty=DifficultyScores(visual=1, reasoning=1, localization=1),
        question_family="single_value_lookup",
    )

    # Normalized predicted bbox (exactly the gold region normalized).
    pred = [BBox(page=1, x0=0.55, y0=0.2364, x1=0.9473, y1=0.6569)]

    # Without dims → coord-space mismatch, IoU approaches 0.
    iou_broken = max_iou_over_alternates(pred, example)
    assert iou_broken < 0.01

    # With dims → both sides normalized, IoU ≈ 1.0.
    iou_fixed = max_iou_over_alternates(
        pred,
        example,
        image_dims_by_page={1: (3000, 2250)},
    )
    assert iou_fixed > 0.99


def test_max_iou_no_change_when_both_sides_already_unit(parser_bench_submodule_present):
    """If both gold and predicted are already in [0,1], providing image dims
    should be a no-op — nothing to normalize, IoU unchanged."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required for BenchmarkExample")

    from focusparse._parser_bench import (
        AnswerType,
        BBox,
        BenchmarkExample,
        DifficultyScores,
        Domain,
    )
    from focusparse.eval.scoring import max_iou_over_alternates

    example = BenchmarkExample(
        id="unit-0001",
        domain=Domain.DATASHEET,
        source_pdf="fake.pdf",
        page_images=["fake_page_1.png"],
        question="q?",
        answer="x",
        answer_type=AnswerType.EXACT_MATCH,
        supporting_pages=[1],
        supporting_bboxes=[BBox(page=1, x0=0.1, y0=0.1, x1=0.5, y1=0.5)],
        difficulty=DifficultyScores(visual=1, reasoning=1, localization=1),
        question_family="single_value_lookup",
    )
    pred = [BBox(page=1, x0=0.1, y0=0.1, x1=0.5, y1=0.5)]

    assert max_iou_over_alternates(pred, example) == pytest.approx(1.0)
    assert max_iou_over_alternates(
        pred, example, image_dims_by_page={1: (3000, 2250)}
    ) == pytest.approx(1.0)


def test_max_iou_falls_through_when_dims_map_missing_page(
    parser_bench_submodule_present,
):
    """Page not in dims map → degrade to raw-coord comparison, not crash."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required for BenchmarkExample")

    from focusparse._parser_bench import (
        AnswerType,
        BBox,
        BenchmarkExample,
        DifficultyScores,
        Domain,
    )
    from focusparse.eval.scoring import max_iou_over_alternates

    example = BenchmarkExample(
        id="partial-0001",
        domain=Domain.DATASHEET,
        source_pdf="fake.pdf",
        page_images=["fake_page_1.png"],
        question="q?",
        answer="x",
        answer_type=AnswerType.EXACT_MATCH,
        supporting_pages=[1],
        supporting_bboxes=[BBox(page=1, x0=100, y0=100, x1=500, y1=500)],
        difficulty=DifficultyScores(visual=1, reasoning=1, localization=1),
        question_family="single_value_lookup",
    )
    pred = [BBox(page=1, x0=100, y0=100, x1=500, y1=500)]

    # Dims map doesn't cover page 1 → fall through to raw comparison (both
    # sides happen to be in pixel space, so IoU = 1.0).
    iou = max_iou_over_alternates(pred, example, image_dims_by_page={2: (100, 100)})
    assert iou == pytest.approx(1.0)


def test_score_evidence_reward_respects_coord_space_fix(
    parser_bench_submodule_present,
):
    """The smoke-test scenario: correct answer + normalized pred + pixel gold.
    Without dims → reward 0 (the bug). With dims → reward 1.0."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required for BenchmarkExample")

    from focusparse._parser_bench import (
        AnswerType,
        BBox,
        BenchmarkExample,
        DifficultyScores,
        Domain,
    )
    from focusparse.eval.scoring import score_evidence_reward

    example = BenchmarkExample(
        id="reward-0001",
        domain=Domain.DATASHEET,
        source_pdf="fake.pdf",
        page_images=["fake_page_1.png"],
        question="q?",
        answer="42",
        answer_type=AnswerType.NUMERIC,
        answer_unit="count",
        tolerance=0.01,
        supporting_pages=[1],
        supporting_bboxes=[BBox(page=1, x0=1500.0, y0=1000.0, x1=2000.0, y1=1500.0)],
        difficulty=DifficultyScores(visual=1, reasoning=1, localization=1),
        question_family="single_value_lookup",
    )
    pred = [BBox(page=1, x0=0.5, y0=0.4444, x1=0.6667, y1=0.6667)]  # ≈gold normalized

    buggy = score_evidence_reward(
        prediction_text="42",
        predicted_pages=[1],
        predicted_bboxes=pred,
        tool_calls=[{"tool": "inspect_region"}],
        example=example,
    )
    assert buggy == 0.0  # coord-space mismatch zeroed the reward

    fixed = score_evidence_reward(
        prediction_text="42",
        predicted_pages=[1],
        predicted_bboxes=pred,
        tool_calls=[{"tool": "inspect_region"}],
        example=example,
        image_dims_by_page={1: (3000, 2250)},
    )
    assert fixed > 0.95  # answer=1 × recall=1 × IoU≈1 ≈ 1.0
