"""Tests for scripts/related_work_monitor.py."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "related_work_monitor.py"


def _load_monitor_module():
    spec = importlib.util.spec_from_file_location("_related_work_monitor_under_test", SCRIPT_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _write_fake_run(root: Path, *, agent: str = "simple", protocol: str = "agentic_multi_page") -> Path:
    run_dir = root / "focusparse_simple_agentic_multi_page_deadbeef"
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "agent": agent,
                "protocol": protocol,
                "tool_set": "full",
                "ended_at": 1,
                "aggregate": {
                    "n": 2,
                    "accuracy": 0.5,
                    "usd_per_correct": 0.01,
                    "latency_ms_mean": 1000.0,
                    "page_recall_mean": 1.0,
                    "bbox_iou_mean": 0.5,
                    "evidence_reward_mean": 0.5,
                    "lazy_answer_rate": 0.0,
                    "tool_calls_mean": 0.0,
                },
                "aggregate_by_domain": {
                    "_overall": {
                        "n": 2,
                        "accuracy": 0.5,
                        "accuracy_ci": [0.0, 1.0],
                        "usd_per_correct": 0.01,
                        "usd_per_correct_ci": [0.01, 0.02],
                        "latency_ms_mean": 1000.0,
                        "page_recall_mean": 1.0,
                        "bbox_iou_mean": 0.5,
                        "usd_total": 0.01,
                    }
                },
            }
        )
    )
    (run_dir / "per_example.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"example_id": "a", "answer_correct": 1}),
                json.dumps({"example_id": "b", "answer_correct": 0}),
            ]
        )
        + "\n"
    )
    (root / f"{run_dir.name}.json").write_text(
        json.dumps(
            {
                "config_key": run_dir.name,
                "agent": agent,
                "protocol": protocol,
                "tool_set": "full",
                "hf_repo": "gabrielbo/parser-bench",
                "hf_split": "validation",
                "hf_revision": "3774c67f8b814392b6d04c939e904f749a3f52eb",
                "dataset_fingerprint": {"num_rows": 2, "fingerprint": "fixture"},
            }
        )
    )
    return run_dir


def test_scan_runs_loads_wrapper_and_per_example(tmp_path: Path) -> None:
    monitor = _load_monitor_module()
    root = tmp_path / "results"
    _write_fake_run(root)

    runs = monitor._scan_runs([root])

    assert len(runs) == 1
    assert runs[0]["agent"] == "simple"
    assert runs[0]["protocol"] == "agentic_multi_page"
    assert runs[0]["hf_revision"] == monitor.PINNED_HF_REVISION
    assert runs[0]["per_example_count"] == 2
    assert runs[0]["unique_example_ids"] == 2


def test_registry_marks_verified_when_count_and_revision_match(tmp_path: Path) -> None:
    monitor = _load_monitor_module()
    root = tmp_path / "results"
    _write_fake_run(root)
    runs = monitor._scan_runs([root])
    spec = monitor.ExpectedRun(
        method_id="fixture",
        label="Fixture",
        branch="codex/fixture",
        worktree=str(tmp_path),
        agent="simple",
        protocol="agentic_multi_page",
        expected_n=2,
    )

    rows = monitor._registry_rows([spec], runs)

    assert rows[0]["status"] == "verified"
    assert rows[0]["run"]["aggregate"]["accuracy"] == 0.5


def test_headline_table_preserves_missing_rows(tmp_path: Path) -> None:
    monitor = _load_monitor_module()
    spec = monitor.ExpectedRun(
        method_id="missing",
        label="Missing Method",
        branch="codex/missing",
        worktree=str(tmp_path / "missing"),
        agent="missing_agent",
        protocol="agentic_multi_page",
        headline=True,
    )

    rows = monitor._registry_rows([spec], [])
    table = monitor._headline_table(rows, "fixture")

    assert table["rows"][0]["missing"] is True
    assert table["rows"][0]["status"] == "planned"
