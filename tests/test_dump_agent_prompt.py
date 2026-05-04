"""Smoke test for `scripts/dump_agent_prompt.py`."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(args: list[str]) -> str:
    proc = subprocess.run(
        [sys.executable, "scripts/dump_agent_prompt.py", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return proc.stdout


def test_careful_full_dump_contains_all_required_sections() -> None:
    out = _run(["--tool-set", "full", "--mode", "careful"])
    for marker in (
        "### inspect_region",
        "### get_text_layer",
        "### layout_detect",
        "### run_python",
        "Inputs:",
        "Returns:",
        "Chains with:",
        "Example call:",
    ):
        assert marker in out, f"missing {marker!r} in dumped prompt"


def test_generic_minimal_dump_is_terse() -> None:
    out = _run(["--tool-set", "minimal", "--mode", "generic"])
    assert "Available tools:" in out
    # Generic mode never includes the careful sections.
    assert "Returns:" not in out
    assert "Chains with:" not in out
    # Minimal tool set excludes layout_detect and run_python.
    assert "layout_detect" not in out
    assert "run_python" not in out


def test_default_arguments() -> None:
    """Running with no flags = full + careful (the LLM-driven default)."""
    out = _run([])
    assert "Chains with:" in out
    assert "### run_python" in out
