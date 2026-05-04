"""Cell-by-cell delta between two headline_table.json files.

Used after every sprint A/B (and at end-of-sprint rollup) to decide
ship/hold/revert per the plan's gate:

  ✅ ship default-on    when delta ≥ +3pp at non-overlapping 95% CIs
  🟡 hold opt-in        when delta is positive but CIs overlap
  ⚠ regression         when delta is negative beyond noise

Usage:

    uv run python scripts/compare_headline_tables.py \\
        results/hf/headline-v1/headline_table.json \\
        results/hf/sprint-2026-05-04/phase1/headline_table.json \\
        --output results/diagnostics/sprint-phase1/delta.md \\
        --label-a "headline-v1" --label-b "phase1-react-inspector"

For a single-spec A/B (one row), point both args at the same
`headline_table.json` and use --filter-method "Our harness +4 tools"
to scope the table.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

# Cells to surface per (method, domain). Order chosen to match the
# headline-v1 markdown rendering. accuracy is primary; bbox_iou and
# usd_per_correct are secondary.
_METRICS = ["accuracy", "bbox_iou", "usd_per_correct"]
_DOMAINS = ["_overall", "datasheet", "finance"]


def _row_index(rows: list[dict]) -> dict[str, dict]:
    """Index a `rows` list by `label` for O(1) lookup."""
    return {row["label"]: row for row in rows}


def _cell(row: dict | None, domain: str, metric: str) -> tuple[float | None, list[float] | None]:
    """Return (value, ci) for a (row, domain, metric) cell, or (None, None) on absence."""
    if row is None:
        return None, None
    bd = row.get("by_domain") or {}
    block = bd.get(domain)
    if not block:
        return None, None
    value = block.get(metric)
    ci = block.get(f"{metric}_ci")
    if value is None:
        return None, None
    return float(value), (list(ci) if ci else None)


def _ci_overlap(ci_a: list[float] | None, ci_b: list[float] | None) -> bool:
    """True iff the two CIs overlap. None CIs are treated as overlapping
    (we can't conclude separation from missing data)."""
    if not ci_a or not ci_b:
        return True
    a_lo, a_hi = ci_a
    b_lo, b_hi = ci_b
    return not (a_hi < b_lo or b_hi < a_lo)


def _gate_marker(
    delta: float | None,
    ci_overlap: bool,
    *,
    metric: str,
    threshold_pp: float = 0.03,
) -> str:
    """Decide the per-cell ship/hold/revert marker.

    For accuracy + bbox_iou: ≥+3pp non-overlapping CIs = ship.
    For usd_per_correct: smaller is better, flip sign on the delta.
    """
    if delta is None:
        return "—"
    direction = -1 if metric == "usd_per_correct" else +1
    signed = delta * direction
    if signed >= threshold_pp and not ci_overlap:
        return "✅ ship"
    if signed >= 0 and not ci_overlap:
        return "🟢 sig+"
    if signed >= 0:
        return "🟡 hold"
    if signed > -threshold_pp:
        return "🟠 noise-"
    return "⚠ regress"


def _format_value(value: float | None, metric: str) -> str:
    if value is None:
        return "—"
    if metric == "usd_per_correct":
        return f"${value:.4f}"
    return f"{100 * value:.1f}%"


def _format_delta(delta: float | None, metric: str) -> str:
    if delta is None:
        return "—"
    if metric == "usd_per_correct":
        sign = "+" if delta >= 0 else ""
        return f"{sign}${delta:.4f}"
    sign = "+" if delta >= 0 else ""
    return f"{sign}{100 * delta:.1f}pp"


def render_markdown(
    table_a: dict,
    table_b: dict,
    *,
    label_a: str,
    label_b: str,
    filter_methods: list[str] | None = None,
) -> str:
    """Render a per-cell delta table as Markdown.

    Args:
        table_a / table_b: parsed headline_table.json dicts.
        label_a / label_b: human-readable identifiers shown in the header.
        filter_methods: only emit rows whose `label` is in this list. When
            None, emit every row in `table_b`.
    """
    rows_a = _row_index(table_a.get("rows") or [])
    rows_b = _row_index(table_b.get("rows") or [])

    target_labels = filter_methods or [r["label"] for r in (table_b.get("rows") or [])]

    lines: list[str] = []
    lines.append(f"# Headline-table cell deltas: {label_a} → {label_b}")
    lines.append("")
    lines.append(
        f"_Comparison written by `scripts/compare_headline_tables.py`. "
        f"`{label_a}` is the baseline; `{label_b}` is the new run._"
    )
    lines.append("")

    legend = (
        "**Gate legend**: ✅ ship (≥+3pp non-overlap CIs) · "
        "🟢 sig+ (positive non-overlap CIs <3pp) · "
        "🟡 hold (positive but overlapping CIs) · "
        "🟠 noise- (slight regression within ±3pp) · "
        "⚠ regress (regression beyond -3pp)."
    )
    lines.append(legend)
    lines.append("")

    for label in target_labels:
        row_a = rows_a.get(label)
        row_b = rows_b.get(label)
        if not row_b:
            continue
        lines.append(f"## {label}")
        lines.append("")
        lines.append(f"| domain | metric | {label_a} | {label_b} | Δ | gate |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for domain in _DOMAINS:
            for metric in _METRICS:
                val_a, ci_a = _cell(row_a, domain, metric)
                val_b, ci_b = _cell(row_b, domain, metric)
                delta = (val_b - val_a) if (val_a is not None and val_b is not None) else None
                overlap = _ci_overlap(ci_a, ci_b)
                gate = _gate_marker(delta, overlap, metric=metric)
                lines.append(
                    f"| {domain} | {metric} | "
                    f"{_format_value(val_a, metric)} | "
                    f"{_format_value(val_b, metric)} | "
                    f"{_format_delta(delta, metric)} | {gate} |"
                )
        lines.append("")

    return "\n".join(lines)


def to_json(
    table_a: dict,
    table_b: dict,
    *,
    label_a: str,
    label_b: str,
    filter_methods: list[str] | None = None,
) -> dict[str, Any]:
    """Same shape as render_markdown, but as structured JSON for tooling."""
    rows_a = _row_index(table_a.get("rows") or [])
    rows_b = _row_index(table_b.get("rows") or [])
    target_labels = filter_methods or [r["label"] for r in (table_b.get("rows") or [])]

    out: dict[str, Any] = {
        "label_a": label_a,
        "label_b": label_b,
        "rows": [],
    }
    for label in target_labels:
        row_a = rows_a.get(label)
        row_b = rows_b.get(label)
        if not row_b:
            continue
        cells: list[dict[str, Any]] = []
        for domain in _DOMAINS:
            for metric in _METRICS:
                val_a, ci_a = _cell(row_a, domain, metric)
                val_b, ci_b = _cell(row_b, domain, metric)
                delta = (val_b - val_a) if (val_a is not None and val_b is not None) else None
                overlap = _ci_overlap(ci_a, ci_b)
                gate = _gate_marker(delta, overlap, metric=metric)
                cells.append(
                    {
                        "domain": domain,
                        "metric": metric,
                        "value_a": val_a,
                        "value_b": val_b,
                        "ci_a": ci_a,
                        "ci_b": ci_b,
                        "delta": delta,
                        "ci_overlap": overlap,
                        "gate": gate,
                    }
                )
        out["rows"].append({"label": label, "cells": cells})
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("baseline", type=Path, help="headline_table.json A (baseline)")
    ap.add_argument("new_run", type=Path, help="headline_table.json B (new run)")
    ap.add_argument("--label-a", default="baseline")
    ap.add_argument("--label-b", default="new_run")
    ap.add_argument("--output", type=Path, required=True, help="Markdown output path")
    ap.add_argument(
        "--filter-method",
        action="append",
        default=None,
        help="Only emit rows for this method label (repeatable). "
        "Example: --filter-method 'Our harness +4 tools'",
    )
    args = ap.parse_args()

    table_a = json.loads(args.baseline.read_text())
    table_b = json.loads(args.new_run.read_text())

    md = render_markdown(
        table_a,
        table_b,
        label_a=args.label_a,
        label_b=args.label_b,
        filter_methods=args.filter_method,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(md)

    json_path = args.output.with_suffix(".json")
    json_payload = to_json(
        table_a,
        table_b,
        label_a=args.label_a,
        label_b=args.label_b,
        filter_methods=args.filter_method,
    )
    json_path.write_text(json.dumps(json_payload, indent=2))
    print(f"wrote {args.output} and {json_path}")


if __name__ == "__main__":
    main()
