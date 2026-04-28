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


# ---------------------------------------------------------------------------
# answer_type routing — pin behavior under enum + string repr forms
# (regression: AnswerType.NUMERIC was falling through to exact_match because
#  endswith("numeric") never matched "AnswerType.NUMERIC")
# ---------------------------------------------------------------------------


def _example_with_type(answer_type, *, answer="42", tolerance=None):
    from focusparse._parser_bench import (
        BBox,
        BenchmarkExample,
        DifficultyScores,
        Domain,
    )

    return BenchmarkExample(
        id="test-route",
        domain=Domain.FINANCE,
        source_pdf="fake.pdf",
        page_images=["fake_page_1.png"],
        question="?",
        answer=answer,
        answer_type=answer_type,
        tolerance=tolerance,
        supporting_pages=[1],
        supporting_bboxes=[BBox(page=1, x0=0, y0=0, x1=1, y1=1)],
        difficulty=DifficultyScores(visual=1, reasoning=1, localization=1),
        question_family="single_value_lookup",
    )


def test_answer_type_stem_normalizes_enum_and_string():
    from focusparse._parser_bench import AnswerType
    from focusparse.eval.scoring import _answer_type_stem

    # Enum value
    assert _answer_type_stem(AnswerType.NUMERIC) == "numeric"
    # str(enum) form (`"AnswerType.NUMERIC"`)
    assert _answer_type_stem(str(AnswerType.NUMERIC)) == "numeric"
    # Bare lowercase string
    assert _answer_type_stem("numeric") == "numeric"
    # Bare uppercase string
    assert _answer_type_stem("NUMERIC") == "numeric"


def test_score_answer_routes_numeric_via_enum(parser_bench_submodule_present):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    from focusparse._parser_bench import AnswerType
    from focusparse.eval.scoring import score_answer

    ex = _example_with_type(AnswerType.NUMERIC, answer="40", tolerance=10.0)
    # Within absolute tolerance of 10 → 1.0 (was 0.0 before the fix)
    assert score_answer("50", ex) == 1.0
    # Outside tolerance → 0.0
    assert score_answer("55", ex) == 0.0


def test_score_answer_routes_unanswerable_via_enum(parser_bench_submodule_present):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    from focusparse._parser_bench import AnswerType
    from focusparse.eval.scoring import score_answer

    ex = _example_with_type(AnswerType.UNANSWERABLE, answer="N/A")
    assert score_answer("Unanswerable", ex) == 1.0
    assert score_answer("cannot be determined", ex) == 1.0
    assert score_answer("42", ex) == 0.0


def test_score_answer_routes_boolean_via_enum(parser_bench_submodule_present):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    from focusparse._parser_bench import AnswerType
    from focusparse.eval.scoring import score_answer

    ex = _example_with_type(AnswerType.BOOLEAN, answer="true")
    assert score_answer("yes", ex) == 1.0
    assert score_answer("Y", ex) == 1.0
    assert score_answer("no", ex) == 0.0


def test_score_answer_routes_multiple_choice_via_enum(parser_bench_submodule_present):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    from focusparse._parser_bench import AnswerType
    from focusparse.eval.scoring import score_answer

    ex = _example_with_type(AnswerType.MULTIPLE_CHOICE, answer="C")
    assert score_answer("C", ex) == 1.0
    assert score_answer("c. some explanation", ex) == 1.0
    assert score_answer("D", ex) == 0.0


def test_score_numeric_uses_absolute_tolerance(parser_bench_submodule_present):
    """Parser-bench parity: tolerance is an absolute delta, not relative."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    from focusparse.eval.scoring import _score_numeric

    # gold=40, pred=50, tol=10.0 → |10| ≤ 10 → 1.0
    assert _score_numeric("50", "40", 10.0) == 1.0
    # gold=40, pred=51, tol=10.0 → |11| > 10 → 0.0
    assert _score_numeric("51", "40", 10.0) == 0.0
    # FP-precision edge: |1.1 - 1.0| is 0.10000000000000009; epsilon absorbs it.
    assert _score_numeric("1.1", "1.0", 0.1) == 1.0
    # gold=40, pred=40 → exact match
    assert _score_numeric("40", "40", 0.0) == 1.0


def test_score_numeric_falls_back_to_one_percent_relative_when_no_tolerance():
    """Parser-bench parity: relative tolerance is 1% of max(|gold|, 1.0)."""
    from focusparse.eval.scoring import _score_numeric

    # gold=100, pred=101 → |1| ≤ 1.0 → 1.0
    assert _score_numeric("101", "100", None) == 1.0
    # gold=100, pred=102 → |2| > 1 → 0.0
    assert _score_numeric("102", "100", None) == 0.0
    # gold=0, pred=0 → exact → 1.0
    assert _score_numeric("0", "0", None) == 1.0
    # gold=0, pred=0.5 → 0.5 ≤ 0.01*max(0,1)=0.01 → False → 0.0
    assert _score_numeric("0.5", "0", None) == 0.0
    # Small-gold floor: gold=0.5, pred=0.51 → tol = 0.01*max(0.5,1)=0.01,
    # |0.01| ≤ 0.01 → 1.0 (matches parser-bench, gives small golds room).
    assert _score_numeric("0.51", "0.5", None) == 1.0


def test_score_answer_extracts_number_from_prose_when_numeric(parser_bench_submodule_present):
    """Real model output: '50%' should match gold='40%' under tol=10 absolute."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    from focusparse._parser_bench import AnswerType
    from focusparse.eval.scoring import score_answer

    ex = _example_with_type(AnswerType.NUMERIC, answer="40%", tolerance=10.0)
    assert score_answer("50%", ex) == 1.0
    assert score_answer("About 50%", ex) == 1.0
    # First-number extraction: "2 outputs" → 2 matches gold "2"
    ex2 = _example_with_type(AnswerType.NUMERIC, answer="2", tolerance=0.0)
    assert score_answer("2 outputs", ex2) == 1.0


# ---------------------------------------------------------------------------
# Phase 4: parser-bench parity for exact_match / boolean / multiple_choice
# ---------------------------------------------------------------------------


def test_exact_match_verbatim():
    from focusparse.eval.scoring import _score_exact_match

    assert _score_exact_match("0x44", "0x44") is True
    assert _score_exact_match("0x44.", "0x44") is True  # trailing punctuation stripped
    assert _score_exact_match("0X44", "0x44") is True  # case-insensitive


def test_exact_match_separator_split_on_gold():
    """Gold='MEMORY; it occurs after EXECUTE...' pred='MEMORY' → match core."""
    from focusparse.eval.scoring import _score_exact_match

    gold = "MEMORY; it occurs after EXECUTE and before WRITE"
    assert _score_exact_match("MEMORY", gold) is True
    assert _score_exact_match("memory", gold) is True


def test_exact_match_pred_contains_gold():
    """Gold='0x44' embedded in a longer pred → match (gold ⊂ pred, len ratio ok)."""
    from focusparse.eval.scoring import _score_exact_match

    pred = "After STR/LDRB the value r2 = 0x44 in little-endian."
    # gold len 4, pred len ~55 → 4 / 55 = 0.07 < 0.4 — won't match the
    # containment threshold. This codifies parser-bench's choice.
    assert _score_exact_match(pred, "0x44") is False
    # But a pred that's a verbose version of a longer gold matches:
    long_gold = "Arithmetic Shift Right shifts in the sign bit"
    long_pred = f"{long_gold}. The diagram shows this clearly."
    assert _score_exact_match(long_pred, long_gold) is True


def test_exact_match_gold_contains_pred():
    """Gold='Balance Sheets, page 52' pred='Balance Sheets' → match."""
    from focusparse.eval.scoring import _score_exact_match

    assert _score_exact_match("Balance Sheets", "Balance Sheets, page 52") is True
    # Too-short pred (< 3 chars) doesn't match
    assert _score_exact_match("Ba", "Balance Sheets, page 52") is False


def test_exact_match_parenthetical_removal():
    """X (Y) ≡ X."""
    from focusparse.eval.scoring import _score_exact_match

    full = "Irish Data Protection Commission (IDPC)"
    short = "Irish Data Protection Commission"
    assert _score_exact_match(short, full) is True
    assert _score_exact_match(full, short) is True


def test_score_boolean_token_tolerance():
    from focusparse.eval.scoring import _score_boolean

    assert _score_boolean("yes", "true") is True
    assert _score_boolean("Yes, the device meets the spec.", "true") is True
    assert _score_boolean("no, it does not", "false") is True
    assert _score_boolean("Y", "yes") is True
    assert _score_boolean("incorrect", "false") is True
    assert _score_boolean("yes", "no") is False


def test_score_multiple_choice_standalone_letter():
    from focusparse.eval.scoring import _score_multiple_choice

    assert _score_multiple_choice("B", "B") is True
    assert _score_multiple_choice("(B)", "B") is True
    assert _score_multiple_choice("The answer is C.", "C") is True
    # Standalone letter wins over embedded letters in words
    assert _score_multiple_choice("Bandwidth answer is B", "B") is True
    assert _score_multiple_choice("D", "B") is False


def test_extract_float_handles_units_and_currency():
    from focusparse.eval.scoring import _extract_float

    assert _extract_float("$1,234.56") == 1234.56
    assert _extract_float("42 USD") == 42.0
    assert _extract_float("5.5V") == 5.5
    assert _extract_float("40%") == 40.0
    # Prose-wrapped fallback
    assert _extract_float("The aspect ratio is approximately 1.0 (units of mm)") == 1.0
    # No number present
    assert _extract_float("foo bar") is None
