"""Evaluation harness — runs a workflow across a benchmark slice.

TODO(Phase 1 final): wire `simple` agent path (single-shot backend call per
example) + scoring + metrics + cache of predictions. Matches parser-bench's
`SimpleAgent` behavior on `full_doc | oracle_page | oracle_crop`.

TODO(Phase 2): wire `focus` agent (FocusWorkflow) path with trajectory capture.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from focusparse._parser_bench import BenchmarkExample


async def run_simple_eval(
    examples: Iterable[BenchmarkExample],
    *,
    backend: str,
    model: str,
    protocol: str,
    output_dir: Path,
    limit: int | None = None,
) -> dict[str, Any]:
    """Single-shot baseline. TODO: wire real backend calls."""
    raise NotImplementedError("run_simple_eval — wire in Phase 1 final commit")


async def run_focus_eval(
    examples: Iterable[BenchmarkExample],
    *,
    tier_profile: str,
    budget: dict[str, int],
    output_dir: Path,
    limit: int | None = None,
    export_traces: Path | None = None,
) -> dict[str, Any]:
    """Lens-workflow eval. TODO: wire in Phase 2."""
    raise NotImplementedError("run_focus_eval — wire in Phase 2")
