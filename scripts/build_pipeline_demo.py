#!/usr/bin/env python3
"""Build the static FocusParse pipeline explainer demo."""

from __future__ import annotations

import argparse
from pathlib import Path

from focusparse.traces.pipeline_demo import (
    DEFAULT_BENCHMARK_JSONL,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_SPEC_DIR,
    build_pipeline_demo,
)
from focusparse.traces.viewer import DEFAULT_STAGING_ROOT


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--spec-dir",
        type=Path,
        default=DEFAULT_SPEC_DIR,
        help="FocusParse run directory containing per_example.jsonl or predictions/.",
    )
    parser.add_argument(
        "--benchmark-jsonl",
        type=Path,
        default=DEFAULT_BENCHMARK_JSONL,
        help="Benchmark/audit JSONL with exact question text and gold boxes.",
    )
    parser.add_argument(
        "--staging-root",
        type=Path,
        default=DEFAULT_STAGING_ROOT,
        help="Current FocusParse HF staging root with processed page PNGs.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Static bundle output directory.",
    )
    parser.add_argument(
        "--example-id",
        action="append",
        dest="example_ids",
        help="Repeatable override. May be supplied more than once.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Limit selected examples.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = build_pipeline_demo(
        spec_dir=args.spec_dir,
        benchmark_jsonl=args.benchmark_jsonl,
        staging_root=args.staging_root,
        output_dir=args.output_dir,
        example_ids=args.example_ids,
        limit=args.limit,
    )
    print(
        f"Wrote {result.example_count} example(s) and {result.asset_count} asset(s) "
        f"to {result.output_dir}"
    )


if __name__ == "__main__":
    main()
