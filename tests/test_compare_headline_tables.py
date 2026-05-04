"""Tests for scripts/compare_headline_tables.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import compare_headline_tables as cht  # noqa: E402


def _table(rows: list[dict]) -> dict:
    return {"generated_at": "fixture", "protocol": "agentic_multi_page", "specs": [], "rows": rows}


def _row(
    *,
    label: str,
    overall_acc: float,
    overall_ci: tuple[float, float],
    finance_acc: float = 0.0,
    finance_ci: tuple[float, float] = (0.0, 0.0),
    overall_usd: float = 0.01,
) -> dict:
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
                "usd_per_correct": overall_usd,
                "usd_per_correct_ci": [overall_usd * 0.8, overall_usd * 1.2],
                "bbox_iou": 0.5,
                "page_recall": 0.9,
                "usd_total": 1.0,
            },
            "datasheet": {
                "n": 101,
                "accuracy": overall_acc,
                "accuracy_ci": list(overall_ci),
                "usd_per_correct": overall_usd,
                "usd_per_correct_ci": [overall_usd * 0.8, overall_usd * 1.2],
                "bbox_iou": 0.5,
                "page_recall": 0.9,
            },
            "finance": {
                "n": 47,
                "accuracy": finance_acc,
                "accuracy_ci": list(finance_ci),
                "usd_per_correct": overall_usd,
                "usd_per_correct_ci": [overall_usd * 0.8, overall_usd * 1.2],
                "bbox_iou": 0.5,
                "page_recall": 0.9,
            },
        },
    }


# ---------------------------------------------------------------------------
# CI overlap + gate marker
# ---------------------------------------------------------------------------


def test_ci_overlap_disjoint_returns_false() -> None:
    assert cht._ci_overlap([0.0, 0.3], [0.4, 0.6]) is False


def test_ci_overlap_touching_is_overlap() -> None:
    assert cht._ci_overlap([0.0, 0.3], [0.3, 0.6]) is True


def test_ci_overlap_one_inside_other_is_overlap() -> None:
    assert cht._ci_overlap([0.0, 0.6], [0.2, 0.4]) is True


def test_ci_overlap_none_treated_as_overlap() -> None:
    """Missing CI is conservative — we can't conclude separation."""
    assert cht._ci_overlap(None, [0.2, 0.4]) is True
    assert cht._ci_overlap([0.0, 0.3], None) is True


def test_gate_marker_ship_when_3pp_non_overlapping() -> None:
    g = cht._gate_marker(delta=0.05, ci_overlap=False, metric="accuracy")
    assert g == "✅ ship"


def test_gate_marker_sig_plus_when_positive_non_overlap_under_3pp() -> None:
    g = cht._gate_marker(delta=0.02, ci_overlap=False, metric="accuracy")
    assert g == "🟢 sig+"


def test_gate_marker_hold_when_overlapping_positive() -> None:
    g = cht._gate_marker(delta=0.05, ci_overlap=True, metric="accuracy")
    assert g == "🟡 hold"


def test_gate_marker_regress_when_minus_3pp() -> None:
    g = cht._gate_marker(delta=-0.05, ci_overlap=True, metric="accuracy")
    assert g == "⚠ regress"


def test_gate_marker_noise_when_small_negative() -> None:
    g = cht._gate_marker(delta=-0.01, ci_overlap=True, metric="accuracy")
    assert g == "🟠 noise-"


def test_gate_marker_flips_sign_for_usd_per_correct() -> None:
    """Lower $/correct is better — a -$0.05 delta past the threshold ships."""
    g = cht._gate_marker(delta=-0.05, ci_overlap=False, metric="usd_per_correct")
    assert g == "✅ ship"


def test_gate_marker_none_delta_returns_dash() -> None:
    assert cht._gate_marker(delta=None, ci_overlap=False, metric="accuracy") == "—"


# ---------------------------------------------------------------------------
# Cell extraction
# ---------------------------------------------------------------------------


def test_cell_returns_value_and_ci() -> None:
    row = _row(label="x", overall_acc=0.4, overall_ci=(0.3, 0.5))
    val, ci = cht._cell(row, "_overall", "accuracy")
    assert val == 0.4
    assert ci == [0.3, 0.5]


def test_cell_missing_metric_returns_none() -> None:
    row = _row(label="x", overall_acc=0.4, overall_ci=(0.3, 0.5))
    val, ci = cht._cell(row, "_overall", "non_existent")
    assert val is None
    assert ci is None


def test_cell_missing_row_returns_none() -> None:
    val, ci = cht._cell(None, "_overall", "accuracy")
    assert val is None
    assert ci is None


def test_cell_missing_domain_returns_none() -> None:
    row = _row(label="x", overall_acc=0.4, overall_ci=(0.3, 0.5))
    val, ci = cht._cell(row, "missing_domain", "accuracy")
    assert val is None
    assert ci is None


# ---------------------------------------------------------------------------
# Render markdown / JSON
# ---------------------------------------------------------------------------


def test_render_markdown_contains_method_labels() -> None:
    a = _table([_row(label="Base VLM", overall_acc=0.39, overall_ci=(0.31, 0.47))])
    b = _table([_row(label="Base VLM", overall_acc=0.45, overall_ci=(0.37, 0.53))])
    md = cht.render_markdown(a, b, label_a="v1", label_b="v2")
    assert "## Base VLM" in md
    assert "v1" in md
    assert "v2" in md


def test_render_markdown_filter_method_drops_others() -> None:
    a = _table(
        [
            _row(label="Base VLM", overall_acc=0.4, overall_ci=(0.3, 0.5)),
            _row(label="Our harness +4 tools", overall_acc=0.45, overall_ci=(0.36, 0.54)),
        ]
    )
    b = _table(
        [
            _row(label="Base VLM", overall_acc=0.4, overall_ci=(0.3, 0.5)),
            _row(label="Our harness +4 tools", overall_acc=0.55, overall_ci=(0.46, 0.64)),
        ]
    )
    md = cht.render_markdown(
        a, b, label_a="v1", label_b="v2", filter_methods=["Our harness +4 tools"]
    )
    assert "## Our harness +4 tools" in md
    assert "## Base VLM" not in md


def test_to_json_emits_per_cell_gates() -> None:
    """Non-overlapping +15pp shows up as ship in the JSON."""
    a = _table([_row(label="Our harness +4 tools", overall_acc=0.40, overall_ci=(0.32, 0.46))])
    b = _table([_row(label="Our harness +4 tools", overall_acc=0.60, overall_ci=(0.52, 0.68))])
    payload = cht.to_json(a, b, label_a="v1", label_b="v2")
    cells = payload["rows"][0]["cells"]
    overall_acc = next(c for c in cells if c["domain"] == "_overall" and c["metric"] == "accuracy")
    assert overall_acc["delta"] == pytest.approx(0.20)
    assert overall_acc["ci_overlap"] is False
    assert overall_acc["gate"] == "✅ ship"


def test_to_json_handles_missing_baseline_row() -> None:
    """If a method appears in B but not A, deltas are None but the row renders."""
    a = _table([])
    b = _table([_row(label="New Method", overall_acc=0.5, overall_ci=(0.4, 0.6))])
    payload = cht.to_json(a, b, label_a="v1", label_b="v2")
    assert len(payload["rows"]) == 1
    cells = payload["rows"][0]["cells"]
    assert all(c["delta"] is None for c in cells)


def test_round_trip_via_json_files(tmp_path: Path) -> None:
    """End-to-end: write two JSON files, run the script's render, verify output."""
    a_path = tmp_path / "a.json"
    b_path = tmp_path / "b.json"
    a_path.write_text(json.dumps(_table([_row(label="x", overall_acc=0.4, overall_ci=(0.3, 0.5))])))
    b_path.write_text(json.dumps(_table([_row(label="x", overall_acc=0.5, overall_ci=(0.4, 0.6))])))
    a_table = json.loads(a_path.read_text())
    b_table = json.loads(b_path.read_text())
    md = cht.render_markdown(a_table, b_table, label_a="A", label_b="B")
    assert "+10.0pp" in md or "+10.1pp" in md  # tolerate float repr edge


def test_format_helpers_handle_none() -> None:
    assert cht._format_value(None, "accuracy") == "—"
    assert cht._format_delta(None, "accuracy") == "—"


def test_format_value_renders_percent_for_accuracy() -> None:
    assert cht._format_value(0.42, "accuracy") == "42.0%"


def test_format_value_renders_money_for_usd() -> None:
    assert cht._format_value(0.012, "usd_per_correct") == "$0.0120"
