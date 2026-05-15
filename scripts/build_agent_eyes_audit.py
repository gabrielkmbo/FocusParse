"""Build an "agent eyes" audit bundle for FocusParse prediction runs.

The normal run summary answers "how many were correct?". This script answers
"what exactly did the agent see?" for the rows worth inspecting next. It reads
one spec directory with `predictions/*.json`, emits:

  * `index.html` — compact wrong-row triage table.
  * `agent_eyes_audit.jsonl` — machine-readable failure summaries.
  * `examples/<example_id>.html` — full trace viewer pages with page overlays,
    selected crops, multi-scale crops, linked neighbor crops, OCR/text snippets,
    answer history, verifier payloads, and all debug events.

Usage:

    uv run python scripts/build_agent_eyes_audit.py \\
      --spec-dir results/hf/sprint-2026-05-15/chart-fallback-context-only-oai-run1/focusparse_focus_agentic_multi_page_8c5e328d \\
      --output-dir results/agent_eyes/chart-fallback-context-only-wrong \\
      --staging-root /Users/gabrielbo/.cache/focusparse/hf_staging_full_2026-05-13
"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any

from focusparse.traces.viewer import DEFAULT_STAGING_ROOT, build_view_model, render_html


def load_prediction_records(spec_dir: Path) -> list[dict[str, Any]]:
    per_example = spec_dir / "per_example.jsonl"
    if per_example.is_file():
        records: list[dict[str, Any]] = []
        for line_no, line in enumerate(per_example.read_text().splitlines(), start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "example_id" not in record:
                record["example_id"] = f"row-{line_no:04d}"
            records.append(record)
        _assign_artifact_ids(records)
        return records

    pred_dir = spec_dir / "predictions"
    if not pred_dir.is_dir():
        raise FileNotFoundError(f"prediction directory not found: {pred_dir}")
    records = []
    for path in sorted(pred_dir.glob("*.json")):
        try:
            record = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        if "example_id" not in record:
            record["example_id"] = path.stem
        records.append(record)
    _assign_artifact_ids(records)
    return records


def _assign_artifact_ids(records: list[dict[str, Any]]) -> None:
    """Give every row a unique viewer filename, even duplicate example ids."""
    seen: dict[str, int] = {}
    for idx, record in enumerate(records, start=1):
        eid = str(record.get("example_id") or f"row-{idx:04d}")
        count = seen.get(eid, 0) + 1
        seen[eid] = count
        record["_agent_eyes_artifact_id"] = eid if count == 1 else f"{eid}__{count}"


def build_audit_rows(
    records: list[dict[str, Any]],
    *,
    include_correct: bool = False,
    example_ids: set[str] | None = None,
    limit: int | None = 40,
    benchmark_lookup: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        eid = str(record.get("example_id") or "")
        if example_ids is not None and eid not in example_ids:
            continue
        if not include_correct and float(record.get("answer_correct") or 0.0) >= 1.0:
            continue
        rows.append(summarize_record(record, benchmark=(benchmark_lookup or {}).get(eid)))

    rows.sort(
        key=lambda row: (
            -float(row.get("page_recall") or 0.0),
            -float(row.get("bbox_iou") or 0.0),
            str(row.get("example_id") or ""),
        )
    )
    return rows[:limit] if limit is not None else rows


def summarize_record(
    record: dict[str, Any],
    *,
    benchmark: dict[str, Any] | None = None,
) -> dict[str, Any]:
    trace = record.get("trace") or {}
    debug_events = trace.get("debug_events") or []
    snapshot = trace.get("evidence_snapshot") or []
    plan = _plan_args(trace)
    final_verdict = _last_payload(debug_events, stage="verify", event_type="verdict")
    answer_history = [
        {
            "retry_attempt": event.get("retry_attempt") or 0,
            "answer": (event.get("payload") or {}).get("answer"),
            "citations": (event.get("payload") or {}).get("citations") or [],
            "confidence": (event.get("payload") or {}).get("confidence"),
            "evidence_scope": (event.get("payload") or {}).get("evidence_scope"),
        }
        for event in debug_events
        if event.get("stage") == "answer" and event.get("event_type") == "answer"
    ]
    return {
        "artifact_id": record.get("_agent_eyes_artifact_id") or record.get("example_id"),
        "example_id": record.get("example_id"),
        "domain": record.get("domain"),
        "question": (trace.get("question") if isinstance(trace, dict) else None)
        or record.get("question")
        or (benchmark or {}).get("question"),
        "answer_pred": record.get("answer_pred"),
        "answer_gold": record.get("answer_gold") or (benchmark or {}).get("answer"),
        "answer_correct": record.get("answer_correct"),
        "page_recall": record.get("page_recall"),
        "bbox_iou": record.get("bbox_iou"),
        "evidence_reward": record.get("evidence_reward"),
        "retries_used": (record.get("telemetry") or {}).get("retries_used"),
        "loop_terminated": (record.get("telemetry") or {}).get("loop_terminated"),
        "question_family": plan.get("question_family"),
        "routing_policy": plan.get("routing_policy"),
        "budget_class": plan.get("budget_class"),
        "final_verdict": {
            "supported": final_verdict.get("supported"),
            "next_action": final_verdict.get("next_action"),
            "reason": final_verdict.get("reason"),
            "target_packet_ids": (final_verdict.get("diagnostics") or {}).get("target_packet_ids")
            or [],
            "missing_context": (final_verdict.get("diagnostics") or {}).get("missing_context")
            or [],
        },
        "answer_history": answer_history,
        "packets": [_packet_summary(packet) for packet in snapshot],
    }


def write_agent_eyes_audit(
    *,
    spec_dir: Path,
    output_dir: Path,
    staging_root: Path,
    include_correct: bool = False,
    example_ids: set[str] | None = None,
    limit: int | None = 40,
) -> list[dict[str, Any]]:
    records = load_prediction_records(spec_dir)
    benchmark_lookup = load_benchmark_lookup(staging_root)
    rows = build_audit_rows(
        records,
        include_correct=include_correct,
        example_ids=example_ids,
        limit=limit,
        benchmark_lookup=benchmark_lookup,
    )
    by_id = {
        str(record.get("_agent_eyes_artifact_id") or record.get("example_id")): record
        for record in records
    }
    output_dir.mkdir(parents=True, exist_ok=True)

    search_dirs = [
        spec_dir / "crops",
        spec_dir / "tiles",
        Path("cache/crops"),
    ]

    examples_dir = output_dir / "examples"
    examples_dir.mkdir(exist_ok=True)
    for row in rows:
        eid = str(row["example_id"])
        artifact_id = str(row.get("artifact_id") or eid)
        record = by_id[artifact_id]
        view = build_view_model(record, search_dirs=search_dirs, staging_root=staging_root)
        html_text = render_html(view, title=f"Agent eyes · {eid}")
        (examples_dir / f"{artifact_id}.html").write_text(html_text)

    with (output_dir / "agent_eyes_audit.jsonl").open("w") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=True) + "\n")
    render_index(rows, output_dir / "index.html")
    return rows


def load_benchmark_lookup(staging_root: Path) -> dict[str, dict[str, Any]]:
    jsonl = staging_root / "benchmark.jsonl"
    if not jsonl.is_file():
        return {}
    out: dict[str, dict[str, Any]] = {}
    for line in jsonl.read_text().splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        eid = row.get("id")
        if eid:
            out[str(eid)] = row
    return out


def render_index(rows: list[dict[str, Any]], output_path: Path) -> None:
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="UTF-8">',
        "<title>Agent eyes audit</title>",
        '<script src="https://cdn.tailwindcss.com"></script>',
        '</head><body class="bg-slate-50 p-6 max-w-7xl mx-auto">',
        '<h1 class="text-2xl font-bold mb-2">Agent Eyes Audit</h1>',
        '<p class="text-sm text-slate-600 mb-6">'
        "Rows are sorted by high page recall and bbox IoU first, so the top "
        "failures are usually answer/extraction mistakes over evidence the "
        "agent already saw."
        "</p>",
        '<table class="w-full text-sm bg-white rounded shadow overflow-hidden">',
        '<thead class="bg-slate-100"><tr>',
    ]
    for header in [
        "example",
        "question",
        "family",
        "metrics",
        "prediction",
        "gold",
        "final verifier",
        "packet view",
    ]:
        parts.append(f'<th class="text-left align-top p-2">{html.escape(header)}</th>')
    parts.append("</tr></thead><tbody>")

    for row in rows:
        eid = str(row.get("example_id") or "")
        artifact_id = str(row.get("artifact_id") or eid)
        verdict = row.get("final_verdict") or {}
        packets = row.get("packets") or []
        packet_bits = []
        for packet in packets[:4]:
            snippet = packet.get("text") or ""
            packet_bits.append(
                f"{html.escape(str(packet.get('packet_id')))} "
                f"p{html.escape(str(packet.get('page')))} "
                f"{html.escape(str(packet.get('region_type') or '?'))}: "
                f"{html.escape(_shorten(snippet, 90))}"
            )
        parts.append('<tr class="border-t">')
        parts.append(
            '<td class="p-2 align-top">'
            f'<a class="font-mono text-xs underline text-blue-700" '
            f'href="examples/{html.escape(artifact_id)}.html">{html.escape(eid)}</a>'
            f'<div class="text-xs text-slate-500">{html.escape(str(row.get("domain") or ""))}</div>'
            "</td>"
        )
        parts.append(
            '<td class="p-2 align-top max-w-sm text-xs">'
            f"{html.escape(_shorten(str(row.get('question') or ''), 220))}"
            "</td>"
        )
        parts.append(
            '<td class="p-2 align-top">'
            f"{html.escape(str(row.get('question_family') or '?'))}"
            f'<div class="text-xs text-slate-500">{html.escape(str(row.get("budget_class") or ""))}</div>'
            "</td>"
        )
        parts.append(
            '<td class="p-2 align-top font-mono text-xs">'
            f"correct={html.escape(str(row.get('answer_correct')))}<br>"
            f"page={_fmt(row.get('page_recall'))}<br>"
            f"iou={_fmt(row.get('bbox_iou'))}<br>"
            f"retry={html.escape(str(row.get('retries_used')))}"
            "</td>"
        )
        parts.append(
            '<td class="p-2 align-top max-w-xs">'
            f'<div class="font-mono whitespace-pre-wrap">{html.escape(str(row.get("answer_pred") or ""))}</div>'
            "</td>"
        )
        parts.append(
            '<td class="p-2 align-top max-w-xs">'
            f'<div class="font-mono whitespace-pre-wrap">{html.escape(str(row.get("answer_gold") or ""))}</div>'
            "</td>"
        )
        parts.append(
            '<td class="p-2 align-top max-w-sm">'
            f'<div class="font-medium">{html.escape(str(verdict.get("next_action") or "?"))} '
            f"supported={html.escape(str(verdict.get('supported')))}</div>"
            f'<div class="text-xs text-slate-600">{html.escape(_shorten(str(verdict.get("reason") or ""), 220))}</div>'
            "</td>"
        )
        parts.append('<td class="p-2 align-top max-w-sm">' + "<br>".join(packet_bits) + "</td>")
        parts.append("</tr>")

    parts.append("</tbody></table></body></html>")
    output_path.write_text("\n".join(parts))


def _plan_args(trace: dict[str, Any]) -> dict[str, Any]:
    for step in trace.get("steps") or []:
        if step.get("stage") == "plan":
            return step.get("args") or {}
    return {}


def _last_payload(
    events: list[dict[str, Any]],
    *,
    stage: str,
    event_type: str,
) -> dict[str, Any]:
    for event in reversed(events):
        if event.get("stage") == stage and event.get("event_type") == event_type:
            payload = event.get("payload")
            return payload if isinstance(payload, dict) else {}
    return {}


def _packet_summary(packet: dict[str, Any]) -> dict[str, Any]:
    text = packet.get("text_layer_snippet") or packet.get("ocr_snippet") or ""
    return {
        "packet_id": packet.get("packet_id"),
        "page": packet.get("page"),
        "bbox_norm": packet.get("bbox_norm"),
        "region_type": packet.get("region_type"),
        "confidence": packet.get("confidence"),
        "local_crop_ref": packet.get("local_crop_ref"),
        "linked_neighbor_types": packet.get("linked_neighbor_types") or [],
        "multi_scale_crops": [
            {"scale": crop.get("scale"), "bbox_norm": crop.get("bbox_norm")}
            for crop in (packet.get("multi_scale_crops") or [])
            if isinstance(crop, dict)
        ],
        "text": text,
        "chart_csv": packet.get("chart_csv"),
    }


def _shorten(text: str, max_chars: int) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3] + "..."


def _fmt(value: Any) -> str:
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return "n/a"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--staging-root", type=Path, default=DEFAULT_STAGING_ROOT)
    parser.add_argument(
        "--include-correct",
        action="store_true",
        help="Render correct rows too. Default renders only wrong rows.",
    )
    parser.add_argument(
        "--example-id",
        action="append",
        default=None,
        help="Render a specific example id. Repeatable. Overrides wrong-only filtering only with --include-correct.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=40,
        help="Maximum rows/viewers to render. Use 0 for no limit.",
    )
    args = parser.parse_args()

    rows = write_agent_eyes_audit(
        spec_dir=args.spec_dir,
        output_dir=args.output_dir,
        staging_root=args.staging_root,
        include_correct=args.include_correct,
        example_ids=set(args.example_id) if args.example_id else None,
        limit=None if args.limit == 0 else args.limit,
    )
    print(f"wrote {len(rows)} agent-eyes rows under {args.output_dir}")


if __name__ == "__main__":
    main()
