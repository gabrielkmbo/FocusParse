#!/usr/bin/env python3
"""Summarize same-revision qualitative baseline predictions for paper figures."""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_HEADLINE_DIR = Path("results/hf/paper/2026-05-24-paper-headline-v1/headline")
DEFAULT_OUTPUT_DIR = Path("results/paper/qualitative-baseline-comparisons")
DEFAULT_EXAMPLE_IDS = (
    "fin-bis_qr_2025_mar-0050",
    "dat-JESD204B-Survival-Guide-0029",
)


@dataclass(frozen=True)
class MethodSpec:
    """Method directory and paper-facing label."""

    label: str
    path_name: str


METHODS = (
    MethodSpec("Base VLM", "focusparse_simple_agentic_multi_page_0b139a04"),
    MethodSpec("ReAct +2 tools", "focusparse_react_agentic_multi_page_0b139a04_tminimal"),
    MethodSpec("ReAct +4 tools", "focusparse_react_agentic_multi_page_0b139a04"),
    MethodSpec(
        "Agent baseline +2 tools", "focusparse_agent_baseline_agentic_multi_page_0b139a04_tminimal"
    ),
    MethodSpec("Agent baseline +4 tools", "focusparse_agent_baseline_agentic_multi_page_0b139a04"),
    MethodSpec("FocusParse +2 tools", "focusparse_focus_agentic_multi_page_0b139a04_tminimal"),
    MethodSpec("FocusParse +4 tools", "focusparse_focus_agentic_multi_page_0b139a04"),
)


EXAMPLE_LABELS = {
    "fin-bis_qr_2025_mar-0050": "Latvia finance evidence binding",
    "dat-JESD204B-Survival-Guide-0029": "JESD204B datasheet evidence compaction",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--headline-dir", type=Path, default=DEFAULT_HEADLINE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--example-id", action="append", dest="example_ids")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    example_ids = tuple(args.example_ids or DEFAULT_EXAMPLE_IDS)
    rows = collect_rows(args.headline_dir, example_ids)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(rows, args.output_dir / "qualitative-baseline-comparison.csv")
    write_markdown(rows, args.output_dir / "qualitative-baseline-comparison.md")
    print(f"Wrote {len(rows)} method-example row(s) to {args.output_dir}")


def collect_rows(headline_dir: Path, example_ids: tuple[str, ...]) -> list[dict[str, Any]]:
    rows = []
    for method in METHODS:
        per_example = headline_dir / method.path_name / "per_example.jsonl"
        records = load_records(per_example)
        for example_id in example_ids:
            if example_id not in records:
                raise KeyError(f"{example_id} missing from {per_example}")
            record = records[example_id]
            answer_pred = clean_answer(record.get("answer_pred"))
            answer_gold = clean_answer(record.get("answer_gold"))
            rows.append(
                {
                    "example_id": example_id,
                    "example_label": EXAMPLE_LABELS.get(example_id, example_id),
                    "method": method.label,
                    "prediction": answer_pred,
                    "gold": answer_gold,
                    "answer_correct": record.get("answer_correct"),
                    "exact_text_match": exact_match(answer_pred, answer_gold),
                    "is_lazy": record.get("is_lazy"),
                    "page_recall": record.get("page_recall"),
                    "bbox_iou": record.get("bbox_iou"),
                    "citation_count": len(record.get("citations") or []),
                    "tool_sequence": " -> ".join(record.get("tool_call_sequence") or []),
                    "failure_mode": classify(record, answer_pred, answer_gold),
                }
            )
    return rows


def load_records(path: Path) -> dict[str, dict[str, Any]]:
    records = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            records[row["example_id"]] = row
    return records


def classify(record: dict[str, Any], answer_pred: str, answer_gold: str) -> str:
    correct = float(record.get("answer_correct") or 0.0) >= 1.0
    exact = exact_match(answer_pred, answer_gold)
    page_recall = float(record.get("page_recall") or 0.0)
    bbox_iou = float(record.get("bbox_iou") or 0.0)
    citations = record.get("citations") or []
    lazy = int(record.get("is_lazy") or 0) == 1

    if not correct and answer_pred.lower() == "unanswerable":
        return "unanswerable"
    if looks_like_raw_transcript(answer_pred):
        return "raw tool transcript / invalid final"
    if not correct:
        return "wrong answer"
    if correct and not exact and normalize_text(answer_gold) not in normalize_text(answer_pred):
        return "scorer accepted non-exact answer"
    if not citations or lazy or page_recall == 0:
        return "correct answer without grounded evidence"
    if correct and not exact:
        return "scorer accepted non-exact answer"
    if page_recall < 1.0:
        return "correct answer with incomplete page grounding"
    if bbox_iou < 0.8:
        return "correct answer with weak region grounding"
    return "grounded correct"


def looks_like_raw_transcript(text: str) -> bool:
    lowered = text.lower()
    return (
        "action_input" in lowered
        or "final_answer" in lowered
        or "```json" in lowered
        or lowered.count('"action"') >= 1
    )


def clean_answer(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if text else "<empty>"


def exact_match(prediction: str, gold: str) -> bool:
    return normalize_text(prediction) == normalize_text(gold)


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def short(value: str, limit: int = 150) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."


def fmt_metric(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, int | float):
        return f"{float(value):.3f}"
    return str(value)


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    fieldnames = [
        "example_id",
        "example_label",
        "method",
        "prediction",
        "gold",
        "answer_correct",
        "exact_text_match",
        "is_lazy",
        "page_recall",
        "bbox_iou",
        "citation_count",
        "tool_sequence",
        "failure_mode",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(rows: list[dict[str, Any]], path: Path) -> None:
    lines = [
        "# FocusParse Qualitative Baseline Comparison",
        "",
        "Same-revision predictions for the main qualitative figure examples from the",
        "final May 24 matched headline run.",
        "",
    ]
    by_example: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_example.setdefault(row["example_id"], []).append(row)

    for example_id, example_rows in by_example.items():
        lines.extend([f"## {EXAMPLE_LABELS.get(example_id, example_id)}", ""])
        lines.append(f"Example id: `{example_id}`")
        lines.append("")
        lines.append(
            "| Method | Prediction | Correct | Exact | Page recall | BBox IoU | Citations | Failure mode |"
        )
        lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |")
        for row in example_rows:
            lines.append(
                "| "
                + " | ".join(
                    [
                        row["method"],
                        f"`{short(row['prediction'])}`",
                        fmt_metric(row["answer_correct"]),
                        "yes" if row["exact_text_match"] else "no",
                        fmt_metric(row["page_recall"]),
                        fmt_metric(row["bbox_iou"]),
                        str(row["citation_count"]),
                        row["failure_mode"],
                    ]
                )
                + " |"
            )
        lines.append("")

    lines.extend(
        [
            "## Paper Takeaway",
            "",
            "- The Latvia example separates answer accuracy from evidence construction:",
            "  Base VLM is unanswerable, generic agents choose Estonia without grounded",
            "  citations, and FocusParse +4 supplies all three evidence pages.",
            "- The JESD204B example shows why the paper should report grounding metrics:",
            "  several baselines can state `6`, but only FocusParse has complete page",
            "  recall with near-perfect region overlap on the cross-page evidence.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
