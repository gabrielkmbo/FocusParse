"""Tests for scripts/render_headline_table.py."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import render_headline_table as rht  # noqa: E402


def _table() -> dict:
    return {
        "generated_at": "fixture",
        "protocol": "agentic_multi_page",
        "specs": [],
        "rows": [
            {
                "label": "Our harness +4 tools",
                "agent": "focus",
                "tool_set": "full",
                "n_total": 148,
                "by_domain": {
                    "datasheet": {
                        "n": 101,
                        "accuracy": 0.53,
                        "accuracy_ci": [0.43, 0.63],
                        "usd_per_correct": 0.024,
                        "usd_per_correct_ci": [0.02, 0.03],
                        "latency_ms_mean": 3500.0,
                        "bbox_iou": 0.88,
                        "page_recall": 0.93,
                        "usd_total": 1.2,
                    },
                    "finance": {
                        "n": 47,
                        "accuracy": 0.43,
                        "accuracy_ci": [0.28, 0.57],
                        "usd_per_correct": 0.034,
                        "usd_per_correct_ci": [0.025, 0.053],
                        "latency_ms_mean": 4100.0,
                        "bbox_iou": 0.8,
                        "page_recall": 0.89,
                        "usd_total": 0.7,
                    },
                    "_overall": {
                        "n": 148,
                        "accuracy": 0.5,
                        "accuracy_ci": [0.42, 0.58],
                        "usd_per_correct": 0.026,
                        "usd_per_correct_ci": [0.023, 0.032],
                        "latency_ms_mean": 3691.0,
                        "bbox_iou": 0.86,
                        "page_recall": 0.92,
                        "usd_total": 1.9,
                    },
                },
            }
        ],
    }


def test_flat_rows_emit_method_domain_metrics() -> None:
    rows = rht._flat_rows(_table())

    assert len(rows) == 3
    overall = next(row for row in rows if row["domain"] == "_overall")
    assert overall["method"] == "Our harness +4 tools"
    assert overall["accuracy"] == pytest.approx(0.5)
    assert overall["accuracy_ci_low"] == pytest.approx(0.42)
    assert overall["usd_per_correct_ci_high"] == pytest.approx(0.032)
    assert overall["latency_ms_mean"] == pytest.approx(3691.0)
    assert overall["latency_s_mean"] == pytest.approx(3.691)


def test_csv_and_jsonl_are_machine_readable() -> None:
    csv_rows = list(csv.DictReader(rht._to_csv(_table()).splitlines()))
    jsonl_rows = [json.loads(line) for line in rht._to_jsonl(_table()).splitlines()]

    assert len(csv_rows) == 3
    assert csv_rows[0]["method"] == "Our harness +4 tools"
    assert csv_rows[0]["latency_s_mean"] == "3.5"
    assert len(jsonl_rows) == 3
    assert jsonl_rows[-1]["domain"] == "_overall"
    assert jsonl_rows[-1]["latency_s_mean"] == pytest.approx(3.691)


def test_main_writes_all_rendered_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    table_path = tmp_path / "headline_table.json"
    table_path.write_text(json.dumps(_table()))
    monkeypatch.setattr(sys, "argv", ["render_headline_table.py", str(table_path)])

    assert rht.main() == 0

    assert table_path.with_suffix(".md").exists()
    assert table_path.with_suffix(".html").exists()
    assert table_path.with_suffix(".csv").exists()
    assert table_path.with_suffix(".jsonl").exists()
