"""Sweep FocusParse configs against the HF parser-bench validation split.

Phase A (default): simple × {full_doc, oracle_page, oracle_crop}  — 3 runs
Phase B:           focus  × {cheap_only, balanced, frontier}      — 3 runs

Shells out to `scripts/run_hf_eval.py` per cell (one subprocess each) so each
cell gets its own prediction cache, its own deterministic filename, and any
tier overrides apply cleanly. Merges per-cell JSONs into a single
`results/hf/matrix_summary.json` in parser-bench shape — re-running `--phase a`
after `--phase b` yields one file with all configs (existing keys preserved).

    uv run python scripts/run_hf_matrix.py --phase a
    uv run python scripts/run_hf_matrix.py --phase b --focus-tiers balanced,frontier
    uv run python scripts/run_hf_matrix.py --phase a --phase b  # sequential
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_OUTPUT_DIR = Path("results/hf")
_DEFAULT_STAGING = Path.home() / ".cache" / "focusparse" / "hf_staging"
_RUN_EVAL_SCRIPT = Path(__file__).resolve().parent / "run_hf_eval.py"

_PHASE_A_PROTOCOLS = ("full_doc", "oracle_page", "oracle_crop")

# Tier profiles for Phase B. Each value is a {role: tier} dict that gets turned
# into repeated --tier-override args. `balanced` is the config default (no
# overrides applied).
_TIER_PROFILES: dict[str, dict[str, str]] = {
    "cheap_only": {
        "planner": "cheap",
        "router": "cheap",
        "localizer_rerank": "cheap",
        "reasoner": "cheap",
        "verifier": "cheap",
    },
    "balanced": {},
    "frontier": {
        "planner": "frontier",
        "router": "frontier",
        "localizer_rerank": "frontier",
        "reasoner": "frontier",
        "verifier": "frontier",
    },
}


def main() -> int:
    args = _parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    out_root: Path = args.output_dir
    out_root.mkdir(parents=True, exist_ok=True)
    summary_path = out_root / "matrix_summary.json"

    run_specs = _build_specs(
        phases=args.phase,
        focus_tiers=args.focus_tiers,
    )
    if not run_specs:
        logger.error("No specs to run — did you pass --phase?")
        return 2

    logger.info("Matrix: %d run(s) queued", len(run_specs))
    for spec in run_specs:
        logger.info("  - %s", _spec_label(spec))

    # Run each cell. Each subprocess writes `<output_dir>/focusparse_<agent>_<protocol>_<sha>.json`.
    for spec in run_specs:
        cmd = _build_cmd(
            spec,
            output_dir=out_root,
            staging_dir=args.staging_dir,
            limit=args.limit,
            hf_revision=args.hf_revision,
            resume=args.resume,
        )
        logger.info("$ %s", " ".join(str(c) for c in cmd))
        subprocess.run(cmd, check=True)

    # Merge per-cell JSONs into the summary. Load existing file first so we
    # preserve rows from earlier --phase invocations.
    summary = _load_or_init_summary(
        summary_path,
        hf_revision=args.hf_revision,
        limit=args.limit,
    )

    for spec in run_specs:
        cell_json = _find_cell_json(out_root, spec)
        if cell_json is None:
            logger.warning("No cell JSON found for %s — skipping merge.", _spec_label(spec))
            continue
        data = json.loads(cell_json.read_text())
        _merge_cell(summary, data, tier_profile=spec.get("tier_profile"))

    summary["generated_at"] = datetime.now(UTC).isoformat()
    summary_path.write_text(json.dumps(summary, indent=2))
    logger.info("Wrote %s", summary_path)
    _print_summary(summary)
    return 0


# ---------------------------------------------------------------------------
# argparse
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase",
        action="append",
        choices=["a", "b"],
        default=[],
        help="Repeatable. `a` = simple × 3 protocols, `b` = focus × tier profiles.",
    )
    parser.add_argument(
        "--focus-tiers",
        default="balanced",
        help=(
            "Comma-separated subset of {cheap_only, balanced, frontier}. "
            "Only consulted when --phase b is selected."
        ),
    )
    parser.add_argument("--hf-revision", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--staging-dir", type=Path, default=_DEFAULT_STAGING)
    parser.add_argument("--output-dir", type=Path, default=_DEFAULT_OUTPUT_DIR)
    parser.add_argument("--resume", dest="resume", action="store_true", default=True)
    parser.add_argument("--no-resume", dest="resume", action="store_false")
    args = parser.parse_args()
    if not args.phase:
        args.phase = ["a"]
    return args


# ---------------------------------------------------------------------------
# Spec building + cmd shaping
# ---------------------------------------------------------------------------


def _build_specs(*, phases: list[str], focus_tiers: str) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    if "a" in phases:
        for protocol in _PHASE_A_PROTOCOLS:
            specs.append({"agent": "simple", "protocol": protocol})
    if "b" in phases:
        requested = [t.strip() for t in focus_tiers.split(",") if t.strip()]
        for profile in requested:
            if profile not in _TIER_PROFILES:
                raise ValueError(
                    f"Unknown tier profile {profile!r}; choose from {sorted(_TIER_PROFILES)}"
                )
            specs.append(
                {
                    "agent": "focus",
                    "protocol": "focus_default",
                    "tier_profile": profile,
                }
            )
    return specs


def _build_cmd(
    spec: dict[str, Any],
    *,
    output_dir: Path,
    staging_dir: Path,
    limit: int | None,
    hf_revision: str | None,
    resume: bool,
) -> list[str]:
    cmd: list[str] = [
        sys.executable,
        str(_RUN_EVAL_SCRIPT),
        "--agent",
        spec["agent"],
        "--protocol",
        spec["protocol"],
        "--output-dir",
        str(output_dir),
        "--staging-dir",
        str(staging_dir),
    ]
    if limit is not None:
        cmd += ["--limit", str(limit)]
    if hf_revision:
        cmd += ["--hf-revision", hf_revision]
    if not resume:
        cmd.append("--no-resume")
    profile = spec.get("tier_profile")
    if profile:
        for role, tier in _TIER_PROFILES[profile].items():
            cmd += ["--tier-override", f"{role}={tier}"]
    return cmd


def _spec_label(spec: dict[str, Any]) -> str:
    profile = spec.get("tier_profile")
    if profile:
        return f"{spec['agent']}/{spec['protocol']}/{profile}"
    return f"{spec['agent']}/{spec['protocol']}"


# ---------------------------------------------------------------------------
# Merge logic — pure, unit-testable
# ---------------------------------------------------------------------------


def _load_or_init_summary(
    summary_path: Path,
    *,
    hf_revision: str | None,
    limit: int | None,
) -> dict[str, Any]:
    if summary_path.exists():
        return json.loads(summary_path.read_text())
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "hf_repo": "gabrielbo/parser-bench",
        "hf_split": "validation",
        "hf_revision": hf_revision or "HEAD",
        "dataset_fingerprint": None,
        "limit": limit,
        "results": {},
    }


def _build_group_key(*, agent: str, tier_sha8: str, tier_profile: str | None) -> str:
    """Top-level key under which protocol rows nest.

    Simple runs share a tier_sha8 across protocols, so 3 protocols collapse to
    one group. Focus runs with a profile embed the profile name for readability
    (the tier_sha8 alone would disambiguate, but the label helps humans)."""
    if tier_profile:
        return f"focusparse_{agent}_{tier_profile}_{tier_sha8}"
    return f"focusparse_{agent}_{tier_sha8}"


def _extract_cell(overall: dict[str, Any]) -> dict[str, Any]:
    """Flatten `EvalRunResults.overall` into the matrix cell shape.

    Mirrors parser-bench's per-protocol dict exactly; FocusParse-specific keys
    (evidence_reward_mean etc.) are dropped when null so simple rows stay
    visually identical to parser-bench rows."""
    cell = {
        "accuracy": overall["accuracy"],
        "abstain_rate": overall["abstain_rate"],
        "page_recall": overall["page_recall"],
        "bbox_iou": overall["bbox_iou"],
        "count": overall["count"],
        "total_cost_usd": overall.get("total_cost_usd"),
        "cost_per_correct_usd": overall.get("cost_per_correct_usd"),
        "total_input_tokens": overall.get("total_input_tokens", 0),
        "total_output_tokens": overall.get("total_output_tokens", 0),
    }
    for focus_key in ("evidence_reward_mean", "lazy_answer_rate", "tool_calls_mean"):
        val = overall.get(focus_key)
        if val is not None:
            cell[focus_key] = val
    return cell


def _merge_cell(
    summary: dict[str, Any],
    data: dict[str, Any],
    *,
    tier_profile: str | None,
) -> None:
    """Merge one `EvalRunResults` JSON into the matrix summary.

    Preserves existing protocol entries under the same group_key (so
    re-running `--phase a` after `--phase b` doesn't clobber phase-b rows).
    Stamps `dataset_fingerprint` exactly once."""
    group_key = _build_group_key(
        agent=data["agent"],
        tier_sha8=data["tier_sha8"],
        tier_profile=tier_profile,
    )
    cell = _extract_cell(data["overall"])
    summary["results"].setdefault(group_key, {})[data["protocol"]] = cell
    if summary.get("dataset_fingerprint") in (None, {}):
        summary["dataset_fingerprint"] = data.get("dataset_fingerprint")


def _find_cell_json(out_root: Path, spec: dict[str, Any]) -> Path | None:
    """Locate the JSON produced by `run_hf_eval.py` for this spec.

    We can't predict `tier_sha8` without importing the config machinery here,
    so we glob on (agent, protocol) and pick the newest match. Subprocess runs
    are sequential, so the newest mtime is unambiguously the one we just
    triggered. (When the prediction cache hits on a resume, the JSON is
    rewritten with a fresh mtime, so this still holds.)"""
    pattern = f"focusparse_{spec['agent']}_{spec['protocol']}_*.json"
    candidates = sorted(
        (p for p in out_root.glob(pattern) if p.name != "matrix_summary.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _print_summary(summary: dict[str, Any]) -> None:
    print("\n== Matrix summary ==")
    for group_key, protocols in summary.get("results", {}).items():
        print(f"  {group_key}:")
        for proto, cell in protocols.items():
            cost = cell.get("total_cost_usd") or 0.0
            per = cell.get("cost_per_correct_usd") or 0.0
            print(
                f"    {proto}: accuracy={cell['accuracy']:.1%} "
                f"n={cell['count']} cost=${cost:.2f} (${per:.3f}/correct)"
            )


if __name__ == "__main__":
    sys.exit(main())
