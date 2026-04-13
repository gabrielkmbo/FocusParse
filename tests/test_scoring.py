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
