"""60plus sprint helper — print key deltas between a new run and main-stack-run1.

Usage:
    uv run python scripts/_60plus_eval_delta.py <new_run_json_or_dir>

Defaults to the canonical main-stack baseline at
`results/hf/sprint-2026-05-13/main-stack-run1/focusparse_focus_agentic_multi_page_333fe987.json`.
Pass `--baseline <path>` to override.

Prints:
  * overall accuracy delta + per-domain breakdown
  * lazy_answer_rate / bbox_iou / page_recall changes
  * per-example flips (newly correct / newly wrong)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

_DEFAULT_BASELINE = Path(
    "results/hf/sprint-2026-05-13/main-stack-run1/focusparse_focus_agentic_multi_page_333fe987.json"
)


def _resolve_run_path(path: str | Path) -> Path:
    p = Path(path)
    if p.is_dir():
        candidates = sorted(p.glob("focusparse_*.json"))
        if candidates:
            return candidates[0]
    return p


def _load_per_example(run_json_path: Path) -> list[dict]:
    """Find per_example.jsonl next to a run wrapper JSON."""
    # run wrapper: <output>/<config_key>.json. per_example: <output>/<config_key>/per_example.jsonl
    config_key = run_json_path.stem
    per_example = run_json_path.parent / config_key / "per_example.jsonl"
    if not per_example.exists():
        # Maybe the path already pointed at the inner dir
        per_example = run_json_path.parent / "per_example.jsonl"
    if not per_example.exists():
        raise FileNotFoundError(f"per_example.jsonl not found near {run_json_path}")
    return [json.loads(line) for line in per_example.read_text().splitlines() if line.strip()]


def _domain_of(r: dict) -> str:
    d = (r.get("domain") or "").replace("Domain.", "").lower()
    if d:
        return d
    eid = r["example_id"]
    if eid.startswith("dat-"):
        return "datasheet"
    if eid.startswith("fin-"):
        return "finance"
    return "unknown"


def _accuracy(rows: list[dict]) -> tuple[float, int, int]:
    correct = sum(1 for r in rows if r["answer_correct"] >= 0.999)
    return correct / len(rows) if rows else 0.0, correct, len(rows)


def _mean(rows: list[dict], key: str) -> float:
    vals = [r[key] for r in rows if r.get(key) is not None]
    return sum(vals) / len(vals) if vals else 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("new_run", help="path to new run wrapper .json or directory")
    ap.add_argument("--baseline", default=str(_DEFAULT_BASELINE))
    args = ap.parse_args()

    base_path = _resolve_run_path(args.baseline)
    new_path = _resolve_run_path(args.new_run)
    print(f"Baseline: {base_path}")
    print(f"New run : {new_path}")

    base_rows = _load_per_example(base_path)
    new_rows = _load_per_example(new_path)

    print(f"\nBaseline n={len(base_rows)}, New n={len(new_rows)}")

    base_by = {r["example_id"]: r for r in base_rows}
    new_by = {r["example_id"]: r for r in new_rows}
    common = set(base_by) & set(new_by)
    only_new = set(new_by) - set(base_by)
    only_base = set(base_by) - set(new_by)
    print(f"Common: {len(common)}, only_new: {len(only_new)}, only_base: {len(only_base)}")

    # Overall metrics on the new run
    print("\n=== Overall metrics ===")
    ba, bc, bn = _accuracy(base_rows)
    na, nc, nn = _accuracy(new_rows)
    print(f"  Baseline: {bc}/{bn} = {ba * 100:.1f}%")
    print(f"  New     : {nc}/{nn} = {na * 100:.1f}%  Δ={((na - ba) * 100):+.1f}pp")

    print("  page_recall:")
    print(
        f"    base {_mean(base_rows, 'page_recall'):.3f}  new {_mean(new_rows, 'page_recall'):.3f}"
    )
    print("  bbox_iou:")
    print(f"    base {_mean(base_rows, 'bbox_iou'):.3f}  new {_mean(new_rows, 'bbox_iou'):.3f}")
    print("  is_lazy rate:")
    print(f"    base {_mean(base_rows, 'is_lazy'):.3f}  new {_mean(new_rows, 'is_lazy'):.3f}")

    # Per-domain
    print("\n=== Per-domain accuracy ===")
    for dom in ["datasheet", "finance"]:
        b_dom = [r for r in base_rows if _domain_of(r) == dom]
        n_dom = [r for r in new_rows if _domain_of(r) == dom]
        ba, bc, bn = _accuracy(b_dom)
        na, nc, nn = _accuracy(n_dom)
        print(
            f"  {dom}: base {bc}/{bn}={ba * 100:.1f}%  new {nc}/{nn}={na * 100:.1f}%  Δ={((na - ba) * 100):+.1f}pp"
        )

    # Per-example flips
    flipped_to_correct = []
    flipped_to_wrong = []
    for eid in common:
        b = base_by[eid]
        n = new_by[eid]
        if b["answer_correct"] < 0.999 and n["answer_correct"] >= 0.999:
            flipped_to_correct.append((eid, b, n))
        elif b["answer_correct"] >= 0.999 and n["answer_correct"] < 0.999:
            flipped_to_wrong.append((eid, b, n))

    print("\n=== Flips ===")
    print(f"  base wrong → new correct: {len(flipped_to_correct)}")
    print(f"  base correct → new wrong: {len(flipped_to_wrong)}")
    print(f"  net: {len(flipped_to_correct) - len(flipped_to_wrong):+d} examples")

    # Per-domain flips
    for dom in ["datasheet", "finance"]:
        flips_to_correct = sum(1 for eid, b, n in flipped_to_correct if _domain_of(n) == dom)
        flips_to_wrong = sum(1 for eid, b, n in flipped_to_wrong if _domain_of(n) == dom)
        print(f"  {dom}: +{flips_to_correct} / -{flips_to_wrong}")

    if flipped_to_correct:
        print("\n=== Newly correct (sample first 12) ===")
        for eid, b, n in flipped_to_correct[:12]:
            print(
                f"  [{eid[:45]:45}] {_domain_of(n)}  "
                f"pred='{(n.get('answer_pred') or '')[:40]}'  "
                f"gold='{(n.get('answer_gold') or '')[:40]}'"
            )
    if flipped_to_wrong:
        print("\n=== Newly wrong (sample first 12) ===")
        for eid, b, n in flipped_to_wrong[:12]:
            print(
                f"  [{eid[:45]:45}] {_domain_of(n)}  "
                f"prior_pred='{(b.get('answer_pred') or '')[:30]}'  "
                f"now_pred='{(n.get('answer_pred') or '')[:30]}'  "
                f"gold='{(n.get('answer_gold') or '')[:30]}'"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
