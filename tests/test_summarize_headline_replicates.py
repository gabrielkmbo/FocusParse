"""Tests for scripts/summarize_headline_replicates.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import summarize_headline_replicates as shr  # noqa: E402


def _table(rows: list[dict]) -> dict:
    return {"generated_at": "fixture", "protocol": "agentic_multi_page", "rows": rows}


def _row(label: str, *, overall_acc: float, overall_ci: tuple[float, float]) -> dict:
    return {
        "label": label,
        "agent": "focus",
        "tool_set": "full",
        "n_total": 148,
        "by_domain": {
            "_overall": {
                "n": 148,
                "accuracy": overall_acc,
                "accuracy_ci": list(overall_ci),
                "usd_per_correct": 0.02,
                "usd_per_correct_ci": [0.01, 0.03],
                "bbox_iou": 0.50,
                "bbox_iou_ci": [0.45, 0.55],
            },
            "datasheet": {
                "n": 101,
                "accuracy": overall_acc,
                "accuracy_ci": list(overall_ci),
                "usd_per_correct": 0.02,
                "usd_per_correct_ci": [0.01, 0.03],
                "bbox_iou": 0.50,
                "bbox_iou_ci": [0.45, 0.55],
            },
            "finance": {
                "n": 47,
                "accuracy": overall_acc,
                "accuracy_ci": list(overall_ci),
                "usd_per_correct": 0.02,
                "usd_per_correct_ci": [0.01, 0.03],
                "bbox_iou": 0.50,
                "bbox_iou_ci": [0.45, 0.55],
            },
        },
    }


def _overall_accuracy_cell(summary: dict) -> dict:
    return next(
        cell
        for cell in summary["rows"][0]["cells"]
        if cell["domain"] == "_overall" and cell["metric"] == "accuracy"
    )


def test_summarize_averages_replicate_values() -> None:
    baseline = _table([_row("Our harness +4 tools", overall_acc=0.439, overall_ci=(0.36, 0.51))])
    run1 = _table([_row("Our harness +4 tools", overall_acc=0.50, overall_ci=(0.42, 0.58))])
    run2 = _table([_row("Our harness +4 tools", overall_acc=0.56, overall_ci=(0.48, 0.64))])

    summary = shr.summarize(
        baseline,
        [run1, run2],
        label_a="baseline",
        label_b="path-a",
        filter_methods=["Our harness +4 tools"],
    )

    cell = _overall_accuracy_cell(summary)
    assert cell["replicate_values"] == [0.50, 0.56]
    assert cell["mean_b"] == pytest.approx(0.53)
    assert cell["delta"] == pytest.approx(0.091)


def test_summarize_uses_conservative_union_ci_for_gate() -> None:
    baseline = _table([_row("Our harness +4 tools", overall_acc=0.40, overall_ci=(0.30, 0.45))])
    run1 = _table([_row("Our harness +4 tools", overall_acc=0.58, overall_ci=(0.52, 0.66))])
    run2 = _table([_row("Our harness +4 tools", overall_acc=0.62, overall_ci=(0.55, 0.70))])

    summary = shr.summarize(
        baseline,
        [run1, run2],
        label_a="baseline",
        label_b="path-a",
        filter_methods=["Our harness +4 tools"],
    )

    cell = _overall_accuracy_cell(summary)
    assert cell["ci_b_union"] == [0.52, 0.70]
    assert cell["ci_overlap"] is False
    assert cell["gate"] == "✅ ship"


def test_missing_ci_is_conservative_overlap() -> None:
    baseline = _table([_row("Our harness +4 tools", overall_acc=0.40, overall_ci=(0.30, 0.45))])
    run1 = _table([_row("Our harness +4 tools", overall_acc=0.58, overall_ci=(0.52, 0.66))])
    run2 = _table([_row("Our harness +4 tools", overall_acc=0.62, overall_ci=(0.55, 0.70))])
    del run2["rows"][0]["by_domain"]["_overall"]["accuracy_ci"]

    summary = shr.summarize(
        baseline,
        [run1, run2],
        label_a="baseline",
        label_b="path-a",
        filter_methods=["Our harness +4 tools"],
    )

    cell = _overall_accuracy_cell(summary)
    assert cell["ci_b_union"] is None
    assert cell["ci_overlap"] is True
    assert cell["gate"] == "🟡 hold"


def test_render_markdown_lists_replicate_values() -> None:
    baseline = _table([_row("Our harness +4 tools", overall_acc=0.439, overall_ci=(0.36, 0.51))])
    run1 = _table([_row("Our harness +4 tools", overall_acc=0.50, overall_ci=(0.42, 0.58))])
    run2 = _table([_row("Our harness +4 tools", overall_acc=0.56, overall_ci=(0.48, 0.64))])
    summary = shr.summarize(
        baseline,
        [run1, run2],
        label_a="rebaseline-v2",
        label_b="path-a",
        filter_methods=["Our harness +4 tools"],
    )

    md = shr.render_markdown(summary)
    assert "Our harness +4 tools" in md
    assert "50.0%, 56.0%" in md
    assert "+9.1pp" in md


def test_cli_writes_markdown_and_json(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    run1_path = tmp_path / "run1.json"
    run2_path = tmp_path / "run2.json"
    output_path = tmp_path / "summary.md"
    json_output_path = tmp_path / "summary.json"
    baseline_path.write_text(
        json.dumps(
            _table([_row("Our harness +4 tools", overall_acc=0.439, overall_ci=(0.36, 0.51))])
        )
    )
    run1_path.write_text(
        json.dumps(
            _table([_row("Our harness +4 tools", overall_acc=0.50, overall_ci=(0.42, 0.58))])
        )
    )
    run2_path.write_text(
        json.dumps(
            _table([_row("Our harness +4 tools", overall_acc=0.56, overall_ci=(0.48, 0.64))])
        )
    )

    old_argv = sys.argv
    try:
        sys.argv = [
            "summarize_headline_replicates.py",
            str(baseline_path),
            str(run1_path),
            str(run2_path),
            "--label-a",
            "rebaseline-v2",
            "--label-b",
            "path-a",
            "--filter-method",
            "Our harness +4 tools",
            "--output",
            str(output_path),
            "--json-output",
            str(json_output_path),
        ]
        shr.main()
    finally:
        sys.argv = old_argv

    assert "Replicated headline-table deltas" in output_path.read_text()
    payload = json.loads(json_output_path.read_text())
    assert payload["n_replicates"] == 2
