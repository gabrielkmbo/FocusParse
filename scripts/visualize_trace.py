"""Render one prediction's trace into a single self-contained HTML file.

Usage:

    uv run python scripts/visualize_trace.py \\
        --spec-dir results/hf/headline-v1/focusparse_focus_agentic_multi_page_7d4b816d \\
        --example-id dat-AN040_EN-0008 \\
        --output results/trace_viewer/dat-AN040_EN-0008/focus_full.html

The output file is openable from `file://` and inlines all crops as base64.
The only external request is Tailwind CDN.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from focusparse.traces.viewer import (
    DEFAULT_STAGING_ROOT,
    build_view_model,
    render_html,
)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--spec-dir", type=Path, required=True, help="Spec dir with predictions/")
    ap.add_argument("--example-id", type=str, required=True)
    ap.add_argument("--output", type=Path, required=True, help="HTML output path")
    ap.add_argument(
        "--staging-root",
        type=Path,
        default=DEFAULT_STAGING_ROOT,
        help="HF staging root (for page-image lookup)",
    )
    ap.add_argument(
        "--cache-dir",
        type=Path,
        action="append",
        default=None,
        help="Additional crop search dir (repeat for multiple)",
    )
    args = ap.parse_args()

    pred_path = args.spec_dir / "predictions" / f"{args.example_id}.json"
    if not pred_path.is_file():
        raise SystemExit(f"prediction not found: {pred_path}")
    record = json.loads(pred_path.read_text())

    search_dirs = [
        args.spec_dir / "crops",
        args.spec_dir / "tiles",
        Path("cache/crops"),
    ]
    if args.cache_dir:
        search_dirs.extend(args.cache_dir)

    view = build_view_model(record, search_dirs=search_dirs, staging_root=args.staging_root)
    title = f"Trace · {args.example_id} · {args.spec_dir.name}"
    html_str = render_html(view, title=title)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html_str)
    print(f"wrote {args.output} ({args.output.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
