"""Tests for scripts/enrich_headline_table_latency.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import enrich_headline_table_latency as ehtl  # noqa: E402


def _run_dir(root: Path, name: str, rows: list[dict]) -> Path:
    run_dir = root / name
    run_dir.mkdir(parents=True)
    with (run_dir / "per_example.jsonl").open("w") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    return run_dir


def _table(tmp_path: Path) -> tuple[Path, dict]:
    baseline = tmp_path / "baseline" / "headline_table.json"
    baseline.parent.mkdir()
    baseline.write_text("{}")
    summary = tmp_path / "runs" / "focus-mean-replicate-summary.json"
    summary.parent.mkdir()
    summary.write_text("{}")
    table_path = tmp_path / "rollup" / "headline_table.json"
    table_path.parent.mkdir()
    table = {
        "protocol": "agentic_multi_page",
        "baseline": str(baseline),
        "current_focus_plus4_summary": str(summary),
        "rows": [
            {
                "label": "Base VLM",
                "agent": "simple",
                "tool_set": "full",
                "source": "rebaseline-v2",
                "n_total": 2,
                "by_domain": {
                    "_overall": {"n": 2},
                    "datasheet": {"n": 1},
                    "finance": {"n": 1},
                },
            },
            {
                "label": "Our harness +4 tools",
                "agent": "focus",
                "tool_set": "full",
                "source": "current main +4 mean (2 runs)",
                "n_total": 2,
                "by_domain": {
                    "_overall": {"n": 2},
                    "datasheet": {"n": 1},
                    "finance": {"n": 1},
                },
            },
        ],
    }
    table_path.write_text(json.dumps(table))
    return table_path, table


def test_enrich_table_adds_baseline_and_replicate_latency(tmp_path: Path) -> None:
    table_path, table = _table(tmp_path)
    _run_dir(
        tmp_path / "baseline",
        "focusparse_simple_agentic_multi_page_7d4b816d",
        [
            {"domain": "Domain.DATASHEET", "latency_ms": 1000},
            {"domain": "Domain.FINANCE", "latency_ms": 3000},
        ],
    )
    _run_dir(
        tmp_path / "runs" / "focus-mean-run1",
        "focusparse_focus_agentic_multi_page_7d4b816d",
        [
            {"domain": "Domain.DATASHEET", "latency_ms": 2000},
            {"domain": "Domain.FINANCE", "latency_ms": 4000},
        ],
    )
    _run_dir(
        tmp_path / "runs" / "focus-mean-run2",
        "focusparse_focus_agentic_multi_page_7d4b816d",
        [
            {"domain": "Domain.DATASHEET", "latency_ms": 4000},
            {"domain": "Domain.FINANCE", "latency_ms": 6000},
        ],
    )

    enriched = ehtl.enrich_table(table, table_path=table_path, repo_root=tmp_path)

    base = enriched["rows"][0]["by_domain"]
    assert base["_overall"]["latency_ms_mean"] == pytest.approx(2000.0)
    assert base["datasheet"]["latency_ms_mean"] == pytest.approx(1000.0)
    focus = enriched["rows"][1]["by_domain"]
    assert focus["_overall"]["latency_ms_mean"] == pytest.approx(4000.0)
    assert focus["finance"]["latency_ms_mean"] == pytest.approx(5000.0)
    assert focus["_overall"]["latency_ms_runs"] == [3000.0, 5000.0]
