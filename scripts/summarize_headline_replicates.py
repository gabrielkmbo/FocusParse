"""Summarize replicated headline-table A/B runs.

Path A exposed a real evaluation wrinkle: a single n=148 focus +4 run can
move by several points from upstream model variance alone. This script keeps
the comparison reproducible by averaging replicated `headline_table.json`
files before applying the normal ship/hold/regress gate.

Usage:
    uv run python scripts/summarize_headline_replicates.py \\
        results/hf/headline-v1-rebaseline-v2/headline_table.json \\
        results/hf/sprint-2026-05-06/path-a-run1/headline_table.json \\
        results/hf/sprint-2026-05-06/path-a-run2/headline_table.json \\
        --label-a rebaseline-v2 \\
        --label-b path-a-mean \\
        --filter-method "Our harness +4 tools" \\
        --output results/hf/sprint-2026-05-06/path-a-replicate-summary.md
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from typing import Any

import compare_headline_tables as cht

_METRICS = ["accuracy", "bbox_iou", "usd_per_correct"]
_DOMAINS = ["_overall", "datasheet", "finance"]


def _row_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {row["label"]: row for row in rows}


def _union_ci(cis: list[list[float] | None]) -> list[float] | None:
    """Return a conservative CI spanning every replicate CI.

    Missing CIs mean the new-run uncertainty is unknown, so return None and
    let compare_headline_tables treat the cell as overlapping.
    """
    if not cis or any(ci is None for ci in cis):
        return None
    lows = [ci[0] for ci in cis if ci is not None]
    highs = [ci[1] for ci in cis if ci is not None]
    return [min(lows), max(highs)]


def summarize(
    baseline: dict[str, Any],
    replicates: list[dict[str, Any]],
    *,
    label_a: str,
    label_b: str,
    filter_methods: list[str] | None = None,
) -> dict[str, Any]:
    """Create a structured replicated comparison payload."""
    rows_a = _row_index(baseline.get("rows") or [])
    replicate_rows = [_row_index(table.get("rows") or []) for table in replicates]
    if filter_methods is not None:
        target_labels = filter_methods
    else:
        target_labels = sorted({label for rows in replicate_rows for label in rows})

    out: dict[str, Any] = {
        "label_a": label_a,
        "label_b": label_b,
        "n_replicates": len(replicates),
        "rows": [],
    }
    for label in target_labels:
        row_a = rows_a.get(label)
        cells: list[dict[str, Any]] = []
        for domain in _DOMAINS:
            for metric in _METRICS:
                value_a, ci_a = cht._cell(row_a, domain, metric)
                replicate_values: list[float] = []
                replicate_cis: list[list[float] | None] = []
                for rows_b in replicate_rows:
                    value_b, ci_b = cht._cell(rows_b.get(label), domain, metric)
                    if value_b is not None:
                        replicate_values.append(value_b)
                    replicate_cis.append(ci_b)

                mean_b = mean(replicate_values) if replicate_values else None
                ci_b_union = _union_ci(replicate_cis)
                delta = mean_b - value_a if mean_b is not None and value_a is not None else None
                ci_overlap = cht._ci_overlap(ci_a, ci_b_union)
                cells.append(
                    {
                        "domain": domain,
                        "metric": metric,
                        "value_a": value_a,
                        "ci_a": ci_a,
                        "replicate_values": replicate_values,
                        "mean_b": mean_b,
                        "ci_b_union": ci_b_union,
                        "delta": delta,
                        "ci_overlap": ci_overlap,
                        "gate": cht._gate_marker(delta, ci_overlap, metric=metric),
                    }
                )
        out["rows"].append({"label": label, "cells": cells})
    return out


def _format_replicates(values: list[float], metric: str) -> str:
    if not values:
        return "-"
    return ", ".join(cht._format_value(v, metric) for v in values)


def render_markdown(summary: dict[str, Any]) -> str:
    lines: list[str] = []
    label_a = summary["label_a"]
    label_b = summary["label_b"]
    n_replicates = summary["n_replicates"]
    lines.append(f"# Replicated headline-table deltas: {label_a} -> {label_b}")
    lines.append("")
    lines.append(
        f"`{label_b}` is the mean of {n_replicates} replicate run(s). "
        "The new-run CI is the conservative union of replicate CIs."
    )
    lines.append("")
    lines.append(
        "**Gate legend**: ship requires the normal positive threshold plus "
        "non-overlap against the conservative replicate-CI union."
    )
    lines.append("")

    for row in summary.get("rows", []):
        lines.append(f"## {row['label']}")
        lines.append("")
        lines.append(
            f"| domain | metric | {label_a} | {label_b} runs | {label_b} mean | delta | gate |"
        )
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for cell in row["cells"]:
            metric = cell["metric"]
            lines.append(
                f"| {cell['domain']} | {metric} | "
                f"{cht._format_value(cell['value_a'], metric)} | "
                f"{_format_replicates(cell['replicate_values'], metric)} | "
                f"{cht._format_value(cell['mean_b'], metric)} | "
                f"{cht._format_delta(cell['delta'], metric)} | "
                f"{cell['gate']} |"
            )
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path, help="Baseline headline_table.json")
    parser.add_argument(
        "replicates",
        type=Path,
        nargs="+",
        help="Replicate headline_table.json files to average",
    )
    parser.add_argument("--label-a", default="baseline")
    parser.add_argument("--label-b", default="replicate_mean")
    parser.add_argument("--output", type=Path, required=True, help="Markdown output path")
    parser.add_argument(
        "--json-output",
        type=Path,
        default=None,
        help="Optional structured JSON output path",
    )
    parser.add_argument(
        "--filter-method",
        action="append",
        default=None,
        help="Only emit rows for this method label. Repeatable.",
    )
    args = parser.parse_args()

    baseline = json.loads(args.baseline.read_text())
    replicates = [json.loads(path.read_text()) for path in args.replicates]
    summary = summarize(
        baseline,
        replicates,
        label_a=args.label_a,
        label_b=args.label_b,
        filter_methods=args.filter_method,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_markdown(summary))
    if args.json_output is not None:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
