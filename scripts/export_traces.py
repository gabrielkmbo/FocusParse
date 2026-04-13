"""CLI wrapper for focusparse.traces.export.export_sft_jsonl.

Usage:
    uv run python scripts/export_traces.py results/runs/<ts>/ --out traces.jsonl
"""

from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--out", type=Path, default=Path("traces.jsonl"))
    ap.add_argument("--min-coverage", type=float, default=0.8)
    ap.add_argument("--min-iou", type=float, default=0.3)
    ap.add_argument("--require-correct", action="store_true", default=True)
    ns = ap.parse_args()
    _ = ns
    raise NotImplementedError("export_traces — wire in Phase 6 (after traces are written)")


if __name__ == "__main__":
    main()
