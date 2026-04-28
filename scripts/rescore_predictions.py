"""Re-score cached eval predictions without re-running the model.

Reads `<run_dir>/predictions/*.json` produced by `run_simple_eval` /
`run_focus_eval`, re-applies the current `score_answer` / `page_recall` /
`max_iou_over_alternates` / `score_evidence_reward` to each, and rewrites
the same predictions JSON + the run.json aggregate.

Use after a scoring fix to verify the change against an existing matrix
(e.g. the Phase 1 enum-routing fix on the Arm_EE382N_4 7-example run).
Cheap: O(disk), no API calls.

Usage:
  uv run python scripts/rescore_predictions.py results/hf/single-doc-arm/focusparse_simple_tiled_4up_7d4b816d.json
  uv run python scripts/rescore_predictions.py results/hf/single-doc-arm  # recurse
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def _load_benchmark(benchmark_jsonl: Path) -> dict[str, Any]:
    """Load benchmark.jsonl into an `id -> BenchmarkExample` map."""
    from focusparse._parser_bench import BenchmarkExample

    out: dict[str, BenchmarkExample] = {}
    for line in benchmark_jsonl.read_text().splitlines():
        if not line.strip():
            continue
        ex = BenchmarkExample.model_validate_json(line)
        out[ex.id] = ex
    return out


def _rescore_one(
    record: dict[str, Any],
    example: Any,
    image_dims_by_page: dict[int, tuple[int, int]] | None,
) -> dict[str, Any]:
    """Recompute answer/page/iou/evidence_reward for one prediction record."""
    from focusparse._parser_bench import BBox as _BBox
    from focusparse.eval.scoring import (
        max_iou_over_alternates,
        page_recall,
        score_answer,
        score_evidence_reward,
    )

    citations = record.get("citations") or []
    predicted_pages = [int(c["page"]) for c in citations if "page" in c]
    predicted_bboxes: list[Any] = []
    for c in citations:
        bbox = c.get("bbox")
        if not (isinstance(bbox, list) and len(bbox) == 4):
            continue
        try:
            predicted_bboxes.append(
                _BBox(
                    page=int(c["page"]),
                    x0=float(bbox[0]),
                    y0=float(bbox[1]),
                    x1=float(bbox[2]),
                    y1=float(bbox[3]),
                )
            )
        except (TypeError, ValueError, KeyError):
            continue

    pred_text = record.get("answer_pred", "") or ""
    answer = score_answer(pred_text, example)
    recall = page_recall(predicted_pages, [int(p) for p in (example.supporting_pages or [])])
    iou = max_iou_over_alternates(predicted_bboxes, example, image_dims_by_page=image_dims_by_page)

    # Trace tool calls (if present) feed the lazy-answer penalty
    tool_calls: list[dict[str, Any]] = []
    trace = record.get("trace") or {}
    for step in trace.get("steps", []) or []:
        if step.get("tool") or step.get("action") == "tool_call":
            tool_calls.append({"tool": step.get("tool")})

    evidence = score_evidence_reward(
        prediction_text=pred_text,
        predicted_pages=predicted_pages,
        predicted_bboxes=predicted_bboxes,
        tool_calls=tool_calls,
        example=example,
        largest_crop_area_ratio=0.0,
        image_dims_by_page=image_dims_by_page,
    )

    record["answer_correct"] = float(answer)
    record["page_recall"] = float(recall)
    record["bbox_iou"] = float(iou)
    record["evidence_reward"] = float(evidence)
    record["is_lazy"] = int(len(tool_calls) == 0 or not predicted_bboxes)
    return record


def _aggregate(per_example: list[dict[str, Any]]) -> dict[str, Any]:
    """Mirror `eval.metrics.aggregate` for our subset of fields."""
    n = len(per_example)
    if n == 0:
        return {
            "accuracy": 0.0,
            "abstain_rate": 0.0,
            "page_recall": 0.0,
            "bbox_iou": 0.0,
            "count": 0,
            "total_cost_usd": 0.0,
            "cost_per_correct_usd": None,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "evidence_reward_mean": None,
            "lazy_answer_rate": None,
            "tool_calls_mean": None,
        }

    correct = sum(r.get("answer_correct", 0) or 0 for r in per_example)
    page_r = sum(r.get("page_recall", 0) or 0 for r in per_example) / n
    iou_m = sum(r.get("bbox_iou", 0) or 0 for r in per_example) / n
    cost = sum(r.get("usd", 0) or 0 for r in per_example)
    in_tok = sum(r.get("tokens_in", 0) or 0 for r in per_example)
    out_tok = sum(r.get("tokens_out", 0) or 0 for r in per_example)
    ev = [r.get("evidence_reward") for r in per_example if r.get("evidence_reward") is not None]
    lazy_vals = [r.get("is_lazy") for r in per_example if r.get("is_lazy") is not None]
    tool_vals = [r.get("tool_calls") for r in per_example if r.get("tool_calls") is not None]

    accuracy = correct / n
    abstain_rate = (
        sum(1 for r in per_example if "unanswerable" in (r.get("answer_pred") or "").lower()) / n
    )
    return {
        "accuracy": accuracy,
        "abstain_rate": abstain_rate,
        "page_recall": page_r,
        "bbox_iou": iou_m,
        "count": n,
        "total_cost_usd": cost,
        "cost_per_correct_usd": (cost / correct) if correct else None,
        "total_input_tokens": in_tok,
        "total_output_tokens": out_tok,
        "evidence_reward_mean": (sum(ev) / len(ev)) if ev else None,
        "lazy_answer_rate": (sum(lazy_vals) / len(lazy_vals)) if lazy_vals else None,
        "tool_calls_mean": (sum(tool_vals) / len(tool_vals)) if tool_vals else None,
    }


def rescore_run(run_summary_path: Path, benchmark_jsonl: Path) -> dict[str, Any]:
    """Re-score one run's predictions in place. Returns the new aggregate."""
    bench = _load_benchmark(benchmark_jsonl)
    summary = json.loads(run_summary_path.read_text())

    # Run dir: same stem, sibling dir
    run_dir = run_summary_path.parent / run_summary_path.stem
    pred_dir = run_dir / "predictions"
    if not pred_dir.exists():
        logger.warning("No predictions dir for %s; skipping", run_summary_path)
        return summary

    per_example: list[dict[str, Any]] = []
    for pred_path in sorted(pred_dir.glob("*.json")):
        record = json.loads(pred_path.read_text())
        eid = record.get("example_id")
        if eid not in bench:
            logger.warning("Example %s not in benchmark; skipping", eid)
            continue
        ex = bench[eid]
        # Reuse cached image_dims if recorded; else None (simple-agent path)
        dims = record.get("image_dims_by_page")
        if isinstance(dims, dict):
            dims = {int(k): tuple(v) for k, v in dims.items()}
        else:
            dims = None
        record = _rescore_one(record, ex, dims)
        pred_path.write_text(json.dumps(record, default=str, indent=2))
        per_example.append(record)

    new_overall = _aggregate(per_example)
    old_overall = summary.get("overall", {})
    summary["overall"] = new_overall
    summary["_rescored"] = True
    summary["_old_overall"] = old_overall
    run_summary_path.write_text(json.dumps(summary, default=str, indent=2))

    # Also refresh run_dir/run.json if present (used by stage_aggregate readers)
    run_json = run_dir / "run.json"
    if run_json.exists():
        rj = json.loads(run_json.read_text())
        rj["aggregate"] = {
            **rj.get("aggregate", {}),
            "accuracy": new_overall["accuracy"],
            "abstain_rate": new_overall["abstain_rate"],
            "page_recall": new_overall["page_recall"],
            "bbox_iou": new_overall["bbox_iou"],
            "evidence_reward_mean": new_overall.get("evidence_reward_mean"),
            "lazy_answer_rate": new_overall.get("lazy_answer_rate"),
        }
        rj["_rescored"] = True
        run_json.write_text(json.dumps(rj, default=str, indent=2))

    return new_overall


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "target",
        type=Path,
        help="Either a single run.json (e.g. results/hf/.../*.json) or a directory containing many.",
    )
    parser.add_argument(
        "--benchmark-jsonl",
        type=Path,
        default=Path.home() / ".cache" / "focusparse" / "hf_staging" / "benchmark.jsonl",
        help="Path to staged benchmark.jsonl (default: ~/.cache/focusparse/hf_staging/benchmark.jsonl).",
    )
    args = parser.parse_args()

    if not args.benchmark_jsonl.exists():
        logger.error("benchmark.jsonl not found at %s", args.benchmark_jsonl)
        return 1

    targets: list[Path] = []
    if args.target.is_file():
        targets = [args.target]
    elif args.target.is_dir():
        # All run.json shaped files (top-level *.json with `overall` key)
        for p in sorted(args.target.glob("*.json")):
            if p.name == "matrix_summary.json":
                continue
            try:
                d = json.loads(p.read_text())
                if "overall" in d:
                    targets.append(p)
            except json.JSONDecodeError:
                continue
    if not targets:
        logger.error("No re-score targets found at %s", args.target)
        return 1

    print(f"{'run':60s}  {'old_acc':>8s} → {'new_acc':>8s}  {'old_pr':>8s} → {'new_pr':>8s}")
    for t in targets:
        old = json.loads(t.read_text()).get("overall", {})
        new = rescore_run(t, args.benchmark_jsonl)
        print(
            f"{t.stem:60s}  {old.get('accuracy', 0) * 100:7.1f}% → "
            f"{new['accuracy'] * 100:7.1f}%  "
            f"{old.get('page_recall', 0):7.2f} → {new['page_recall']:7.2f}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
