"""Tests for `scripts/diff_runs.py`.

The diff harness is the gate for Phase 2 items 3-5: each item ships only
if its diff vs a stable baseline shows a positive delta on the metric it
was supposed to improve. These tests pin down the diff math + format so
the harness is reliable to read at PR-review time.

Pure-function tests on the helpers; the CLI itself is tested via subprocess
with synthetic run.json inputs.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

_DIFF_RUNS = Path(__file__).resolve().parent.parent / "scripts" / "diff_runs.py"


def _import_diff_runs():
    """Load `scripts/diff_runs.py` as a module so we can unit-test helpers."""
    spec = importlib.util.spec_from_file_location("diff_runs", _DIFF_RUNS)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------


def test_metric_paths_flattens_nested_dicts():
    dr = _import_diff_runs()
    paths = dr._metric_paths(
        {
            "n": 5,
            "routing": {"page_recall_at_1": 0.8, "pages_inspected_mean": 1.2},
            "efficiency_by_stage": {
                "answer": {"tokens": 1000, "usd": 0.005},
            },
        }
    )
    assert "n" in paths
    assert "routing.page_recall_at_1" in paths
    assert "routing.pages_inspected_mean" in paths
    assert "efficiency_by_stage.answer.tokens" in paths
    assert "efficiency_by_stage.answer.usd" in paths


def test_get_path_returns_none_for_missing():
    dr = _import_diff_runs()
    d = {"routing": {"page_recall_at_1": 0.8}}
    assert dr._get_path(d, "routing.page_recall_at_1") == 0.8
    assert dr._get_path(d, "routing.missing") is None
    assert dr._get_path(d, "missing.path") is None


def test_delta_returns_b_minus_a_for_numeric():
    dr = _import_diff_runs()
    assert dr._delta(0.5, 0.7) == pytest_approx(0.2)
    assert dr._delta(10, 5) == pytest_approx(-5.0)


def test_delta_returns_none_for_non_numeric():
    dr = _import_diff_runs()
    assert dr._delta(None, 0.5) is None
    assert dr._delta("abc", 0.5) is None
    assert dr._delta(0.5, None) is None


def test_section_groups_metrics_by_stage():
    dr = _import_diff_runs()
    rows = ["loop.retries_mean", "n", "routing.page_recall_at_1", "reasoning.answer_correct"]
    rows.sort(key=lambda m: dr._section(m))
    # n first, routing second, reasoning third, loop fourth (per the order map).
    assert rows[0] == "n"
    assert rows[1] == "routing.page_recall_at_1"
    assert rows[2] == "reasoning.answer_correct"
    assert rows[3] == "loop.retries_mean"


def test_direction_label_flags_lower_is_better():
    dr = _import_diff_runs()
    assert dr._direction_label("localization.lazy_full_page_rate") == "lower-is-better"
    assert dr._direction_label("localization.duplicate_crop_rate") == "lower-is-better"
    assert dr._direction_label("loop.retries_mean") == "tradeoff"
    assert dr._direction_label("efficiency_by_stage.answer.tokens") == "tradeoff"
    assert dr._direction_label("reasoning.answer_correct") == ""


def test_fmt_delta_marks_lower_is_better_regression():
    dr = _import_diff_runs()
    # Positive delta on lower-is-better metric → flagged as bad
    assert "↑bad" in dr._fmt_delta(0.05, "lower-is-better")
    # Negative delta on lower-is-better → good
    assert "↓good" in dr._fmt_delta(-0.05, "lower-is-better")
    # Positive delta on neutral metric → good
    assert "↑good" in dr._fmt_delta(0.05, "")
    # Tradeoff metric: no judgment marker
    s = dr._fmt_delta(700.0, "tradeoff")
    assert "↑bad" not in s and "↓good" not in s


def test_build_rows_skips_dual_none_metrics():
    """When both runs have None for a metric, the row is omitted."""
    dr = _import_diff_runs()
    a = {"routing": {"page_recall_at_1": None, "pages_inspected_mean": 1.0}}
    b = {"routing": {"page_recall_at_1": None, "pages_inspected_mean": 2.0}}
    rows = dr._build_rows(a, b)
    paths = [r["metric"] for r in rows]
    # page_recall_at_1 was None on both → skipped
    assert "routing.page_recall_at_1" not in paths
    # pages_inspected_mean had values on both → kept
    assert "routing.pages_inspected_mean" in paths


def test_build_rows_keeps_partial_none():
    """Asymmetric None should still surface — one run might have measured
    the metric while the other didn't."""
    dr = _import_diff_runs()
    a = {"routing": {"page_recall_at_1": 0.7}}
    b = {"routing": {"page_recall_at_1": None}}
    rows = dr._build_rows(a, b)
    assert any(r["metric"] == "routing.page_recall_at_1" for r in rows)


# ---------------------------------------------------------------------------
# CLI smoke (subprocess)
# ---------------------------------------------------------------------------


def _make_run(tmp_path: Path, name: str, stage_aggregate: dict) -> Path:
    p = tmp_path / f"{name}.json"
    p.write_text(json.dumps({"stage_aggregate": stage_aggregate}))
    return p


def test_cli_prints_table_with_deltas(tmp_path):
    baseline = _make_run(
        tmp_path,
        "baseline",
        {
            "n": 5,
            "routing": {
                "page_recall_at_1": 0.6,
                "pages_inspected_mean": 1.0,
            },
            "localization": {
                "region_recall": 0.5,
                "lazy_full_page_rate": 0.3,
            },
            "reasoning": {"answer_correct": 0.4},
            "loop": {"retries_mean": 0.0},
            "loop_terminated_distribution": {"no_loop": 1.0},
            "efficiency_by_stage": {},
        },
    )
    new = _make_run(
        tmp_path,
        "new",
        {
            "n": 5,
            "routing": {
                "page_recall_at_1": 0.8,
                "pages_inspected_mean": 1.2,
            },
            "localization": {
                "region_recall": 0.7,
                "lazy_full_page_rate": 0.1,
            },
            "reasoning": {"answer_correct": 0.55},
            "loop": {"retries_mean": 0.6},
            "loop_terminated_distribution": {"no_loop": 0.5, "accepted": 0.5},
            "efficiency_by_stage": {},
        },
    )
    proc = subprocess.run(
        [sys.executable, str(_DIFF_RUNS), str(baseline), str(new)],
        capture_output=True,
        text=True,
        check=True,
    )
    out = proc.stdout
    # Improvements show up as ↑good
    assert "page_recall_at_1" in out
    assert "↑good" in out
    # Lower-is-better metric improved (lazy_full_page_rate 0.3 → 0.1) → ↓good
    assert "lazy_full_page_rate" in out
    assert "↓good" in out


def test_cli_falls_back_when_stage_aggregate_missing(tmp_path):
    """Legacy run.json without stage_aggregate → the script warns + falls
    through to the top-level aggregate diff."""
    legacy = tmp_path / "legacy.json"
    legacy.write_text(json.dumps({"aggregate": {"accuracy": 0.42, "tokens_in_mean": 500.0}}))
    new = tmp_path / "new.json"
    new.write_text(json.dumps({"aggregate": {"accuracy": 0.55, "tokens_in_mean": 600.0}}))

    proc = subprocess.run(
        [sys.executable, str(_DIFF_RUNS), str(legacy), str(new)],
        capture_output=True,
        text=True,
        check=True,
    )
    # Falls through, prints the legacy table with accuracy + tokens.
    assert "accuracy" in proc.stdout
    assert "tokens_in_mean" in proc.stdout
    # Warning routed to stderr.
    assert "stage_aggregate" in proc.stderr


def test_cli_json_output(tmp_path):
    """`--format json` emits an array of {metric, baseline, new, delta, direction}."""
    baseline = _make_run(
        tmp_path,
        "b",
        {"n": 1, "reasoning": {"answer_correct": 0.5}},
    )
    new = _make_run(
        tmp_path,
        "n",
        {"n": 1, "reasoning": {"answer_correct": 0.8}},
    )
    proc = subprocess.run(
        [sys.executable, str(_DIFF_RUNS), str(baseline), str(new), "--format", "json"],
        capture_output=True,
        text=True,
        check=True,
    )
    rows = json.loads(proc.stdout)
    assert isinstance(rows, list)
    answer_row = next(r for r in rows if r["metric"] == "reasoning.answer_correct")
    assert answer_row["baseline"] == 0.5
    assert answer_row["new"] == 0.8
    assert answer_row["delta"] == pytest_approx(0.3)


# ---------------------------------------------------------------------------
# Helpers (avoid the pytest fixture import noise in unit-test helpers)
# ---------------------------------------------------------------------------


def pytest_approx(value, rel=1e-6):
    """Tiny shim so the helper unit tests don't need to import pytest into
    diff_runs.py itself."""
    import pytest

    return pytest.approx(value, rel=rel)
