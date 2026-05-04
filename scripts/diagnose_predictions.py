"""Mine per-example prediction JSONs to surface failure modes.

Reads `predictions/*.json` under one or more spec dirs and reports tool-error
rates by category, lazy-answer rates, premature-final rates (ReAct/baseline),
iteration histograms, and the most common `action_input` shapes per tool.

Used to falsify or confirm hypotheses about a comparator's failure mode (e.g.
the 2026-05-04 finding that ReAct's collapse is lazy answers, not path
hallucination).

Usage:

    uv run python scripts/diagnose_predictions.py \\
        --spec-dir results/hf/headline-v1 \\
        --output results/diagnostics/headline-v1/report.md

Pass `--spec-dir` once per spec dir, OR point at a parent dir whose immediate
children are spec dirs (the headline-eval layout).
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class SpecDiagnosis:
    """One spec's failure-mode breakdown."""

    spec_name: str
    n_examples: int
    n_steps: int = 0
    n_tool_calls: int = 0
    n_tool_errors: int = 0
    error_categories: Counter[str] = field(default_factory=Counter)
    lazy_answer_rate: float = 0.0  # examples with tool_calls == 0
    empty_citation_rate: float = 0.0  # examples with citations == []
    correct_but_no_citations_rate: float = 0.0
    premature_final_rate: float | None = None  # None for non-comparator specs
    iterations_used_hist: Counter[int] = field(default_factory=Counter)
    action_input_top: dict[str, list[tuple[str, int]]] = field(default_factory=dict)
    mean_tool_calls: float = 0.0
    mean_iterations: float = 0.0
    mean_usd: float = 0.0
    accuracy: float = 0.0
    answers_correct: int = 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def diagnose_spec(spec_dir: Path) -> SpecDiagnosis:
    """Diagnose all predictions under `<spec_dir>/predictions/`."""
    pred_dir = spec_dir / "predictions"
    diag = SpecDiagnosis(spec_name=spec_dir.name, n_examples=0)
    if not pred_dir.is_dir():
        return diag

    is_comparator = _is_comparator_spec(spec_dir.name)
    tool_input_samples: dict[str, Counter[str]] = {}
    tool_call_counts: list[int] = []
    iteration_counts: list[int] = []
    usd_values: list[float] = []

    for path in sorted(pred_dir.glob("*.json")):
        try:
            record = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        diag.n_examples += 1
        steps = (record.get("trace") or {}).get("steps") or []
        diag.n_steps += len(steps)

        if record.get("answer_correct", 0.0) >= 1.0:
            diag.answers_correct += 1
        usd_values.append(float(record.get("usd") or 0.0))

        per_example_tool_calls = 0
        per_example_iterations = 0
        first_step_was_final = False

        for i, step in enumerate(steps):
            action = step.get("action") or ""
            tool = step.get("tool")

            if action == "tool_call":
                per_example_tool_calls += 1
                tool_input_samples.setdefault(tool or "?", Counter())[
                    _shape_action_input(step.get("args"))
                ] += 1
            if action == "tool_error":
                diag.n_tool_errors += 1
                err = (step.get("args") or {}).get("error") or "unknown"
                diag.error_categories[str(err)] += 1
            if action != "final_answer" and action != "react_final":
                per_example_iterations += 1
            if i == 0 and step.get("stage") == "react_final":
                first_step_was_final = True

        diag.n_tool_calls += per_example_tool_calls
        tool_call_counts.append(per_example_tool_calls)
        iteration_counts.append(per_example_iterations)
        diag.iterations_used_hist[per_example_iterations] += 1

        # lazy_answer_rate: harness already stamps `is_lazy` on the record
        # using tool_calls == 0 OR no predicted bboxes. Trust that flag.
        if int(record.get("is_lazy", 0)) == 1:
            diag.lazy_answer_rate += 1
        if not record.get("citations"):
            diag.empty_citation_rate += 1
            if record.get("answer_correct", 0.0) >= 1.0:
                diag.correct_but_no_citations_rate += 1
        # premature_final = comparator emitted final_answer at iter 0 with
        # no prior tool call. Tracks the dominant failure mode.
        if is_comparator and first_step_was_final and per_example_tool_calls == 0:
            if diag.premature_final_rate is None:
                diag.premature_final_rate = 0.0
            diag.premature_final_rate += 1

    n = max(diag.n_examples, 1)
    diag.lazy_answer_rate /= n
    diag.empty_citation_rate /= n
    diag.correct_but_no_citations_rate /= n
    if is_comparator:
        if diag.premature_final_rate is not None:
            diag.premature_final_rate /= n
        else:
            diag.premature_final_rate = 0.0
    diag.mean_tool_calls = statistics.mean(tool_call_counts) if tool_call_counts else 0.0
    diag.mean_iterations = statistics.mean(iteration_counts) if iteration_counts else 0.0
    diag.mean_usd = statistics.mean(usd_values) if usd_values else 0.0
    diag.accuracy = diag.answers_correct / n

    diag.action_input_top = {
        tool: counter.most_common(5) for tool, counter in tool_input_samples.items()
    }
    return diag


def render_markdown(diags: list[SpecDiagnosis]) -> str:
    """Render a markdown report comparable to headline_table.md."""
    lines: list[str] = []
    lines.append("# Predictions diagnostics")
    lines.append("")
    lines.append(f"_Specs analyzed: {len(diags)}_")
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append(
        "| Spec | n | accuracy | lazy_rate | empty_cite_rate "
        "| premature_final | tool_err_rate | mean_tool_calls | mean_usd |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for d in diags:
        tool_err_rate = d.n_tool_errors / max(d.n_steps, 1)
        prem = f"{d.premature_final_rate:.1%}" if d.premature_final_rate is not None else "—"
        lines.append(
            f"| {d.spec_name} | {d.n_examples} | {d.accuracy:.1%} "
            f"| {d.lazy_answer_rate:.1%} | {d.empty_citation_rate:.1%} "
            f"| {prem} | {tool_err_rate:.1%} | {d.mean_tool_calls:.2f} "
            f"| ${d.mean_usd:.4f} |"
        )
    lines.append("")

    for d in diags:
        lines.append(f"## {d.spec_name}")
        lines.append("")
        lines.append(f"- examples: **{d.n_examples}**, accuracy: **{d.accuracy:.1%}**")
        lines.append(
            f"- mean tool calls / example: **{d.mean_tool_calls:.2f}**, "
            f"mean iterations: **{d.mean_iterations:.2f}**, "
            f"mean usd: **${d.mean_usd:.4f}**"
        )
        lines.append(f"- lazy_answer_rate (no tool calls): **{d.lazy_answer_rate:.1%}**")
        lines.append(f"- empty_citation_rate (citations == []): **{d.empty_citation_rate:.1%}**")
        lines.append(f"- correct but no citations: **{d.correct_but_no_citations_rate:.1%}**")
        if d.premature_final_rate is not None:
            lines.append(
                f"- premature_final_rate (final at iter 0, no tool call): "
                f"**{d.premature_final_rate:.1%}**"
            )
        if d.error_categories:
            lines.append("- tool_error categories:")
            for cat, count in d.error_categories.most_common():
                lines.append(f"  - `{cat}`: {count}")
        if d.iterations_used_hist:
            lines.append("- iterations histogram:")
            for k in sorted(d.iterations_used_hist.keys()):
                lines.append(f"  - {k}: {d.iterations_used_hist[k]}")
        if d.action_input_top:
            lines.append("- top action_input shapes per tool:")
            for tool, top in d.action_input_top.items():
                lines.append(f"  - **{tool}**:")
                for shape, count in top:
                    lines.append(f"    - `{shape}` × {count}")
        lines.append("")

    return "\n".join(lines)


def to_json(diags: list[SpecDiagnosis]) -> dict[str, Any]:
    return {
        "specs": [
            {
                "spec_name": d.spec_name,
                "n_examples": d.n_examples,
                "n_steps": d.n_steps,
                "n_tool_calls": d.n_tool_calls,
                "n_tool_errors": d.n_tool_errors,
                "error_categories": dict(d.error_categories),
                "lazy_answer_rate": d.lazy_answer_rate,
                "empty_citation_rate": d.empty_citation_rate,
                "correct_but_no_citations_rate": d.correct_but_no_citations_rate,
                "premature_final_rate": d.premature_final_rate,
                "iterations_used_hist": dict(d.iterations_used_hist),
                "action_input_top": d.action_input_top,
                "mean_tool_calls": d.mean_tool_calls,
                "mean_iterations": d.mean_iterations,
                "mean_usd": d.mean_usd,
                "accuracy": d.accuracy,
            }
            for d in diags
        ]
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_comparator_spec(spec_name: str) -> bool:
    return "_react_" in spec_name or "_agent_baseline_" in spec_name


def _shape_action_input(args: dict[str, Any] | None) -> str:
    """Render an action_input shape as a stable string for top-N counting.

    We don't print full values (they're per-example noisy). Instead we record
    the field set and field types: {'doc_path': str, 'page': int, ...}.
    """
    if not args:
        return "{}"
    inner = (args.get("action_input") if isinstance(args, dict) else None) or {}
    if not isinstance(inner, dict) or not inner:
        return "{}"
    parts = []
    for k in sorted(inner.keys()):
        v = inner[k]
        parts.append(f"{k}:{type(v).__name__}")
    return "{" + ", ".join(parts) + "}"


def _resolve_spec_dirs(roots: Iterable[Path]) -> list[Path]:
    """Expand `--spec-dir` arguments. A root that contains `predictions/`
    directly is itself a spec dir; otherwise its immediate children are."""
    resolved: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        if (root / "predictions").is_dir():
            resolved.append(root)
            continue
        for child in sorted(root.iterdir()):
            if child.is_dir() and (child / "predictions").is_dir():
                resolved.append(child)
    return resolved


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--spec-dir",
        action="append",
        type=Path,
        required=True,
        help="A spec dir (with predictions/) OR a parent of spec dirs. Pass multiple.",
    )
    ap.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Markdown report path. JSON sibling is written next to it.",
    )
    args = ap.parse_args()

    spec_dirs = _resolve_spec_dirs(args.spec_dir)
    if not spec_dirs:
        raise SystemExit("No spec dirs found under the supplied --spec-dir args.")

    diags = [diagnose_spec(d) for d in spec_dirs]
    md = render_markdown(diags)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(md)
    json_path = args.output.with_suffix(".json")
    json_path.write_text(json.dumps(to_json(diags), indent=2))
    print(f"wrote {args.output} and {json_path}")


if __name__ == "__main__":
    main()
