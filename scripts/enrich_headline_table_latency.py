"""Add latency means to an existing headline table from cached run artifacts.

This is for post-hoc rollups assembled from older `headline_table.json`
files before latency became a first-class aggregate metric. It does not
run models. It reads the per-method run directories referenced by the
table, computes mean `latency_ms` by domain from `run.json` or
`per_example.jsonl`, and writes an enriched headline table.

Usage:
    uv run python scripts/enrich_headline_table_latency.py \\
        results/hf/sprint-2026-05-08/final-main-rollup/headline_table_with_current_focus_means.json \\
        --output results/hf/sprint-2026-05-08/final-main-rollup/headline_table_with_current_focus_means_latency.json
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from statistics import mean
from typing import Any

_DOMAINS = ("_overall", "datasheet", "finance")
_DOMAIN_ALIASES = {
    "Domain.DATASHEET": "datasheet",
    "DATASHEET": "datasheet",
    "datasheet": "datasheet",
    "Domain.FINANCE": "finance",
    "FINANCE": "finance",
    "finance": "finance",
}


def enrich_table(
    table: dict[str, Any],
    *,
    table_path: Path,
    repo_root: Path,
) -> dict[str, Any]:
    """Return a copy of `table` with `latency_ms_mean` filled when possible."""
    out = deepcopy(table)
    out.setdefault("latency_sources", {})
    for row in out.get("rows", []):
        if row.get("missing"):
            continue
        roots = _candidate_roots(out, row, table_path=table_path, repo_root=repo_root)
        run_dirs = _matching_run_dirs(
            roots, row=row, protocol=out.get("protocol", "agentic_multi_page")
        )
        if not run_dirs:
            continue
        latencies = [_latency_by_domain(run_dir) for run_dir in run_dirs]
        merged = _mean_latency_by_domain(latencies)
        for domain, value in merged.items():
            metrics = row.setdefault("by_domain", {}).setdefault(domain, {})
            metrics["latency_ms_mean"] = value
            if len(latencies) > 1:
                metrics["latency_ms_runs"] = [
                    latency[domain] for latency in latencies if latency.get(domain) is not None
                ]
        out["latency_sources"][row["label"]] = [str(path) for path in run_dirs]
    return out


def _candidate_roots(
    table: dict[str, Any],
    row: dict[str, Any],
    *,
    table_path: Path,
    repo_root: Path,
) -> list[Path]:
    label = row.get("label", "")
    if label == "Our harness +2 tools":
        return _replicate_roots(table.get("current_focus_plus2_summary"), table_path, repo_root)
    if label == "Our harness +4 tools":
        return _replicate_roots(table.get("current_focus_plus4_summary"), table_path, repo_root)
    if row.get("source") == "rebaseline-v2" and table.get("baseline"):
        return [_resolve_path(table["baseline"], table_path, repo_root).parent]
    return [table_path.parent]


def _replicate_roots(value: str | None, table_path: Path, repo_root: Path) -> list[Path]:
    if not value:
        return []
    summary = _resolve_path(value, table_path, repo_root)
    name = summary.name
    suffix = "-replicate-summary.json"
    if not name.endswith(suffix):
        return []
    prefix = name[: -len(suffix)]
    return sorted(path for path in summary.parent.glob(f"{prefix}-run*") if path.is_dir())


def _resolve_path(value: str, table_path: Path, repo_root: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    candidates = [repo_root / path, table_path.parent / path, Path.cwd() / path]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _matching_run_dirs(roots: list[Path], *, row: dict[str, Any], protocol: str) -> list[Path]:
    out: list[Path] = []
    agent = row.get("agent")
    tool_set = row.get("tool_set")
    if not agent or not tool_set:
        return out
    suffix = "" if tool_set == "full" else f"_t{tool_set}"
    prefix = f"focusparse_{agent}_{protocol}_"
    for root in roots:
        for candidate in sorted(root.glob(f"{prefix}*{suffix}")):
            if not candidate.is_dir():
                continue
            if tool_set == "full" and "_t" in candidate.name:
                continue
            if tool_set != "full" and not candidate.name.endswith(suffix):
                continue
            if (candidate / "run.json").exists() or (candidate / "per_example.jsonl").exists():
                out.append(candidate)
                break
    return out


def _latency_by_domain(run_dir: Path) -> dict[str, float]:
    run_path = run_dir / "run.json"
    if run_path.exists():
        run = json.loads(run_path.read_text())
        by_domain = run.get("aggregate_by_domain") or {}
        if all(
            (by_domain.get(domain) or {}).get("latency_ms_mean") is not None for domain in _DOMAINS
        ):
            return {
                domain: float((by_domain.get(domain) or {})["latency_ms_mean"])
                for domain in _DOMAINS
            }
    return _latency_from_per_example(run_dir / "per_example.jsonl")


def _latency_from_per_example(path: Path) -> dict[str, float]:
    values: dict[str, list[float]] = defaultdict(list)
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        latency = row.get("latency_ms")
        if latency is None:
            continue
        domain = _DOMAIN_ALIASES.get(str(row.get("domain")))
        values["_overall"].append(float(latency))
        if domain:
            values[domain].append(float(latency))
    return {domain: mean(values[domain]) for domain in _DOMAINS if values.get(domain)}


def _mean_latency_by_domain(latencies: list[dict[str, float]]) -> dict[str, float]:
    merged: dict[str, float] = {}
    for domain in _DOMAINS:
        values = [latency[domain] for latency in latencies if latency.get(domain) is not None]
        if values:
            merged[domain] = mean(values)
    return merged


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("headline_table", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Resolve relative artifact paths against this repo root.",
    )
    args = parser.parse_args()

    table_path = args.headline_table.resolve()
    table = json.loads(table_path.read_text())
    enriched = enrich_table(table, table_path=table_path, repo_root=args.repo_root.resolve())
    output = args.output or table_path.with_name(f"{table_path.stem}_latency.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(enriched, indent=2))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
