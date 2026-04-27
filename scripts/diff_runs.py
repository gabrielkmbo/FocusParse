"""diff_runs — print stage-by-stage deltas between two FocusParse runs.

Usage:
    uv run python scripts/diff_runs.py results/hf/<baseline>.json results/hf/<new>.json
    uv run python scripts/diff_runs.py results/hf/<baseline>/run.json results/hf/<new>/run.json

The "gate" tool from `plans/2026-04-27-phase2-sota-leverage.md`. Items
3-5 (verifier loop, region reranker, evidence graph) ship only if their
diff against a stable baseline shows a positive delta on the metric
they were supposed to improve. A negative or zero delta means revert
and rethink — don't stack more complexity.

Reads either:
  * a parser-bench-shaped wrapper (e.g. `focusparse_focus_focus_default
    _<sha>.json`) with a top-level `stage_aggregate` field, or
  * a raw `run.json` with a top-level `stage_aggregate` field.

If only `aggregate` is present (legacy runs from before the metrics
landed), the diff falls back to comparing the legacy fields and notes
the missing stage block.

Lower-is-better metrics (lazy_full_page_rate, duplicate_crop_rate,
abstention_rate when not gold-unanswerable, tokens, latency, usd)
are flagged in the "Direction" column so reviewers can read deltas
correctly.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Metrics where lower is better. Sign-flipped on the "expected better?"
# column so a positive delta isn't visually celebrated when it's actually
# a regression. Add to this set as new metrics arrive.
_LOWER_IS_BETTER: frozenset[str] = frozenset(
    {
        "localization.lazy_full_page_rate",
        "localization.duplicate_crop_rate",
        # efficiency_by_stage::* — handled separately; tokens / usd /
        # latency are tradeoffs, not strict regressions, so they're
        # flagged "tradeoff" rather than "lower is better".
    }
)

# Metrics that are tradeoffs (not strictly better-or-worse) — print
# delta but no judgment marker.
_TRADEOFF_METRICS: frozenset[str] = frozenset(
    {
        "loop.retries_mean",  # 0 retries is the baseline; some retries can be helpful
        "routing.pages_inspected_mean",  # more pages = more recall but more cost
    }
)


def main() -> int:
    args = _parse_args()
    a = _load_stage_aggregate(args.baseline)
    b = _load_stage_aggregate(args.new)

    # Header lines on stderr when format=json so stdout is clean JSON
    # pipeable into CI gates / jq.
    header_stream = sys.stderr if args.format == "json" else sys.stdout
    print(f"Baseline: {args.baseline}", file=header_stream)
    print(f"New:      {args.new}", file=header_stream)
    print(file=header_stream)

    if a is None or b is None:
        print(
            "warning: at least one run is missing `stage_aggregate`. "
            "Diff falls back to top-level `aggregate` only.",
            file=sys.stderr,
        )
        _print_legacy_aggregate_diff(args.baseline, args.new)
        return 0

    rows = _build_rows(a, b)
    _print_table(rows, format=args.format)
    return 0


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("baseline", type=Path, help="Path to baseline run.json or wrapper")
    p.add_argument("new", type=Path, help="Path to new run.json or wrapper")
    p.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format. `json` is for piping into a CI gate.",
    )
    return p.parse_args()


def _load_stage_aggregate(path: Path) -> dict | None:
    """Find a `stage_aggregate` block in either a wrapped EvalRunResults
    or a raw run.json. Returns None when absent (legacy run)."""
    payload = json.loads(path.read_text())

    # If `path` is a directory containing run.json, recurse.
    if isinstance(payload, dict) and "run.json" in payload:
        return _load_stage_aggregate(path.parent / "run.json")

    # Direct run.json.
    sa = payload.get("stage_aggregate") if isinstance(payload, dict) else None
    if isinstance(sa, dict):
        return sa

    # EvalRunResults wrapper has nested per-protocol aggregates; the harness
    # writes stage_aggregate at the top level, but defensive lookup helps
    # when callers point at a wrapper that re-shapes things.
    for key in ("manifest", "results", "by_protocol"):
        nested = payload.get(key) if isinstance(payload, dict) else None
        if isinstance(nested, dict):
            sa = nested.get("stage_aggregate")
            if isinstance(sa, dict):
                return sa

    return None


# ---------------------------------------------------------------------------
# Diff computation
# ---------------------------------------------------------------------------


def _build_rows(a: dict, b: dict) -> list[dict[str, Any]]:
    """Flatten both aggregates into rows of (metric_path, baseline, new, delta).

    Skips fields that are None on both sides; the caller still sees that
    they exist so a future "always-None" metric flags as a wiring bug.
    """
    rows: list[dict[str, Any]] = []
    paths = sorted(_metric_paths(a) | _metric_paths(b))
    for path in paths:
        va = _get_path(a, path)
        vb = _get_path(b, path)
        if va is None and vb is None:
            continue
        rows.append(
            {
                "metric": path,
                "baseline": va,
                "new": vb,
                "delta": _delta(va, vb),
                "direction": _direction_label(path),
            }
        )
    # Stick a divider row on stage_aggregate.n so n-of-examples is the first row.
    rows.sort(key=lambda r: (_section(r["metric"]), r["metric"]))
    return rows


def _metric_paths(d: dict, *, prefix: str = "") -> set[str]:
    """Recursively flatten a nested dict into dotted paths.

    Stops at numeric leaves, bool leaves, None leaves, and string leaves.
    `efficiency_by_stage` is two levels deep ({stage_name: {tokens: int, ...}}).
    """
    paths: set[str] = set()
    for k, v in d.items():
        path = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            paths |= _metric_paths(v, prefix=path)
        else:
            paths.add(path)
    return paths


def _get_path(d: dict, path: str) -> Any:
    cur: Any = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _delta(a: Any, b: Any) -> Any:
    """Return b - a when both numeric, else None."""
    try:
        return float(b) - float(a)
    except (TypeError, ValueError):
        return None


def _section(metric_path: str) -> tuple[int, str]:
    """Sort key: group rows by stage block in a fixed order."""
    order = {
        "n": 0,
        "routing": 1,
        "localization": 2,
        "evidence": 3,
        "reasoning": 4,
        "loop": 5,
        "loop_terminated_distribution": 6,
        "efficiency_by_stage": 7,
    }
    head = metric_path.split(".", 1)[0]
    return (order.get(head, 9), metric_path)


def _direction_label(metric_path: str) -> str:
    if metric_path in _LOWER_IS_BETTER:
        return "lower-is-better"
    if metric_path in _TRADEOFF_METRICS:
        return "tradeoff"
    if metric_path.startswith("efficiency_by_stage."):
        return "tradeoff"
    return ""


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def _print_table(rows: list[dict[str, Any]], *, format: str) -> None:
    if format == "json":
        print(json.dumps(rows, default=str, indent=2))
        return

    # Plain ASCII table. Adapts column widths to the content.
    metric_w = max(8, max((len(r["metric"]) for r in rows), default=8))
    direction_w = max(9, max((len(r["direction"]) for r in rows), default=9))

    print(
        f"{'Metric':<{metric_w}}  {'Baseline':>10}  {'New':>10}  "
        f"{'Δ':>10}  {'Direction':<{direction_w}}"
    )
    print("-" * (metric_w + 10 + 10 + 10 + direction_w + 8))

    last_section = -1
    for r in rows:
        section_id = _section(r["metric"])[0]
        if section_id != last_section:
            if last_section != -1:
                print()  # blank line between sections
            last_section = section_id
        baseline = _fmt_value(r["baseline"])
        new = _fmt_value(r["new"])
        delta = _fmt_delta(r["delta"], r["direction"])
        print(
            f"{r['metric']:<{metric_w}}  {baseline:>10}  {new:>10}  "
            f"{delta:>10}  {r['direction']:<{direction_w}}"
        )


def _fmt_value(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v) if abs(v) < 10000 else f"{v:.2e}"
    if isinstance(v, float):
        if abs(v) < 0.0001 and v != 0:
            return f"{v:.2e}"
        return f"{v:.4f}"
    return str(v)[:10]


def _fmt_delta(delta: Any, direction: str) -> str:
    if delta is None or not isinstance(delta, (int, float)):
        return "—"
    if delta == 0:
        return "0"
    sign = "+" if delta > 0 else ""
    base = f"{sign}{delta:.4f}" if abs(delta) >= 0.0001 else f"{sign}{delta:.2e}"
    # Visual hint: red-ish prefix for "wrong direction" deltas. Pure ASCII,
    # so this works in any terminal / log file.
    if direction == "lower-is-better" and delta > 0:
        return f"{base} ↑bad"
    if direction == "lower-is-better" and delta < 0:
        return f"{base} ↓good"
    if direction == "" and delta > 0:
        return f"{base} ↑good"
    if direction == "" and delta < 0:
        return f"{base} ↓bad"
    return base


# ---------------------------------------------------------------------------
# Legacy fallback
# ---------------------------------------------------------------------------


def _print_legacy_aggregate_diff(baseline: Path, new: Path) -> None:
    """Compare just the top-level `aggregate` blocks when stage_aggregate is
    missing. Useful for diffing a pre-item-2 baseline against a post-item-2
    run before re-scoring the baseline."""
    a = json.loads(baseline.read_text()).get("aggregate", {})
    b = json.loads(new.read_text()).get("aggregate", {})
    keys = sorted(set(a.keys()) | set(b.keys()))
    print(f"{'Metric':<28}  {'Baseline':>10}  {'New':>10}  {'Δ':>10}")
    print("-" * 64)
    for k in keys:
        va = a.get(k)
        vb = b.get(k)
        delta = _delta(va, vb)
        print(f"{k:<28}  {_fmt_value(va):>10}  {_fmt_value(vb):>10}  {_fmt_delta(delta, ''):>10}")


if __name__ == "__main__":
    sys.exit(main())
