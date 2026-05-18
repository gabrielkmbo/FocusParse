"""Monitor and roll up related-work experiment branches.

This script is intentionally read-only with respect to worker branches. It
keeps the experiment coordination branch honest by:

* writing a run registry with the exact expected commands;
* scanning worker result directories for standard FocusParse artifacts;
* producing dataset, protocol-matrix, and headline-table JSON artifacts; and
* rendering a short thesis-oriented status note.

Usage:
    uv run python scripts/related_work_monitor.py --render
    uv run python scripts/related_work_monitor.py --output-dir results/hf/related-work-monitor
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


PINNED_HF_REPO = "gabrielbo/parser-bench"
PINNED_HF_SPLIT = "validation"
PINNED_HF_REVISION = "3774c67f8b814392b6d04c939e904f749a3f52eb"
EXPECTED_CANONICAL_N = 148
DEFAULT_PDFS_ROOT = "~/.cache/focusparse/pdfs"
DEFAULT_FULL_STAGING_DIR = "~/.cache/focusparse/hf_staging_related_work_full"

WORKTREES = {
    "basic_vlm": Path("/private/tmp/focusparse-exp-basic-vlm-protocols"),
    "llamaindex_react": Path("/private/tmp/focusparse-exp-llamaindex-react"),
    "coding_agent": Path("/private/tmp/focusparse-exp-coding-agent"),
    "doclens": Path("/private/tmp/focusparse-exp-doclens-baseline"),
    "agentic_ocr": Path("/private/tmp/focusparse-exp-agenticocr-baseline"),
    "monitor": Path("/private/tmp/focusparse-exp-related-work-monitor"),
}

COMPARATOR_PROTOCOLS = (
    "full_doc",
    "oracle_page",
    "oracle_crop",
    "tiled_2up",
    "tiled_4up",
    "tiled_8up",
    "agentic_multi_page",
)


@dataclass(frozen=True)
class ExpectedRun:
    method_id: str
    label: str
    branch: str
    worktree: str
    agent: str
    protocol: str
    tool_set: str = "full"
    headline: bool = False
    appendix: bool = True
    expected_n: int = EXPECTED_CANONICAL_N
    notes: str = ""

    @property
    def output_dir(self) -> str:
        return f"results/hf/related-work/{self.method_id}"

    @property
    def command(self) -> str:
        parts = [
            "uv",
            "run",
            "python",
            "scripts/run_hf_eval.py",
            "--agent",
            self.agent,
            "--protocol",
            self.protocol,
            "--tool-set",
            self.tool_set,
            "--hf-revision",
            PINNED_HF_REVISION,
            "--staging-dir",
            DEFAULT_FULL_STAGING_DIR,
            "--pdfs-root",
            DEFAULT_PDFS_ROOT,
            "--output-dir",
            self.output_dir,
        ]
        return " ".join(parts)


def _specs() -> list[ExpectedRun]:
    specs: list[ExpectedRun] = [
        ExpectedRun(
            method_id="basic_vlm",
            label="Basic VLM",
            branch="codex/exp-basic-vlm-protocols",
            worktree=str(WORKTREES["basic_vlm"]),
            agent="simple",
            protocol="agentic_multi_page",
            headline=True,
            notes="No-tool baseline on the headline agentic multi-page input.",
        ),
        ExpectedRun(
            method_id="llamaindex_react_minimal",
            label="LlamaIndex ReAct +2",
            branch="codex/exp-llamaindex-react",
            worktree=str(WORKTREES["llamaindex_react"]),
            agent="llamaindex_react",
            protocol="agentic_multi_page",
            tool_set="minimal",
            headline=True,
            notes="Trusted primary ReAct comparator using official LlamaIndex APIs.",
        ),
        ExpectedRun(
            method_id="llamaindex_react_full",
            label="LlamaIndex ReAct +4",
            branch="codex/exp-llamaindex-react",
            worktree=str(WORKTREES["llamaindex_react"]),
            agent="llamaindex_react",
            protocol="agentic_multi_page",
            tool_set="full",
            headline=True,
            notes="Trusted primary ReAct comparator with the full tool belt.",
        ),
        ExpectedRun(
            method_id="coding_agent",
            label="Coding Agent +4",
            branch="codex/exp-coding-agent",
            worktree=str(WORKTREES["coding_agent"]),
            agent="coding_agent",
            protocol="agentic_multi_page",
            headline=True,
            notes="Gemini Agentic Vision style think-act-observe coding comparator.",
        ),
        ExpectedRun(
            method_id="doclens",
            label="DocLens-style",
            branch="codex/exp-doclens-baseline",
            worktree=str(WORKTREES["doclens"]),
            agent="doclens",
            protocol="agentic_multi_page",
            headline=True,
            notes="Faithful DocLens-style proxy: page navigation, element localization, sampling, adjudication.",
        ),
        ExpectedRun(
            method_id="agentic_ocr",
            label="AgenticOCR-style",
            branch="codex/exp-agenticocr-baseline",
            worktree=str(WORKTREES["agentic_ocr"]),
            agent="agentic_ocr",
            protocol="agentic_multi_page",
            headline=True,
            notes="Faithful-lite AgenticOCR proxy over FocusParse inspect-region modes.",
        ),
        ExpectedRun(
            method_id="focusparse_reference",
            label="FocusParse +4",
            branch="codex/exp-related-work-monitor",
            worktree=str(WORKTREES["monitor"]),
            agent="focus",
            protocol="agentic_multi_page",
            headline=True,
            notes="66.9% checkpoint reference; raw artifact must be reproduced or recovered.",
        ),
    ]

    # Appendix protocol sweeps for methods that can consume image/protocol inputs.
    appendix_methods = [
        ("basic_vlm", "Basic VLM", "codex/exp-basic-vlm-protocols", WORKTREES["basic_vlm"], "simple", "full"),
        (
            "llamaindex_react_minimal",
            "LlamaIndex ReAct +2",
            "codex/exp-llamaindex-react",
            WORKTREES["llamaindex_react"],
            "llamaindex_react",
            "minimal",
        ),
        (
            "llamaindex_react_full",
            "LlamaIndex ReAct +4",
            "codex/exp-llamaindex-react",
            WORKTREES["llamaindex_react"],
            "llamaindex_react",
            "full",
        ),
        ("coding_agent", "Coding Agent +4", "codex/exp-coding-agent", WORKTREES["coding_agent"], "coding_agent", "full"),
        ("doclens", "DocLens-style", "codex/exp-doclens-baseline", WORKTREES["doclens"], "doclens", "full"),
        (
            "agentic_ocr",
            "AgenticOCR-style",
            "codex/exp-agenticocr-baseline",
            WORKTREES["agentic_ocr"],
            "agentic_ocr",
            "full",
        ),
    ]
    seen = {(s.method_id, s.protocol, s.tool_set) for s in specs}
    for method_id, label, branch, worktree, agent, tool_set in appendix_methods:
        for protocol in COMPARATOR_PROTOCOLS:
            key = (method_id, protocol, tool_set)
            if key in seen:
                continue
            seen.add(key)
            specs.append(
                ExpectedRun(
                    method_id=method_id,
                    label=label,
                    branch=branch,
                    worktree=str(worktree),
                    agent=agent,
                    protocol=protocol,
                    tool_set=tool_set,
                    headline=False,
                )
            )
    return specs


def _json_load(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            rows.append({"_parse_error": True, "_raw": line[:200]})
    return rows


def _scan_runs(result_roots: list[Path]) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    seen_run_json: set[Path] = set()
    for root in result_roots:
        if not root.exists():
            continue
        for run_json in root.rglob("run.json"):
            run_json = run_json.resolve()
            if run_json in seen_run_json:
                continue
            seen_run_json.add(run_json)
            run_dir = run_json.parent
            run_data = _json_load(run_json) or {}
            wrapper_path = run_dir.parent / f"{run_dir.name}.json"
            wrapper_data = _json_load(wrapper_path) or {}
            per_example_path = run_dir / "per_example.jsonl"
            per_example = _load_jsonl(per_example_path)
            example_ids = sorted(
                {
                    str(row.get("example_id") or row.get("id"))
                    for row in per_example
                    if row.get("example_id") or row.get("id")
                }
            )
            runs.append(
                {
                    "run_dir": str(run_dir),
                    "run_json": str(run_json),
                    "wrapper_json": str(wrapper_path) if wrapper_path.exists() else None,
                    "per_example_jsonl": str(per_example_path) if per_example_path.exists() else None,
                    "config_key": wrapper_data.get("config_key") or run_dir.name,
                    "agent": wrapper_data.get("agent") or run_data.get("agent"),
                    "protocol": wrapper_data.get("protocol") or run_data.get("protocol"),
                    "tool_set": run_data.get("tool_set")
                    or wrapper_data.get("tool_set")
                    or _infer_tool_set(run_dir.name),
                    "hf_repo": wrapper_data.get("hf_repo"),
                    "hf_split": wrapper_data.get("hf_split"),
                    "hf_revision": wrapper_data.get("hf_revision"),
                    "dataset_fingerprint": wrapper_data.get("dataset_fingerprint")
                    or run_data.get("dataset_fingerprint")
                    or {},
                    "aggregate": run_data.get("aggregate") or {},
                    "aggregate_by_domain": run_data.get("aggregate_by_domain") or {},
                    "stage_aggregate": run_data.get("stage_aggregate") or {},
                    "started_at": run_data.get("started_at"),
                    "ended_at": run_data.get("ended_at"),
                    "per_example_count": len(per_example),
                    "unique_example_ids": len(example_ids),
                    "example_ids": example_ids,
                }
            )
    return runs


def _infer_tool_set(config_key: str) -> str:
    if "_tminimal" in config_key:
        return "minimal"
    return "full"


def _implemented(spec: ExpectedRun) -> bool:
    worktree = Path(spec.worktree)
    if spec.agent in {"simple", "focus", "react", "agent_baseline"}:
        return worktree.exists()
    runner = worktree / "scripts" / "run_hf_eval.py"
    if not runner.exists():
        return False
    try:
        return spec.agent in runner.read_text()
    except OSError:
        return False


def _match_run(spec: ExpectedRun, runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [
        run
        for run in runs
        if run.get("agent") == spec.agent
        and run.get("protocol") == spec.protocol
        and (run.get("tool_set") or "full") == spec.tool_set
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda r: str(r.get("ended_at") or r.get("started_at") or ""))[-1]


def _status(spec: ExpectedRun, run: dict[str, Any] | None) -> str:
    if run is None:
        return "implemented" if _implemented(spec) else "planned"
    if run.get("ended_at") is None:
        return "full_running"
    n = int(run.get("per_example_count") or run.get("aggregate", {}).get("n") or 0)
    if _is_verified(spec, run):
        return "verified"
    if n >= spec.expected_n:
        return "full_complete"
    if n > 0:
        return "smoke_passed"
    return "implemented"


def _is_verified(spec: ExpectedRun, run: dict[str, Any]) -> bool:
    n = int(run.get("per_example_count") or run.get("aggregate", {}).get("n") or 0)
    unique_ids = int(run.get("unique_example_ids") or 0)
    revision = run.get("hf_revision")
    return (
        n == spec.expected_n
        and unique_ids == spec.expected_n
        and (revision == PINNED_HF_REVISION or revision is None)
    )


def _metric_cell(metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "n": metrics.get("n", 0),
        "accuracy": metrics.get("accuracy", 0.0),
        "accuracy_ci": metrics.get("accuracy_ci") or [0.0, 0.0],
        "usd_per_correct": metrics.get("usd_per_correct"),
        "usd_per_correct_ci": metrics.get("usd_per_correct_ci"),
        "latency_ms_mean": metrics.get("latency_ms_mean", 0.0),
        "bbox_iou": metrics.get("bbox_iou_mean", metrics.get("bbox_iou", 0.0)),
        "page_recall": metrics.get("page_recall_mean", metrics.get("page_recall", 0.0)),
        "evidence_reward": metrics.get("evidence_reward_mean", 0.0),
        "lazy_answer_rate": metrics.get("lazy_answer_rate", 0.0),
        "tool_calls": metrics.get("tool_calls_mean", 0.0),
        "usd_total": metrics.get("usd_total", 0.0),
    }


def _registry_rows(specs: list[ExpectedRun], runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for spec in specs:
        run = _match_run(spec, runs)
        rows.append(
            {
                **asdict(spec),
                "command": spec.command,
                "output_dir": spec.output_dir,
                "status": _status(spec, run),
                "implemented": _implemented(spec),
                "run": run,
            }
        )
    return rows


def _headline_table(registry_rows: list[dict[str, Any]], generated_at: str) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for row in registry_rows:
        if not row["headline"]:
            continue
        run = row.get("run")
        if not run:
            rows.append(
                {
                    "label": row["label"],
                    "agent": row["agent"],
                    "tool_set": row["tool_set"],
                    "missing": True,
                    "status": row["status"],
                }
            )
            continue
        by_domain = run.get("aggregate_by_domain") or {}
        rows.append(
            {
                "label": row["label"],
                "agent": row["agent"],
                "tool_set": row["tool_set"],
                "status": row["status"],
                "n_total": run.get("aggregate", {}).get("n", run.get("per_example_count", 0)),
                "run_dir": run.get("run_dir"),
                "by_domain": {
                    domain: _metric_cell(metrics) for domain, metrics in by_domain.items()
                },
            }
        )
    return {
        "generated_at": generated_at,
        "protocol": "agentic_multi_page",
        "hf_repo": PINNED_HF_REPO,
        "hf_split": PINNED_HF_SPLIT,
        "hf_revision": PINNED_HF_REVISION,
        "expected_n": EXPECTED_CANONICAL_N,
        "rows": rows,
    }


def _protocol_matrix(registry_rows: list[dict[str, Any]]) -> dict[str, Any]:
    cells: list[dict[str, Any]] = []
    for row in registry_rows:
        run = row.get("run")
        aggregate = (run or {}).get("aggregate", {})
        stage = (run or {}).get("stage_aggregate", {})
        cells.append(
            {
                "method_id": row["method_id"],
                "label": row["label"],
                "agent": row["agent"],
                "tool_set": row["tool_set"],
                "protocol": row["protocol"],
                "headline": row["headline"],
                "status": row["status"],
                "n": aggregate.get("n", (run or {}).get("per_example_count", 0)),
                "accuracy": aggregate.get("accuracy"),
                "usd_per_correct": aggregate.get("usd_per_correct"),
                "latency_ms_mean": aggregate.get("latency_ms_mean"),
                "page_recall": aggregate.get("page_recall_mean"),
                "bbox_iou": aggregate.get("bbox_iou_mean"),
                "evidence_reward": aggregate.get("evidence_reward_mean"),
                "lazy_answer_rate": aggregate.get("lazy_answer_rate"),
                "tool_calls": aggregate.get("tool_calls_mean"),
                "stage_aggregate": stage,
                "run_dir": (run or {}).get("run_dir"),
                "command": row["command"],
            }
        )
    return {
        "hf_repo": PINNED_HF_REPO,
        "hf_split": PINNED_HF_SPLIT,
        "hf_revision": PINNED_HF_REVISION,
        "expected_n": EXPECTED_CANONICAL_N,
        "cells": cells,
    }


def _dataset_manifest(runs: list[dict[str, Any]]) -> dict[str, Any]:
    observed = []
    for run in runs:
        observed.append(
            {
                "agent": run.get("agent"),
                "protocol": run.get("protocol"),
                "tool_set": run.get("tool_set"),
                "hf_repo": run.get("hf_repo"),
                "hf_split": run.get("hf_split"),
                "hf_revision": run.get("hf_revision"),
                "dataset_fingerprint": run.get("dataset_fingerprint"),
                "per_example_count": run.get("per_example_count"),
                "unique_example_ids": run.get("unique_example_ids"),
                "run_dir": run.get("run_dir"),
            }
        )
    return {
        "expected": {
            "hf_repo": PINNED_HF_REPO,
            "hf_split": PINNED_HF_SPLIT,
            "hf_revision": PINNED_HF_REVISION,
            "canonical_n": EXPECTED_CANONICAL_N,
        },
        "observed_runs": observed,
    }


def _write_thesis_note(output_dir: Path, registry_rows: list[dict[str, Any]]) -> None:
    counts: dict[str, int] = {}
    for row in registry_rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    lines = [
        "# Related-Work Experiment Monitor",
        "",
        f"Generated: {datetime.now(UTC).isoformat()}",
        "",
        "## Thesis Target",
        "",
        (
            "FocusParse should be compared against a trusted LlamaIndex ReAct "
            "agent, a coding-agent loop, DocLens-style hierarchical evidence "
            "extraction, AgenticOCR-style on-demand crop/OCR, and a no-tool VLM. "
            "The main claim is architecture plus evidence localization, not just "
            "tool availability."
        ),
        "",
        "## Status Counts",
        "",
    ]
    for status in sorted(counts):
        lines.append(f"- `{status}`: {counts[status]}")
    lines.extend(["", "## Headline Rows", ""])
    for row in registry_rows:
        if row["headline"]:
            lines.append(
                f"- **{row['label']}**: `{row['status']}` "
                f"({row['agent']}, `{row['tool_set']}`, `{row['protocol']}`)"
            )
    lines.extend(
        [
            "",
            "## Gates",
            "",
            f"- Decision-grade rows must use `{PINNED_HF_REVISION}` and `n={EXPECTED_CANONICAL_N}`.",
            "- FocusParse 66.9% remains gated until the raw artifact is reproduced or recovered.",
            "- Results under `results/` are gitignored; tracked files should contain commands, manifests, and analysis.",
            "",
        ]
    )
    (output_dir / "related_work_thesis_note.md").write_text("\n".join(lines))


def _default_result_roots() -> list[Path]:
    roots: list[Path] = []
    for worktree in WORKTREES.values():
        roots.append(worktree / "results" / "hf" / "related-work")
        roots.append(worktree / "results" / "hf")
    return roots


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("results/hf/related-work-monitor"),
        help="Where monitor artifacts should be written.",
    )
    parser.add_argument(
        "--result-root",
        type=Path,
        action="append",
        default=None,
        help="Additional result root to scan. Defaults to all experiment worktree results/hf dirs.",
    )
    parser.add_argument(
        "--render",
        action="store_true",
        help="Also render headline_table.json with scripts/render_headline_table.py.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    specs = _specs()
    result_roots = args.result_root or _default_result_roots()
    runs = _scan_runs(result_roots)
    generated_at = datetime.now(UTC).isoformat()
    registry_rows = _registry_rows(specs, runs)

    registry = {
        "generated_at": generated_at,
        "hf_repo": PINNED_HF_REPO,
        "hf_split": PINNED_HF_SPLIT,
        "hf_revision": PINNED_HF_REVISION,
        "expected_n": EXPECTED_CANONICAL_N,
        "rows": registry_rows,
    }
    (args.output_dir / "run_registry.json").write_text(json.dumps(registry, indent=2, sort_keys=True))
    (args.output_dir / "dataset_manifest.json").write_text(
        json.dumps(_dataset_manifest(runs), indent=2, sort_keys=True)
    )
    (args.output_dir / "protocol_matrix.json").write_text(
        json.dumps(_protocol_matrix(registry_rows), indent=2, sort_keys=True)
    )
    headline_path = args.output_dir / "headline_table.json"
    headline_path.write_text(
        json.dumps(_headline_table(registry_rows, generated_at), indent=2, sort_keys=True)
    )
    _write_thesis_note(args.output_dir, registry_rows)

    if args.render:
        renderer = Path(__file__).resolve().parent / "render_headline_table.py"
        subprocess.run([sys.executable, str(renderer), str(headline_path)], check=False)

    print(f"Wrote related-work monitor artifacts to {args.output_dir}")
    for status in sorted({row["status"] for row in registry_rows}):
        n = sum(1 for row in registry_rows if row["status"] == status)
        print(f"{status}: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
