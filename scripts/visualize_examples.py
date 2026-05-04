"""Pick 4 example IDs spanning failure modes and emit per-spec trace HTMLs.

Failure-mode buckets, picked deterministically (seed=42) from the headline
predictions:

  1. correct_by_focus_only  — Our harness +4 correct, Base VLM wrong
  2. correct_by_base_only   — Base VLM correct, Our harness +4 wrong
  3. correct_by_react_not_base — ReAct +4 correct, Base VLM wrong (rare;
     skipped if no example matches)
  4. wrong_by_everyone      — All 7 specs wrong

For each picked ID, emits 7 HTML files (one per spec) plus an `index.html`
that links them in a 4-row × 7-col grid.

Usage:

    uv run python scripts/visualize_examples.py \\
        --headline-dir results/hf/headline-v1 \\
        --output-dir results/trace_viewer/
"""

from __future__ import annotations

import argparse
import json
import random
import re
from collections.abc import Iterable
from pathlib import Path

from focusparse.traces.viewer import (
    DEFAULT_STAGING_ROOT,
    build_view_model,
    render_html,
)

# Spec ID matchers. The headline-eval orchestrator names dirs as
# `focusparse_<agent>_<protocol>_<config_sha>[_t<tool_set>]`.
SPEC_KEYS: dict[str, re.Pattern[str]] = {
    "simple": re.compile(r"focusparse_simple_"),
    "react_2": re.compile(r"focusparse_react_.*_tminimal$"),
    "react_4": re.compile(r"focusparse_react_(?!.*_tminimal).*"),
    "agent_baseline_2": re.compile(r"focusparse_agent_baseline_.*_tminimal$"),
    "agent_baseline_4": re.compile(r"focusparse_agent_baseline_(?!.*_tminimal).*"),
    "focus_2": re.compile(r"focusparse_focus_.*_tminimal$"),
    "focus_4": re.compile(r"focusparse_focus_(?!.*_tminimal).*"),
}

# Display labels matching headline_table.md.
SPEC_LABELS = {
    "simple": "Base VLM",
    "react_2": "ReAct +2",
    "react_4": "ReAct +4",
    "agent_baseline_2": "Agent baseline +2",
    "agent_baseline_4": "Agent baseline +4",
    "focus_2": "Our harness +2",
    "focus_4": "Our harness +4",
}

BUCKETS = [
    "correct_by_focus_only",
    "correct_by_base_only",
    "correct_by_react_not_base",
    "wrong_by_everyone",
]


# ---------------------------------------------------------------------------
# Discovery + picking
# ---------------------------------------------------------------------------


def discover_specs(headline_dir: Path) -> dict[str, Path]:
    """Map spec key (`simple`, `react_4`, …) → spec dir.

    Walks immediate children of `headline_dir`. Each child must have a
    `predictions/` subdir to qualify. Names that match multiple regexes
    keep the first hit; unmatched dirs are silently skipped.
    """
    out: dict[str, Path] = {}
    if not headline_dir.is_dir():
        return out
    for child in sorted(headline_dir.iterdir()):
        if not child.is_dir() or not (child / "predictions").is_dir():
            continue
        for key, pattern in SPEC_KEYS.items():
            if key in out:
                continue
            if pattern.search(child.name):
                out[key] = child
                break
    return out


def load_correctness(spec_dir: Path) -> dict[str, float]:
    """Read `per_example.jsonl` and return {example_id: answer_correct}.

    Falls back to walking `predictions/*.json` when the JSONL doesn't exist
    (older runs).
    """
    correctness: dict[str, float] = {}
    jsonl = spec_dir / "per_example.jsonl"
    if jsonl.is_file():
        for line in jsonl.read_text().splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            eid = row.get("example_id")
            if eid:
                correctness[eid] = float(row.get("answer_correct") or 0.0)
        return correctness
    pred_dir = spec_dir / "predictions"
    for path in pred_dir.glob("*.json"):
        try:
            row = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        eid = row.get("example_id") or path.stem
        correctness[eid] = float(row.get("answer_correct") or 0.0)
    return correctness


def pick_examples(
    correctness_by_spec: dict[str, dict[str, float]],
    *,
    seed: int = 42,
) -> dict[str, str | None]:
    """Pick one example_id per failure-mode bucket. None if no candidate.

    Selection prefers domain coverage where possible: when a bucket has
    multiple candidates, prefer one with `dat-` prefix on odd-bucket-index
    and `fin-` on even (gives at least one of each across buckets when
    available).
    """
    rng = random.Random(seed)
    base = correctness_by_spec.get("simple") or {}
    focus_4 = correctness_by_spec.get("focus_4") or {}
    react_4 = correctness_by_spec.get("react_4") or {}

    all_specs_correctness = correctness_by_spec.values()

    candidates: dict[str, list[str]] = {b: [] for b in BUCKETS}
    universe = set()
    for d in [base, focus_4, react_4, *all_specs_correctness]:
        universe |= set(d.keys())

    for eid in sorted(universe):
        b = base.get(eid, 0.0) >= 1.0
        f = focus_4.get(eid, 0.0) >= 1.0
        r = react_4.get(eid, 0.0) >= 1.0
        all_wrong = all(d.get(eid, 0.0) < 1.0 for d in all_specs_correctness)

        if f and not b:
            candidates["correct_by_focus_only"].append(eid)
        if b and not f:
            candidates["correct_by_base_only"].append(eid)
        if r and not b:
            candidates["correct_by_react_not_base"].append(eid)
        if all_wrong:
            candidates["wrong_by_everyone"].append(eid)

    picked: dict[str, str | None] = {}
    for i, bucket in enumerate(BUCKETS):
        pool = candidates[bucket]
        if not pool:
            picked[bucket] = None
            continue
        # Prefer domain coverage: alternating bias.
        prefix_pref = "dat-" if i % 2 == 0 else "fin-"
        preferred = [x for x in pool if x.startswith(prefix_pref)]
        chosen_pool = preferred or pool
        picked[bucket] = rng.choice(sorted(chosen_pool))
    return picked


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_one(
    spec_dir: Path,
    example_id: str,
    output_path: Path,
    *,
    extra_search_dirs: Iterable[Path] = (),
    staging_root: Path = DEFAULT_STAGING_ROOT,
) -> bool:
    """Render one (spec, example) HTML. Return True on success."""
    pred_path = spec_dir / "predictions" / f"{example_id}.json"
    if not pred_path.is_file():
        return False
    record = json.loads(pred_path.read_text())
    search_dirs = [
        spec_dir / "crops",
        spec_dir / "tiles",
        Path("cache/crops"),
        *extra_search_dirs,
    ]
    view = build_view_model(record, search_dirs=search_dirs, staging_root=staging_root)
    html_str = render_html(view, title=f"{example_id} · {spec_dir.name}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_str)
    return True


def render_index(
    picks: dict[str, str | None],
    specs: dict[str, Path],
    correctness_by_spec: dict[str, dict[str, float]],
    output_path: Path,
) -> None:
    """Emit a 4-row × 7-col grid linking every (bucket, spec) cell."""
    rows = []
    rows.append("<!DOCTYPE html>")
    rows.append('<html lang="en"><head><meta charset="UTF-8">')
    rows.append("<title>Trace viewer index</title>")
    rows.append('<script src="https://cdn.tailwindcss.com"></script>')
    rows.append('</head><body class="bg-slate-50 p-6 max-w-7xl mx-auto">')
    rows.append('<h1 class="text-2xl font-bold mb-4">Trace viewer · headline-v1</h1>')
    rows.append(
        '<p class="text-sm text-slate-600 mb-6">'
        "4 example IDs spanning failure modes × 7 specs. ✓ = correct, ✗ = wrong."
        "</p>"
    )
    rows.append('<table class="w-full text-sm bg-white rounded shadow overflow-hidden">')
    rows.append('<thead class="bg-slate-100">')
    rows.append("<tr>")
    rows.append('<th class="text-left p-2">bucket</th>')
    rows.append('<th class="text-left p-2">example_id</th>')
    for key in [
        "simple",
        "react_2",
        "react_4",
        "agent_baseline_2",
        "agent_baseline_4",
        "focus_2",
        "focus_4",
    ]:
        rows.append(f'<th class="text-left p-2">{SPEC_LABELS[key]}</th>')
    rows.append("</tr></thead><tbody>")

    for bucket, example_id in picks.items():
        rows.append('<tr class="border-t">')
        rows.append(f'<td class="p-2 font-medium">{bucket}</td>')
        if example_id is None:
            rows.append(
                '<td colspan="9" class="p-2 italic text-slate-500">no candidate in this bucket</td>'
            )
            rows.append("</tr>")
            continue
        rows.append(f'<td class="p-2 font-mono text-xs">{example_id}</td>')
        for key in [
            "simple",
            "react_2",
            "react_4",
            "agent_baseline_2",
            "agent_baseline_4",
            "focus_2",
            "focus_4",
        ]:
            href = f"./{bucket}_{example_id}/{key}.html"
            spec_correct = (correctness_by_spec.get(key) or {}).get(example_id, 0.0)
            mark = "✓" if spec_correct >= 1.0 else "✗"
            color = "text-emerald-600" if spec_correct >= 1.0 else "text-red-600"
            available = key in specs
            if available:
                rows.append(
                    f'<td class="p-2"><a class="underline {color}" href="{href}">'
                    f"{mark} open</a></td>"
                )
            else:
                rows.append('<td class="p-2 text-slate-400">—</td>')
        rows.append("</tr>")

    rows.append("</tbody></table></body></html>")
    output_path.write_text("\n".join(rows))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--headline-dir", type=Path, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--staging-root", type=Path, default=DEFAULT_STAGING_ROOT)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    specs = discover_specs(args.headline_dir)
    if not specs:
        raise SystemExit(f"no specs with predictions/ found under {args.headline_dir}")

    correctness_by_spec = {key: load_correctness(spec_dir) for key, spec_dir in specs.items()}
    picks = pick_examples(correctness_by_spec, seed=args.seed)

    args.output_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    for bucket, example_id in picks.items():
        if example_id is None:
            print(f"  [{bucket}] no candidate, skipping")
            continue
        bucket_dir = args.output_dir / f"{bucket}_{example_id}"
        for key, spec_dir in specs.items():
            out = bucket_dir / f"{key}.html"
            ok = render_one(
                spec_dir,
                example_id,
                out,
                staging_root=args.staging_root,
            )
            if ok:
                written += 1
            else:
                print(f"  [{bucket}/{key}] no prediction for {example_id}")
        print(f"  [{bucket}] -> {bucket_dir}")

    render_index(picks, specs, correctness_by_spec, args.output_dir / "index.html")
    print(f"wrote {written} viewer HTMLs + index.html under {args.output_dir}")


if __name__ == "__main__":
    main()
