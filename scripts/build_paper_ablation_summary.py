"""Build paired ablation summaries for paper result comparisons."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_RESULT_ROOT = Path("results/hf/paper/2026-05-24-paper-headline-v1/headline")
DEFAULT_BASELINE = DEFAULT_RESULT_ROOT / "focusparse_focus_agentic_multi_page_0b139a04_tminimal"
DEFAULT_TREATMENT = DEFAULT_RESULT_ROOT / "focusparse_focus_agentic_multi_page_0b139a04"
DEFAULT_OUTPUT_DIR = Path("results/paper/ablation-summary")
DEFAULT_OUTPUT_STEM = "focusparse-toolset-ablation"
DEFAULT_TITLE = "FocusParse Tool-Set Ablation"
DEFAULT_INTERPRETATION_NOTE = (
    "This is a coarse tool-set ablation: the +4 condition adds "
    "`expand_context` and `run_python`, so it supports the evidence-packet "
    "thesis but does not by itself isolate expansion from computation."
)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def build_pair_keyed_records(rows: list[dict[str, Any]]) -> dict[tuple[str, int], dict[str, Any]]:
    """Key rows by example id and occurrence so duplicate IDs are preserved."""
    seen: Counter[str] = Counter()
    keyed: dict[tuple[str, int], dict[str, Any]] = {}
    for row in rows:
        example_id = str(row.get("example_id") or "")
        seen[example_id] += 1
        keyed[(example_id, seen[example_id])] = row
    return keyed


def summarize_pair(
    baseline_rows: list[dict[str, Any]],
    treatment_rows: list[dict[str, Any]],
    *,
    baseline_label: str,
    treatment_label: str,
) -> dict[str, Any]:
    baseline_by_key = build_pair_keyed_records(baseline_rows)
    treatment_by_key = build_pair_keyed_records(treatment_rows)
    paired_keys = sorted(set(baseline_by_key) & set(treatment_by_key))
    paired = [
        _paired_record(key, baseline_by_key[key], treatment_by_key[key]) for key in paired_keys
    ]

    summary = _summarize_records(paired)
    summary.update(
        {
            "baseline_label": baseline_label,
            "treatment_label": treatment_label,
            "baseline_rows": len(baseline_rows),
            "treatment_rows": len(treatment_rows),
            "paired_n": len(paired),
            "baseline_only": len(set(baseline_by_key) - set(treatment_by_key)),
            "treatment_only": len(set(treatment_by_key) - set(baseline_by_key)),
            "by_domain": {
                domain: _summarize_records([r for r in paired if r["domain"] == domain])
                for domain in sorted({r["domain"] for r in paired})
            },
            "paired_records": paired,
        }
    )
    return summary


def write_outputs(
    summary: dict[str, Any],
    output_dir: Path,
    *,
    output_stem: str = DEFAULT_OUTPUT_STEM,
    title: str = DEFAULT_TITLE,
    interpretation_note: str = DEFAULT_INTERPRETATION_NOTE,
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{output_stem}.json"
    csv_path = output_dir / f"{output_stem}-flips.csv"
    md_path = output_dir / f"{output_stem}.md"

    serializable = {k: v for k, v in summary.items() if k != "paired_records"}
    serializable["paired_records"] = summary["paired_records"]
    json_path.write_text(json.dumps(serializable, indent=2) + "\n", encoding="utf-8")

    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "example_id",
                "occurrence",
                "domain",
                "flip",
                "baseline_correct",
                "treatment_correct",
                "baseline_answer",
                "treatment_answer",
                "gold_answer",
                "baseline_bbox_iou",
                "treatment_bbox_iou",
                "baseline_page_recall",
                "treatment_page_recall",
                "baseline_usd",
                "treatment_usd",
                "baseline_lazy",
                "treatment_lazy",
            ],
        )
        writer.writeheader()
        writer.writerows(summary["paired_records"])

    md_path.write_text(
        _render_markdown(summary, title=title, interpretation_note=interpretation_note),
        encoding="utf-8",
    )
    return {
        "json": json_path.as_posix(),
        "csv": csv_path.as_posix(),
        "markdown": md_path.as_posix(),
    }


def _paired_record(
    key: tuple[str, int],
    baseline: dict[str, Any],
    treatment: dict[str, Any],
) -> dict[str, Any]:
    baseline_correct = _is_correct(baseline)
    treatment_correct = _is_correct(treatment)
    return {
        "example_id": key[0],
        "occurrence": key[1],
        "domain": _normalize_domain(treatment.get("domain") or baseline.get("domain")),
        "flip": _flip_label(baseline_correct, treatment_correct),
        "baseline_correct": int(baseline_correct),
        "treatment_correct": int(treatment_correct),
        "baseline_answer": baseline.get("answer_pred"),
        "treatment_answer": treatment.get("answer_pred"),
        "gold_answer": treatment.get("answer_gold") or baseline.get("answer_gold"),
        "baseline_bbox_iou": _float_or_none(baseline.get("bbox_iou")),
        "treatment_bbox_iou": _float_or_none(treatment.get("bbox_iou")),
        "baseline_page_recall": _float_or_none(baseline.get("page_recall")),
        "treatment_page_recall": _float_or_none(treatment.get("page_recall")),
        "baseline_usd": _float_or_none(baseline.get("usd")),
        "treatment_usd": _float_or_none(treatment.get("usd")),
        "baseline_lazy": int(bool(baseline.get("is_lazy"))),
        "treatment_lazy": int(bool(treatment.get("is_lazy"))),
    }


def _summarize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(records)
    baseline_correct = sum(r["baseline_correct"] for r in records)
    treatment_correct = sum(r["treatment_correct"] for r in records)
    return {
        "paired_n": n,
        "baseline_correct": baseline_correct,
        "treatment_correct": treatment_correct,
        "baseline_accuracy": _ratio(baseline_correct, n),
        "treatment_accuracy": _ratio(treatment_correct, n),
        "accuracy_delta_pp": (_ratio(treatment_correct, n) - _ratio(baseline_correct, n)) * 100.0,
        "recoveries": sum(1 for r in records if r["flip"] == "recovery"),
        "regressions": sum(1 for r in records if r["flip"] == "regression"),
        "unchanged_correct": sum(1 for r in records if r["flip"] == "unchanged_correct"),
        "unchanged_wrong": sum(1 for r in records if r["flip"] == "unchanged_wrong"),
        "net_correct_delta": treatment_correct - baseline_correct,
        "baseline_bbox_iou_mean": _mean(r["baseline_bbox_iou"] for r in records),
        "treatment_bbox_iou_mean": _mean(r["treatment_bbox_iou"] for r in records),
        "baseline_page_recall_mean": _mean(r["baseline_page_recall"] for r in records),
        "treatment_page_recall_mean": _mean(r["treatment_page_recall"] for r in records),
        "baseline_lazy_rate": _mean(r["baseline_lazy"] for r in records),
        "treatment_lazy_rate": _mean(r["treatment_lazy"] for r in records),
        "baseline_usd_per_correct": _usd_per_correct(records, "baseline"),
        "treatment_usd_per_correct": _usd_per_correct(records, "treatment"),
    }


def _render_markdown(
    summary: dict[str, Any],
    *,
    title: str,
    interpretation_note: str,
) -> str:
    lines = [
        f"# {title}",
        "",
        f"Generated: {summary['generated_at_utc']}",
        "",
        (f"Comparison: `{summary['baseline_label']}` -> `{summary['treatment_label']}`."),
        "",
        "## Overall",
        "",
        _summary_table([("_overall", summary)]),
        "",
        "## By Domain",
        "",
        _summary_table(sorted(summary["by_domain"].items())),
        "",
        "## Interpretation",
        "",
        (
            f"The treatment changes {summary['net_correct_delta']:+d} correct rows "
            f"over {summary['paired_n']} paired rows, with "
            f"{summary['recoveries']} recoveries and {summary['regressions']} regressions."
        ),
        interpretation_note,
        "",
        "## Flip Examples",
        "",
    ]
    lines.extend(_flip_examples(summary["paired_records"], "recovery"))
    lines.extend(_flip_examples(summary["paired_records"], "regression"))
    return "\n".join(lines) + "\n"


def _summary_table(rows: list[tuple[str, dict[str, Any]]]) -> str:
    out = [
        "| Slice | n | Baseline acc | Treatment acc | Delta pp | Recoveries | Regressions | Baseline IoU | Treatment IoU |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for label, metrics in rows:
        out.append(
            "| "
            + " | ".join(
                [
                    label,
                    str(metrics["paired_n"]),
                    _pct(metrics["baseline_accuracy"]),
                    _pct(metrics["treatment_accuracy"]),
                    f"{metrics['accuracy_delta_pp']:+.1f}",
                    str(metrics["recoveries"]),
                    str(metrics["regressions"]),
                    _fmt_float(metrics["baseline_bbox_iou_mean"]),
                    _fmt_float(metrics["treatment_bbox_iou_mean"]),
                ]
            )
            + " |"
        )
    return "\n".join(out)


def _flip_examples(records: list[dict[str, Any]], flip: str, limit: int = 8) -> list[str]:
    selected = [r for r in records if r["flip"] == flip][:limit]
    title = "Recoveries" if flip == "recovery" else "Regressions"
    lines = [f"### {title}", ""]
    if not selected:
        lines.append("None.")
        lines.append("")
        return lines
    lines.extend(
        [
            "| Example | Domain | Baseline answer | Treatment answer | Gold |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for row in selected:
        lines.append(
            "| "
            + " | ".join(
                [
                    _escape_md(row["example_id"]),
                    row["domain"],
                    _escape_md(str(row.get("baseline_answer"))),
                    _escape_md(str(row.get("treatment_answer"))),
                    _escape_md(str(row.get("gold_answer"))),
                ]
            )
            + " |"
        )
    lines.append("")
    return lines


def _is_correct(row: dict[str, Any]) -> bool:
    try:
        return float(row.get("answer_correct") or 0.0) >= 0.5
    except (TypeError, ValueError):
        return False


def _flip_label(baseline_correct: bool, treatment_correct: bool) -> str:
    if baseline_correct and treatment_correct:
        return "unchanged_correct"
    if not baseline_correct and not treatment_correct:
        return "unchanged_wrong"
    if not baseline_correct and treatment_correct:
        return "recovery"
    return "regression"


def _normalize_domain(raw: Any) -> str:
    text = str(raw or "").lower()
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text or "unknown"


def _float_or_none(raw: Any) -> float | None:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _mean(values: Any) -> float | None:
    nums = [float(v) for v in values if v is not None]
    return sum(nums) / len(nums) if nums else None


def _usd_per_correct(records: list[dict[str, Any]], prefix: str) -> float | None:
    correct = sum(r[f"{prefix}_correct"] for r in records)
    if correct <= 0:
        return None
    usd = sum(float(r.get(f"{prefix}_usd") or 0.0) for r in records)
    return usd / correct


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _fmt_float(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def _escape_md(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-dir", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--treatment-dir", type=Path, default=DEFAULT_TREATMENT)
    parser.add_argument("--baseline-label", default="FocusParse +2 tools")
    parser.add_argument("--treatment-label", default="FocusParse +4 tools")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--output-stem", default=DEFAULT_OUTPUT_STEM)
    parser.add_argument("--title", default=DEFAULT_TITLE)
    parser.add_argument("--interpretation-note", default=DEFAULT_INTERPRETATION_NOTE)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    baseline_rows = read_jsonl(args.baseline_dir / "per_example.jsonl")
    treatment_rows = read_jsonl(args.treatment_dir / "per_example.jsonl")
    summary = summarize_pair(
        baseline_rows,
        treatment_rows,
        baseline_label=args.baseline_label,
        treatment_label=args.treatment_label,
    )
    summary["generated_at_utc"] = datetime.now(UTC).isoformat()
    summary["baseline_dir"] = args.baseline_dir.as_posix()
    summary["treatment_dir"] = args.treatment_dir.as_posix()
    paths = write_outputs(
        summary,
        args.output_dir,
        output_stem=args.output_stem,
        title=args.title,
        interpretation_note=args.interpretation_note,
    )
    print(json.dumps({"summary": _brief_summary(summary), "paths": paths}, indent=2))


def _brief_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "paired_n": summary["paired_n"],
        "recoveries": summary["recoveries"],
        "regressions": summary["regressions"],
        "net_correct_delta": summary["net_correct_delta"],
        "baseline_accuracy": summary["baseline_accuracy"],
        "treatment_accuracy": summary["treatment_accuracy"],
    }


if __name__ == "__main__":
    main()
