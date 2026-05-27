from __future__ import annotations

from scripts.build_paper_ablation_summary import (
    build_pair_keyed_records,
    summarize_pair,
)


def test_build_pair_keyed_records_preserves_duplicate_example_ids() -> None:
    rows = [
        {"example_id": "dup", "answer_correct": 0.0},
        {"example_id": "dup", "answer_correct": 1.0},
        {"example_id": "other", "answer_correct": 1.0},
    ]

    keyed = build_pair_keyed_records(rows)

    assert list(keyed) == [("dup", 1), ("dup", 2), ("other", 1)]


def test_summarize_pair_counts_recoveries_regressions_and_unchanged() -> None:
    baseline = [
        {"example_id": "a", "domain": "Domain.DATASHEET", "answer_correct": 0.0, "bbox_iou": 0.2},
        {"example_id": "b", "domain": "finance", "answer_correct": 1.0, "bbox_iou": 0.8},
        {"example_id": "c", "domain": "datasheet", "answer_correct": 1.0, "bbox_iou": 0.4},
    ]
    treatment = [
        {"example_id": "a", "domain": "datasheet", "answer_correct": 1.0, "bbox_iou": 0.7},
        {"example_id": "b", "domain": "Domain.FINANCE", "answer_correct": 0.0, "bbox_iou": 0.6},
        {"example_id": "c", "domain": "datasheet", "answer_correct": 1.0, "bbox_iou": 0.9},
    ]

    summary = summarize_pair(
        baseline,
        treatment,
        baseline_label="FocusParse +2",
        treatment_label="FocusParse +4",
    )

    assert summary["paired_n"] == 3
    assert summary["recoveries"] == 1
    assert summary["regressions"] == 1
    assert summary["unchanged_correct"] == 1
    assert summary["unchanged_wrong"] == 0
    assert summary["net_correct_delta"] == 0
    assert summary["by_domain"]["datasheet"]["paired_n"] == 2
    assert summary["by_domain"]["finance"]["paired_n"] == 1
