"""Run the headline 4-method × 2-task × 2-metric table.

Sweeps the seven method × tool-set combinations that fill the headline
table from `plans/2026-04-29-research-driven-eval-framework.md`:

    | Method                           | Datasheets   | Finance     |
    | -------------------------------- | ------------ | ----------- |
    | Base VLM (no tools)              |              |             |
    | ReAct +2 tools                   |              |             |
    | ReAct +4 tools                   |              |             |
    | Agent baseline +2 tools          |              |             |
    | Agent baseline +4 tools          |              |             |
    | Our harness +2 tools             |              |             |
    | Our harness +4 tools             |              |             |

All methods run at protocol=`agentic_multi_page` (the headline-table
input format). Each spec is a separate subprocess invocation of
`run_hf_eval.py`, so:

  * each spec gets its own deterministic prediction cache
  * `--max-parallel` controls how many specs run concurrently (4 is
    OpenAI-rate-limit-safe at gpt-5.4 based on the prior full-eval run)
  * a single failed spec doesn't abort the others; the merge tolerates
    missing entries

After all specs finish, aggregates per-domain into a single
`headline_table.json` with bootstrap 95% CIs on every cell, ready for
`scripts/render_headline_table.py` to emit markdown / HTML.

Usage:
    uv run python scripts/run_headline_eval.py --output-dir results/hf/headline-v1
    uv run python scripts/run_headline_eval.py --max-parallel 4 --limit 30  # smoke
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_OUTPUT_DIR = Path("results/hf/headline")
_DEFAULT_STAGING = Path.home() / ".cache" / "focusparse" / "hf_staging"
_RUN_EVAL_SCRIPT = Path(__file__).resolve().parent / "run_hf_eval.py"


# The seven specs that fill the headline table. Each becomes a separate
# subprocess call to run_hf_eval.py.
HEADLINE_SPECS: list[dict[str, str]] = [
    {"agent": "simple", "tool_set": "full", "label": "Base VLM"},
    {"agent": "react", "tool_set": "minimal", "label": "ReAct +2 tools"},
    {"agent": "react", "tool_set": "full", "label": "ReAct +4 tools"},
    {"agent": "agent_baseline", "tool_set": "minimal", "label": "Agent baseline +2 tools"},
    {"agent": "agent_baseline", "tool_set": "full", "label": "Agent baseline +4 tools"},
    {"agent": "focus", "tool_set": "minimal", "label": "Our harness +2 tools"},
    {"agent": "focus", "tool_set": "full", "label": "Our harness +4 tools"},
]

_HEADLINE_PROTOCOL = "agentic_multi_page"


def _build_cmd(
    spec: dict[str, str],
    *,
    output_dir: Path,
    staging_dir: Path,
    limit: int | None,
    pdfs_root: Path | None,
    hf_revision: str | None,
    resume: bool,
) -> list[str]:
    cmd: list[str] = [
        sys.executable,
        str(_RUN_EVAL_SCRIPT),
        "--agent",
        spec["agent"],
        "--protocol",
        _HEADLINE_PROTOCOL,
        "--tool-set",
        spec["tool_set"],
        "--output-dir",
        str(output_dir),
        "--staging-dir",
        str(staging_dir),
    ]
    if pdfs_root is not None:
        cmd += ["--pdfs-root", str(pdfs_root)]
    if limit is not None:
        cmd += ["--limit", str(limit)]
    if hf_revision:
        cmd += ["--hf-revision", hf_revision]
    if not resume:
        cmd.append("--no-resume")
    return cmd


def _spec_label(spec: dict[str, str]) -> str:
    return spec["label"]


def _run_one_spec(
    spec: dict[str, str],
    *,
    output_dir: Path,
    staging_dir: Path,
    limit: int | None,
    pdfs_root: Path | None,
    hf_revision: str | None,
    resume: bool,
) -> tuple[dict[str, str], int]:
    """Spawn a subprocess for one spec. Returns (spec, returncode)."""
    cmd = _build_cmd(
        spec,
        output_dir=output_dir,
        staging_dir=staging_dir,
        limit=limit,
        pdfs_root=pdfs_root,
        hf_revision=hf_revision,
        resume=resume,
    )
    logger.info("[%s] $ %s", _spec_label(spec), " ".join(cmd))
    proc = subprocess.run(cmd, check=False)
    return spec, proc.returncode


def _config_key(spec: dict[str, str], tier_sha8: str = "7d4b816d") -> str:
    """Match `run_hf_eval.py`'s deterministic config_key shape.

    Includes a `_t<tool_set>` suffix when tool_set != "full" so the
    +2 / +4 variants of the same agent live in different paths and
    don't overwrite each other's run.json.
    """
    suffix = "" if spec["tool_set"] == "full" else f"_t{spec['tool_set']}"
    return f"focusparse_{spec['agent']}_{_HEADLINE_PROTOCOL}_{tier_sha8}{suffix}"


def _load_run_summary(output_dir: Path, spec: dict[str, str]) -> dict[str, Any] | None:
    """Read the per-spec run.json and aggregate_by_domain block.

    Spec results are keyed by `config_key` (the agent/protocol/tier_sha8
    combo). Tool-set differs across specs but the config_key path is the
    same per `run_hf_eval.py`'s naming, so we read the per-run.json
    INSIDE the run dir and assume the most recent write reflects the
    matching spec. To make this robust, we also pin the spec into
    each run.json's `tool_set` field at write time.
    """
    config_key = _config_key(spec)
    run_dir = output_dir / config_key
    summary_path = run_dir / "run.json"
    if not summary_path.exists():
        # Fall back to the top-level <config_key>.json that
        # run_hf_eval.py writes when it finishes.
        summary_path = output_dir / f"{config_key}.json"
    if not summary_path.exists():
        logger.warning("[%s] no run.json at %s", _spec_label(spec), summary_path)
        return None
    try:
        return json.loads(summary_path.read_text())
    except json.JSONDecodeError as exc:
        logger.warning("[%s] run.json parse failed: %s", _spec_label(spec), exc)
        return None


def _build_headline_table(
    output_dir: Path,
    *,
    specs: list[dict[str, str]],
    started_at_iso: str,
) -> dict[str, Any]:
    """Merge per-spec runs into the canonical headline-table JSON shape.

    Output shape (consumed by `scripts/render_headline_table.py`):
      {
        "generated_at": "...",
        "protocol": "agentic_multi_page",
        "rows": [
          {
            "label": "Base VLM",
            "agent": "simple",
            "tool_set": "full",
            "n_total": 148,
            "by_domain": {
              "datasheet": {"n": 100, "accuracy": 0.50, "accuracy_ci": [.39, .60],
                            "usd_per_correct": 0.011, "usd_per_correct_ci": [.009, .015],
                            "latency_ms_mean": 3200.0,
                            "bbox_iou": 0.38, "page_recall": 0.94},
              "finance":   {...},
              "_overall":  {...}
            }
          },
          ...
        ]
      }
    """
    rows: list[dict[str, Any]] = []
    for spec in specs:
        summary = _load_run_summary(output_dir, spec)
        if summary is None:
            rows.append(
                {
                    "label": spec["label"],
                    "agent": spec["agent"],
                    "tool_set": spec["tool_set"],
                    "missing": True,
                }
            )
            continue
        by_domain = summary.get("aggregate_by_domain") or {}
        rows.append(
            {
                "label": spec["label"],
                "agent": spec["agent"],
                "tool_set": spec["tool_set"],
                "n_total": summary.get("aggregate", {}).get("n", 0),
                "by_domain": {
                    domain: {
                        "n": m.get("n", 0),
                        "accuracy": m.get("accuracy", 0.0),
                        "accuracy_ci": m.get("accuracy_ci") or [0.0, 0.0],
                        "usd_per_correct": m.get("usd_per_correct"),
                        "usd_per_correct_ci": m.get("usd_per_correct_ci"),
                        "latency_ms_mean": m.get("latency_ms_mean", 0.0),
                        "bbox_iou": m.get("bbox_iou_mean", 0.0),
                        "page_recall": m.get("page_recall_mean", 0.0),
                        "usd_total": m.get("usd_total", 0.0),
                    }
                    for domain, m in by_domain.items()
                },
            }
        )

    return {
        "generated_at": started_at_iso,
        "protocol": _HEADLINE_PROTOCOL,
        "specs": specs,
        "rows": rows,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_DEFAULT_OUTPUT_DIR,
        help=f"Run dir for the per-spec subdirs and the merged headline_table.json. Default {_DEFAULT_OUTPUT_DIR}.",
    )
    parser.add_argument(
        "--staging-dir",
        type=Path,
        default=_DEFAULT_STAGING,
        help="HF staging dir (read by run_hf_eval.py).",
    )
    parser.add_argument(
        "--pdfs-root",
        type=Path,
        default=None,
        help="Source PDF dir (required for agentic_multi_page noise rendering and the focus pipeline's FTS router).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap examples per spec. Default: full split (~148).",
    )
    parser.add_argument(
        "--hf-revision",
        default=None,
        help="Pin a specific HF dataset revision SHA.",
    )
    parser.add_argument(
        "--max-parallel",
        type=int,
        default=4,
        help="Number of specs to run concurrently. 4 is OpenAI-rate-limit-safe at gpt-5.4.",
    )
    parser.add_argument(
        "--specs",
        default=None,
        help=(
            "Comma-separated subset of specs to run, by `label` field "
            "(e.g. 'Base VLM,Our harness +4 tools'). Default: all 7."
        ),
    )
    parser.add_argument("--resume", dest="resume", action="store_true", default=True)
    parser.add_argument("--no-resume", dest="resume", action="store_false")
    parser.add_argument(
        "--render",
        action="store_true",
        default=False,
        help="Also call render_headline_table.py to produce markdown after merging.",
    )
    return parser.parse_args()


def _filter_specs(args_specs: str | None) -> list[dict[str, str]]:
    if args_specs is None:
        return list(HEADLINE_SPECS)
    wanted = {s.strip() for s in args_specs.split(",") if s.strip()}
    out = [s for s in HEADLINE_SPECS if s["label"] in wanted]
    if not out:
        raise ValueError(
            f"No specs matched {wanted!r}. Known labels: {[s['label'] for s in HEADLINE_SPECS]}"
        )
    return out


def main() -> int:
    args = _parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    specs = _filter_specs(args.specs)
    started_at = datetime.now(UTC).isoformat()
    logger.info(
        "Running %d spec(s) with --max-parallel %d, --limit %s",
        len(specs),
        args.max_parallel,
        args.limit,
    )

    # Spawn subprocesses with bounded parallelism. Each subprocess prints
    # its own progress to its own stdout — we only collect returncodes
    # here so the orchestrator stays simple.
    failures: list[tuple[dict[str, str], int]] = []
    with ThreadPoolExecutor(max_workers=max(1, args.max_parallel)) as executor:
        futures = {
            executor.submit(
                _run_one_spec,
                spec,
                output_dir=args.output_dir,
                staging_dir=args.staging_dir,
                limit=args.limit,
                pdfs_root=args.pdfs_root,
                hf_revision=args.hf_revision,
                resume=args.resume,
            ): spec
            for spec in specs
        }
        for fut in as_completed(futures):
            spec, returncode = fut.result()
            if returncode != 0:
                failures.append((spec, returncode))
                logger.warning("[%s] FAILED with rc=%d", _spec_label(spec), returncode)
            else:
                logger.info("[%s] OK", _spec_label(spec))

    if failures:
        logger.warning("%d / %d specs failed; merging the rest anyway.", len(failures), len(specs))

    table = _build_headline_table(args.output_dir, specs=specs, started_at_iso=started_at)
    out_path = args.output_dir / "headline_table.json"
    out_path.write_text(json.dumps(table, default=str, indent=2))
    logger.info("Wrote %s", out_path)

    # Print a quick summary so the wall-time-watcher sees the headline.
    _print_summary(table)

    if args.render:
        renderer = Path(__file__).resolve().parent / "render_headline_table.py"
        if renderer.exists():
            subprocess.run([sys.executable, str(renderer), str(out_path)], check=False)

    return 1 if failures else 0


def _print_summary(table: dict[str, Any]) -> None:
    print()
    print(f"{'Method':30s} {'Datasheet acc':>15s} {'Finance acc':>15s} {'$/correct':>12s}")
    print("-" * 80)
    for row in table.get("rows", []):
        if row.get("missing"):
            print(f"{row['label']:30s}  (missing)")
            continue
        ds = row.get("by_domain", {}).get("datasheet") or {}
        fn = row.get("by_domain", {}).get("finance") or {}
        overall = row.get("by_domain", {}).get("_overall") or {}
        ds_acc = (ds.get("accuracy") or 0.0) * 100
        fn_acc = (fn.get("accuracy") or 0.0) * 100
        cpc = overall.get("usd_per_correct")
        cpc_str = f"${cpc:.4f}" if cpc is not None else "n/a"
        print(f"{row['label']:30s} {ds_acc:14.1f}% {fn_acc:14.1f}% {cpc_str:>12s}")


if __name__ == "__main__":
    sys.exit(main())
