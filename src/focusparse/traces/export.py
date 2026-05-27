"""SFT-ready JSONL export for trajectory traces.

Schema version 4 (2026-05-07). Changes here are breaking — bump
`SCHEMA_VERSION` and document the migration in the relevant release notes or
paper artifact notes.

v1 → v2: added `evidence_snapshot` (list of `EvidencePacketSummary`,
optional). v1 records remain readable; v2 readers should treat the
field as nullable.

v2 → v3: added `artifacts` and `debug_events` for one-example HTML
dashboards. Payloads store paths/refs and JSON metadata only, never raw
image bytes.

v3 → v4: added `linked_neighbor_types` to `evidence_snapshot` packet
summaries so offline diagnostics and trace viewers can tell whether linked
neighbor crops are captions, footnotes, legends, etc.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from focusparse.traces.recorder import RunTrace

SCHEMA_VERSION = "4"


def coverage_recall(predicted_pages: set[int], gold_pages: set[int]) -> float:
    if not gold_pages:
        return 1.0
    return len(predicted_pages & gold_pages) / len(gold_pages)


def passes_sft_filter(
    trace: RunTrace,
    *,
    min_coverage: float = 0.8,
    min_iou: float = 0.3,
    require_correct: bool = True,
) -> bool:
    """AgenticOCR dual-threshold filter: coverage AND IoU must clear, and
    (optionally) the final answer must be correct."""
    reward = trace.reward or {}
    if require_correct and reward.get("answer", 0.0) < 1.0:
        return False
    if reward.get("coverage", 0.0) < min_coverage:
        return False
    return reward.get("iou", 0.0) >= min_iou


def trace_to_sft_record(trace: RunTrace, *, teacher_tier: str = "frontier") -> dict:
    """Serialize a RunTrace to the v4 SFT JSONL record shape.

    v4 keeps `evidence_snapshot`, `artifacts`, and `debug_events`, and the
    snapshot now carries linked-neighbor roles. All image-like values are
    references, not inlined bytes.
    """
    snapshot = trace.evidence_snapshot
    return {
        "schema_version": SCHEMA_VERSION,
        "example_id": trace.example_id,
        "question": trace.question,
        "plan": trace.plan,
        "trajectory": [
            {
                "step_index": s.step_index,
                "stage": s.stage,
                "tier": s.tier,
                "action": s.action,
                "tool": s.tool,
                "args": s.args,
                "obs_ref": s.obs_ref,
                "obs_summary": s.obs_summary,
                "tokens_in": s.tokens_in,
                "tokens_out": s.tokens_out,
                "latency_ms": s.latency_ms,
                "usd": s.usd,
                "confidence": s.confidence,
            }
            for s in trace.steps
        ],
        "evidence_snapshot": (
            [p.model_dump(mode="json") for p in snapshot] if snapshot is not None else None
        ),
        "artifacts": [a.model_dump(mode="json") for a in trace.artifacts],
        "debug_events": [e.model_dump(mode="json") for e in trace.debug_events],
        "final": {
            "answer": trace.final_answer,
            "citations": trace.final_citations,
        },
        "reward": trace.reward,
        "teacher_tier": teacher_tier,
    }


def export_sft_jsonl(
    traces: Iterable[RunTrace],
    out_path: Path | str,
    *,
    min_coverage: float = 0.8,
    min_iou: float = 0.3,
    require_correct: bool = True,
    teacher_tier: str = "frontier",
) -> int:
    """Write filtered traces to a JSONL. Returns the number of lines written."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(out_path, "w") as f:
        for trace in traces:
            if not passes_sft_filter(
                trace,
                min_coverage=min_coverage,
                min_iou=min_iou,
                require_correct=require_correct,
            ):
                continue
            record = trace_to_sft_record(trace, teacher_tier=teacher_tier)
            f.write(json.dumps(record, separators=(",", ":")) + "\n")
            n += 1
    return n


def load_eval_run_traces(run_dir: Path | str) -> list[RunTrace]:
    """Load `RunTrace` objects from a run directory's `per_example.jsonl`.

    Focus eval runs persist traces inside each per-example record. The
    export schema needs a `RunTrace`, so this adapter reconstructs the trace
    from the cached record without re-running the model.
    """
    run_dir = Path(run_dir)
    per_example_path = run_dir / "per_example.jsonl"
    if not per_example_path.exists():
        raise FileNotFoundError(f"per-example predictions not found: {per_example_path}")

    traces: list[RunTrace] = []
    for line in per_example_path.read_text().splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        traces.append(_trace_from_eval_record(record))
    return traces


def export_eval_run_sft_jsonl(
    run_dir: Path | str,
    out_path: Path | str,
    *,
    min_coverage: float = 0.8,
    min_iou: float = 0.3,
    require_correct: bool = True,
    teacher_tier: str = "frontier",
) -> int:
    """Export SFT JSONL directly from a FocusParse eval run directory."""
    traces = load_eval_run_traces(run_dir)
    return export_sft_jsonl(
        traces,
        out_path,
        min_coverage=min_coverage,
        min_iou=min_iou,
        require_correct=require_correct,
        teacher_tier=teacher_tier,
    )


def _trace_from_eval_record(record: dict[str, Any]) -> RunTrace:
    trace = record.get("trace") if isinstance(record.get("trace"), dict) else {}
    reward = {
        "answer": float(record.get("answer_correct") or 0.0),
        "coverage": float(record.get("page_recall") or 0.0),
        "iou": float(record.get("bbox_iou") or 0.0),
        "evidence": float(record.get("evidence_reward") or 0.0),
    }
    payload = {
        "example_id": str(record.get("example_id") or ""),
        "question": str(record.get("question") or ""),
        "plan": record.get("plan") or {},
        "steps": trace.get("steps") or [],
        "final_answer": record.get("answer_pred"),
        "final_citations": record.get("citations") or [],
        "reward": reward,
        "evidence_snapshot": trace.get("evidence_snapshot"),
        "artifacts": trace.get("artifacts") or [],
        "debug_events": trace.get("debug_events") or [],
    }
    return RunTrace.model_validate(payload)
