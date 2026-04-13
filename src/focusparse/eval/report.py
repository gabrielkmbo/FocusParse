"""HTML report generator.

TODO(Phase 4): per-example pages with gold/predicted/inspected bbox overlays,
trajectory table, top-level aggregate index.
"""

from __future__ import annotations

from pathlib import Path


def render_run_report(run_dir: Path) -> Path:
    """Render an HTML report for a completed run. Returns the path to index.html."""
    raise NotImplementedError("render_run_report — wire in Phase 4")
