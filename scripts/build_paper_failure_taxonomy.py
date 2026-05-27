"""Build failure-taxonomy tables for the FocusParse paper draft."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.diagnose_predictions import (
    _answer_packet_citations,
    _classify_failure_reason,
    _debug_evidence_snapshot,
    _evidence_snapshot,
    _packet_has_chart,
    _packet_has_text,
)

DEFAULT_PER_EXAMPLE = Path(
    "results/hf/paper/2026-05-24-paper-headline-v1/headline/"
    "focusparse_focus_agentic_multi_page_0b139a04/per_example.jsonl"
)
DEFAULT_OUTPUT_DIR = Path("results/paper/failure-taxonomy")

REASON_LABELS = {
    "verifier_unsupported": "Verifier unsupported",
    "partial_localization": "Partial localization",
    "localization_miss": "Localization miss",
    "reasoning_or_extraction": "Reasoning/extraction",
    "lazy_or_no_bbox": "Lazy/no bbox",
    "empty_citation": "Empty citation",
    "abstained": "Abstained",
    "cited_image_only": "Cited image only",
}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def clean_domain(value: str) -> str:
    return value.removeprefix("Domain.").lower()


def verifier_supported(record: dict[str, Any]) -> bool | None:
    supported: bool | None = None
    for step in (record.get("trace") or {}).get("steps") or []:
        if step.get("stage") != "verify":
            continue
        args = step.get("args") or {}
        if "supported" in args:
            supported = bool(args.get("supported"))
    return supported


def any_cited_image_only(record: dict[str, Any], citations: list[str]) -> bool:
    packets = _debug_evidence_snapshot(record) or _evidence_snapshot(record)
    packet_by_id = {
        str(packet.get("packet_id")): packet
        for packet in packets
        if isinstance(packet, dict) and packet.get("packet_id")
    }
    for citation in citations:
        packet = packet_by_id.get(citation)
        if not packet:
            continue
        if not _packet_has_text(packet) and not _packet_has_chart(packet):
            return True
    return False


def classify_record(record: dict[str, Any]) -> str | None:
    if float(record.get("answer_correct") or 0.0) >= 1.0:
        return None
    citations = _answer_packet_citations(record)
    return _classify_failure_reason(
        record,
        answer_citations=citations,
        any_cited_image_only=any_cited_image_only(record, citations),
        verifier_supported=verifier_supported(record),
    )


def compact_text(value: Any, limit: int = 140) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def build_outputs(rows: list[dict[str, Any]], source: Path) -> dict[str, Any]:
    total = len(rows)
    correct = sum(1 for row in rows if float(row.get("answer_correct") or 0.0) >= 1.0)
    incorrect = total - correct
    reason_counts: Counter[str] = Counter()
    domain_counts: dict[str, Counter[str]] = defaultdict(Counter)
    examples: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for row in rows:
        reason = classify_record(row)
        if reason is None:
            continue
        domain = clean_domain(str(row.get("domain") or "unknown"))
        reason_counts[reason] += 1
        domain_counts[reason][domain] += 1
        if len(examples[reason]) < 3:
            examples[reason].append(
                {
                    "example_id": row.get("example_id"),
                    "domain": domain,
                    "pred": compact_text(row.get("answer_pred")),
                    "gold": compact_text(row.get("answer_gold")),
                    "page_recall": row.get("page_recall"),
                    "bbox_iou": row.get("bbox_iou"),
                    "loop_terminated": (row.get("telemetry") or {}).get("loop_terminated"),
                }
            )

    ordered_reasons = [
        reason for reason, _count in reason_counts.most_common()
    ]
    return {
        "source": source.as_posix(),
        "total_rows": total,
        "correct": correct,
        "incorrect": incorrect,
        "accuracy": correct / total if total else None,
        "failure_counts": dict(reason_counts),
        "failure_domain_counts": {
            reason: dict(domain_counts[reason]) for reason in ordered_reasons
        },
        "examples": {reason: examples[reason] for reason in ordered_reasons},
    }


def write_csv(summary: dict[str, Any], path: Path) -> None:
    total = int(summary["total_rows"])
    incorrect = int(summary["incorrect"])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "reason",
                "label",
                "count",
                "datasheet",
                "finance",
                "error_share",
                "all_rows_share",
            ],
        )
        writer.writeheader()
        for reason, count in Counter(summary["failure_counts"]).most_common():
            domains = summary["failure_domain_counts"].get(reason, {})
            writer.writerow(
                {
                    "reason": reason,
                    "label": REASON_LABELS.get(reason, reason),
                    "count": count,
                    "datasheet": domains.get("datasheet", 0),
                    "finance": domains.get("finance", 0),
                    "error_share": count / incorrect if incorrect else 0,
                    "all_rows_share": count / total if total else 0,
                }
            )


def pct(value: float) -> str:
    return f"{value:.1%}"


def fmt_float(value: Any) -> str:
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return "-"


def write_markdown(summary: dict[str, Any], path: Path) -> None:
    total = int(summary["total_rows"])
    correct = int(summary["correct"])
    incorrect = int(summary["incorrect"])
    lines = [
        "# FocusParse Failure Taxonomy",
        "",
        "Date: 2026-05-24",
        "",
        "Source:",
        "",
        f"```text\n{summary['source']}\n```",
        "",
        "Scope: final matched FocusParse +4 run on the pinned 148-row parser-bench paper slice.",
        "",
        "## Summary",
        "",
        f"- Correct: {correct}/{total} ({pct(correct / total)})",
        f"- Incorrect: {incorrect}/{total} ({pct(incorrect / total)})",
        "",
        "## Primary Failure Buckets",
        "",
        "| Bucket | Count | Datasheet | Finance | Error share | All-row share |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for reason, count in Counter(summary["failure_counts"]).most_common():
        domains = summary["failure_domain_counts"].get(reason, {})
        lines.append(
            "| "
            f"{REASON_LABELS.get(reason, reason)} | {count} | "
            f"{domains.get('datasheet', 0)} | {domains.get('finance', 0)} | "
            f"{pct(count / incorrect)} | {pct(count / total)} |"
        )
    lines.extend(
        [
            "",
            "Interpretation:",
            "",
            "- `Verifier unsupported` means the run found cited evidence, but the verifier still did not support the final answer.",
            "- `Partial localization` means at least one required region was found, but not all target regions were localized.",
            "- `Localization miss` means region recall was zero or the best localization IoU was near zero.",
            "- `Reasoning/extraction` means localization did not trip the earlier pathologies, but the final answer was still wrong.",
            "- `Lazy/no bbox` means the answer had no usable predicted bounding boxes or was marked lazy by the harness.",
            "",
            "## Representative Examples",
            "",
        ]
    )
    for reason, examples in summary["examples"].items():
        lines.extend(
            [
                f"### {REASON_LABELS.get(reason, reason)}",
                "",
                "| Example | Domain | Pred | Gold | Page recall | BBox IoU | Loop |",
                "| --- | --- | --- | --- | ---: | ---: | --- |",
            ]
        )
        for example in examples:
            lines.append(
                "| "
                f"`{example['example_id']}` | {example['domain']} | "
                f"`{example['pred']}` | `{example['gold']}` | "
                f"{fmt_float(example['page_recall'])} | {fmt_float(example['bbox_iou'])} | "
                f"{example.get('loop_terminated') or '-'} |"
            )
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-example", type=Path, default=DEFAULT_PER_EXAMPLE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = load_jsonl(args.per_example)
    summary = build_outputs(rows, args.per_example)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "failure-taxonomy.json").write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )
    write_csv(summary, args.output_dir / "failure-taxonomy.csv")
    write_markdown(summary, args.output_dir / "failure-taxonomy.md")
    print(json.dumps({"output_dir": args.output_dir.as_posix(), "incorrect": summary["incorrect"]}))


if __name__ == "__main__":
    main()
