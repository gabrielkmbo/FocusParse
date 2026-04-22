"""Reproduce parser-bench's published single-shot baselines.

Runs `focus eval --agent simple` across {gemini-3.1-pro-preview, claude-opus-4-6,
gpt-5.4} × {full_doc, oracle_page, oracle_crop} on the dev split, then diffs
aggregate accuracy against a pinned baseline JSON.

Pinned baseline:
    results/baselines/pinned.json

Schema (matches what this script writes as `current` on each run):
    {
      "as_of": "2026-04-22",
      "split": "dev",
      "limit": 30,
      "cells": {
        "<backend>:<model>:<protocol>": {"accuracy": 0.42, "n": 30},
        ...
      }
    }

A PR that breaks the ±1 pt gate must update the pinned JSON and explain why
in the PR body.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

_DEFAULT_MATRIX: list[tuple[str, str]] = [
    ("gemini", "gemini-3.1-pro-preview"),
    ("openai", "gpt-5.4"),
    ("anthropic", "claude-opus-4-6"),
]
_PROTOCOLS = ("full_doc", "oracle_page", "oracle_crop")
_PINNED_PATH = Path("results/baselines/pinned.json")
_DEFAULT_LIMIT = 30
_TOLERANCE_PT = 1.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", default="dev")
    parser.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)
    parser.add_argument(
        "--hf-staging",
        type=Path,
        default=Path.home() / ".cache" / "focusparse" / "hf_staging",
        help="HF staging root (passed through to run_simple_eval).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("results/baselines"),
        help="Where to write per-cell run dirs + reproduce_<date>.json.",
    )
    parser.add_argument(
        "--pinned",
        type=Path,
        default=_PINNED_PATH,
        help="Pinned baseline JSON to diff against. Missing file → write as new pin.",
    )
    parser.add_argument(
        "--tolerance-pt",
        type=float,
        default=_TOLERANCE_PT,
        help="Accuracy tolerance in percentage points.",
    )
    parser.add_argument(
        "--update-pin",
        action="store_true",
        help="Overwrite the pinned JSON with current run (use in PRs that intentionally drift).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the matrix + exit without calling any APIs.",
    )
    args = parser.parse_args()

    if args.dry_run:
        print("Would run the matrix:")
        for backend, model in _DEFAULT_MATRIX:
            for protocol in _PROTOCOLS:
                print(f"  - {backend}:{model} · {protocol}")
        return 0

    args.output_dir.mkdir(parents=True, exist_ok=True)
    current = asyncio.run(_run_matrix(args))

    current_path = args.output_dir / f"reproduce_{date.today().isoformat()}.json"
    current_path.write_text(json.dumps(current, indent=2, default=str))
    print(f"\nWrote {current_path}")

    if args.update_pin:
        args.pinned.parent.mkdir(parents=True, exist_ok=True)
        args.pinned.write_text(json.dumps(current, indent=2, default=str))
        print(f"Updated pin: {args.pinned}")
        return 0

    if not args.pinned.exists():
        print(
            f"\n[warn] No pinned baseline at {args.pinned}. Re-run with --update-pin to create it."
        )
        return 0

    pinned = json.loads(args.pinned.read_text())
    return _diff_and_report(current, pinned, tolerance_pt=args.tolerance_pt)


async def _run_matrix(args: argparse.Namespace) -> dict[str, Any]:
    # Defer imports so --dry-run works without heavy deps.
    from focusparse.eval.harness import run_simple_eval
    from focusparse.eval.hf_loader import materialize_split
    from focusparse.models.anthropic import AnthropicClient
    from focusparse.models.gemini import GeminiClient
    from focusparse.models.openai import OpenAIClient

    split_name = "validation" if args.split in ("test", "holdout") else args.split
    jsonl_path, _ = materialize_split(args.hf_staging, split=split_name, limit=args.limit)
    images_root = args.hf_staging

    cells: dict[str, dict[str, Any]] = {}
    for backend, model in _DEFAULT_MATRIX:
        if backend == "gemini":
            client = GeminiClient(model=model)
        elif backend == "openai":
            client = OpenAIClient(model=model)
        elif backend == "anthropic":
            client = AnthropicClient(model=model)
        else:
            raise ValueError(f"Unknown backend: {backend}")

        for protocol in _PROTOCOLS:
            cell_key = f"{backend}:{model}:{protocol}"
            cell_run_dir = args.output_dir / cell_key.replace("/", "_").replace(":", "_")
            print(f"\n=== {cell_key} ===")

            from focusparse._parser_bench import BenchmarkExample

            examples = (
                BenchmarkExample.model_validate_json(line)
                for line in jsonl_path.read_text().splitlines()
                if line.strip()
            )
            try:
                result = await run_simple_eval(
                    examples,
                    backend_client=client,
                    backend=backend,
                    model=model,
                    protocol=protocol,
                    output_dir=cell_run_dir,
                    images_root=images_root,
                    limit=args.limit,
                    resume=True,
                )
                agg = result["aggregate"]
                cells[cell_key] = {"accuracy": agg.accuracy, "n": agg.n}
                print(f"  accuracy={agg.accuracy:.3f} n={agg.n}")
            except Exception as exc:
                print(f"  [skip] {exc}")
                cells[cell_key] = {"error": str(exc)}

    return {
        "as_of": date.today().isoformat(),
        "split": args.split,
        "limit": args.limit,
        "cells": cells,
    }


def _diff_and_report(
    current: dict[str, Any],
    pinned: dict[str, Any],
    *,
    tolerance_pt: float,
) -> int:
    print("\n== Baseline diff ==")
    failures: list[str] = []
    for cell_key, pinned_cell in pinned.get("cells", {}).items():
        current_cell = current.get("cells", {}).get(cell_key)
        if current_cell is None or "error" in current_cell:
            print(f"  {cell_key}: [skipped or errored]")
            continue
        pinned_acc = float(pinned_cell.get("accuracy", 0.0))
        current_acc = float(current_cell.get("accuracy", 0.0))
        delta_pt = (current_acc - pinned_acc) * 100.0
        flag = ""
        if abs(delta_pt) > tolerance_pt:
            failures.append(cell_key)
            flag = "  [FAIL]"
        print(
            f"  {cell_key}: pinned={pinned_acc:.3f} current={current_acc:.3f} "
            f"Δ={delta_pt:+.2f}pt{flag}"
        )
    if failures:
        print(f"\n[fail] {len(failures)} cell(s) outside ±{tolerance_pt}pt: {failures}")
        return 1
    print(f"\n[ok] All cells within ±{tolerance_pt}pt of pinned baseline.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
