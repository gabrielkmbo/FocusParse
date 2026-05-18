"""Generate and optionally run the related-work protocol sweep registry.

This is the reproducibility wrapper for the Basic VLM protocol sweep and the
appendix comparator rows. By default it only writes a manifest/JSONL registry
that a monitor can ingest. Use ``--run`` for smoke execution; full n=148 sweeps
also require ``--allow-full-sweep`` so this script cannot accidentally burn a
whole evaluation.

Examples:

    uv run python scripts/run_related_work_protocols.py --print-commands
    uv run python scripts/run_related_work_protocols.py --limit 1 --suite basic-vlm --run
    uv run python scripts/run_related_work_protocols.py --allow-full-sweep --run
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from run_hf_eval import _resolve_tiers, _tier_sha8

from focusparse.utils.config import load_config

PINNED_HF_REVISION = "3774c67f8b814392b6d04c939e904f749a3f52eb"
HF_REPO = "gabrielbo/parser-bench"
HF_SPLIT = "validation"
SCHEMA_VERSION = "1"

_DEFAULT_OUTPUT_DIR = Path("results/hf/related-work-protocols")
_DEFAULT_STAGING = Path.home() / ".cache" / "focusparse" / "hf_staging"
_REPO_ROOT = Path(__file__).resolve().parents[1]

_BASIC_VLM_SUITE = "basic-vlm"
_APPENDIX_COMPARATOR_SUITE = "appendix-comparators"
_ALL_SUITES = (_BASIC_VLM_SUITE, _APPENDIX_COMPARATOR_SUITE)
_PROTOCOLS = (
    "full_doc",
    "oracle_page",
    "oracle_crop",
    "tiled_2up",
    "tiled_4up",
    "tiled_8up",
    "agentic_multi_page",
)


@dataclass(frozen=True)
class ProtocolSpec:
    method_label: str
    suite: str
    agent: str
    protocol: str
    tool_set: str = "full"


BASIC_VLM_PROTOCOL_SPECS: tuple[ProtocolSpec, ...] = tuple(
    ProtocolSpec(
        method_label=f"Basic VLM / {protocol}",
        suite=_BASIC_VLM_SUITE,
        agent="simple",
        protocol=protocol,
        tool_set="full",
    )
    for protocol in _PROTOCOLS
)

APPENDIX_COMPARATOR_SPECS: tuple[ProtocolSpec, ...] = (
    ProtocolSpec(
        method_label="ReAct appendix +2 tools / agentic_multi_page",
        suite=_APPENDIX_COMPARATOR_SUITE,
        agent="react",
        protocol="agentic_multi_page",
        tool_set="minimal",
    ),
    ProtocolSpec(
        method_label="ReAct appendix +4 tools / agentic_multi_page",
        suite=_APPENDIX_COMPARATOR_SUITE,
        agent="react",
        protocol="agentic_multi_page",
        tool_set="full",
    ),
    ProtocolSpec(
        method_label="Agent baseline appendix +2 tools / agentic_multi_page",
        suite=_APPENDIX_COMPARATOR_SUITE,
        agent="agent_baseline",
        protocol="agentic_multi_page",
        tool_set="minimal",
    ),
    ProtocolSpec(
        method_label="Agent baseline appendix +4 tools / agentic_multi_page",
        suite=_APPENDIX_COMPARATOR_SUITE,
        agent="agent_baseline",
        protocol="agentic_multi_page",
        tool_set="full",
    ),
)

ALL_SPECS: tuple[ProtocolSpec, ...] = BASIC_VLM_PROTOCOL_SPECS + APPENDIX_COMPARATOR_SPECS


def main() -> int:
    args = _parse_args()
    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    config = load_config()
    resolved_tiers = _resolve_tiers(config)
    tier_sha8 = _tier_sha8(resolved_tiers)

    try:
        specs = select_specs(
            suites=args.suite,
            protocols=args.protocol,
            agents=args.agent,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    manifest = build_manifest(
        specs,
        generated_at=datetime.now(UTC).isoformat(),
        output_root=output_dir,
        staging_dir=args.staging_dir,
        pdfs_root=args.pdfs_root,
        hf_revision=args.hf_revision,
        limit=args.limit,
        resume=args.resume,
        tier_sha8=tier_sha8,
        resolved_tiers=resolved_tiers,
    )

    manifest_path = args.manifest_path or (output_dir / "related_work_protocol_manifest.json")
    registry_jsonl_path = args.registry_jsonl_path or (
        output_dir / "related_work_protocol_registry.jsonl"
    )
    _write_manifest(manifest, manifest_path, registry_jsonl_path)

    if args.print_commands:
        _print_commands(manifest)

    if not args.run:
        print(f"Wrote manifest: {manifest_path}")
        print(f"Wrote registry JSONL: {registry_jsonl_path}")
        return 0

    if args.limit is None and not args.allow_full_sweep:
        print(
            "error: refusing to run the full sweep without --allow-full-sweep. "
            "Use --limit 1 or --limit 5 for smoke.",
            file=sys.stderr,
        )
        return 2

    if not args.skip_env_check:
        missing = missing_required_env(resolved_tiers)
        if missing:
            print(
                "error: missing required environment for live model/HF calls: "
                + ", ".join(missing),
                file=sys.stderr,
            )
            return 2

    failures = _run_manifest(manifest, manifest_path, registry_jsonl_path)
    return 1 if failures else 0


def select_specs(
    *,
    suites: list[str] | None,
    protocols: list[str] | None,
    agents: list[str] | None,
) -> list[ProtocolSpec]:
    selected_suites = _selected_suites(suites)
    protocol_filter = set(protocols or [])
    agent_filter = set(agents or [])
    specs = [
        spec
        for spec in ALL_SPECS
        if spec.suite in selected_suites
        and (not protocol_filter or spec.protocol in protocol_filter)
        and (not agent_filter or spec.agent in agent_filter)
    ]
    if not specs:
        raise ValueError("No related-work protocol specs matched the requested filters.")
    return specs


def build_manifest(
    specs: list[ProtocolSpec],
    *,
    generated_at: str,
    output_root: Path,
    staging_dir: Path,
    pdfs_root: Path | None,
    hf_revision: str,
    limit: int | None,
    resume: bool,
    tier_sha8: str,
    resolved_tiers: dict[str, dict],
) -> dict[str, Any]:
    runs = [
        build_registry_entry(
            spec,
            output_root=output_root,
            staging_dir=staging_dir,
            pdfs_root=pdfs_root,
            hf_revision=hf_revision,
            limit=limit,
            resume=resume,
            tier_sha8=tier_sha8,
        )
        for spec in specs
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "hf_repo": HF_REPO,
        "hf_split": HF_SPLIT,
        "hf_revision": hf_revision,
        "limit": limit,
        "output_root": str(output_root),
        "staging_dir": str(staging_dir),
        "pdfs_root": str(pdfs_root) if pdfs_root is not None else None,
        "tier_sha8": tier_sha8,
        "resolved_tiers": resolved_tiers,
        "artifact_expectation": (
            "<output_root>/<expected_config_key>.json plus "
            "<output_root>/<expected_config_key>/{run.json,per_example.jsonl,predictions/}"
        ),
        "runs": runs,
    }


def build_registry_entry(
    spec: ProtocolSpec,
    *,
    output_root: Path,
    staging_dir: Path,
    pdfs_root: Path | None,
    hf_revision: str,
    limit: int | None,
    resume: bool,
    tier_sha8: str,
) -> dict[str, Any]:
    config_key = expected_config_key(spec, tier_sha8=tier_sha8)
    run_dir = output_root / config_key
    wrapper_json = output_root / f"{config_key}.json"
    run_json = run_dir / "run.json"
    per_example_jsonl = run_dir / "per_example.jsonl"
    predictions_dir = run_dir / "predictions"
    command_argv = build_command(
        spec,
        output_root=output_root,
        staging_dir=staging_dir,
        pdfs_root=pdfs_root,
        hf_revision=hf_revision,
        limit=limit,
        resume=resume,
    )
    return {
        "method_label": spec.method_label,
        "suite": spec.suite,
        "agent": spec.agent,
        "protocol": spec.protocol,
        "tool_set": spec.tool_set,
        "command": shlex.join(command_argv),
        "command_argv": command_argv,
        "output_root": str(output_root),
        "output_dir": str(run_dir),
        "expected_config_key": config_key,
        "expected_artifacts": {
            "wrapper_json": str(wrapper_json),
            "run_json": str(run_json),
            "per_example_jsonl": str(per_example_jsonl),
            "predictions_dir": str(predictions_dir),
        },
        "status": artifact_status(
            wrapper_json=wrapper_json,
            run_json=run_json,
            per_example_jsonl=per_example_jsonl,
        ),
    }


def build_command(
    spec: ProtocolSpec,
    *,
    output_root: Path,
    staging_dir: Path,
    pdfs_root: Path | None,
    hf_revision: str,
    limit: int | None,
    resume: bool,
) -> list[str]:
    cmd = [
        "uv",
        "run",
        "python",
        "scripts/run_hf_eval.py",
        "--agent",
        spec.agent,
        "--protocol",
        spec.protocol,
        "--tool-set",
        spec.tool_set,
        "--hf-repo",
        HF_REPO,
        "--hf-split",
        HF_SPLIT,
        "--hf-revision",
        hf_revision,
        "--output-dir",
        str(output_root),
        "--staging-dir",
        str(staging_dir),
        "--resume" if resume else "--no-resume",
    ]
    if pdfs_root is not None:
        cmd += ["--pdfs-root", str(pdfs_root)]
    if limit is not None:
        cmd += ["--limit", str(limit)]
    return cmd


def expected_config_key(spec: ProtocolSpec, *, tier_sha8: str) -> str:
    suffix = "" if spec.tool_set == "full" else f"_t{spec.tool_set}"
    return f"focusparse_{spec.agent}_{spec.protocol}_{tier_sha8}{suffix}"


def artifact_status(*, wrapper_json: Path, run_json: Path, per_example_jsonl: Path) -> str:
    required = (wrapper_json, run_json, per_example_jsonl)
    exists = [path.exists() for path in required]
    if all(exists):
        return "complete"
    if any(exists):
        return "partial"
    return "pending"


def missing_required_env(resolved_tiers: dict[str, dict]) -> list[str]:
    missing: list[str] = []
    if not os.environ.get("HF_TOKEN"):
        missing.append("HF_TOKEN")

    reasoner = resolved_tiers.get("reasoner") or {}
    provider = reasoner.get("provider")
    if provider == "openai" and not os.environ.get("OPENAI_API_KEY"):
        missing.append("OPENAI_API_KEY")
    elif provider == "anthropic" and not os.environ.get("ANTHROPIC_API_KEY"):
        missing.append("ANTHROPIC_API_KEY")
    elif provider == "gemini" and not (
        os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    ):
        missing.append("GEMINI_API_KEY or GOOGLE_API_KEY")
    return missing


def _run_manifest(
    manifest: dict[str, Any],
    manifest_path: Path,
    registry_jsonl_path: Path,
) -> int:
    failures = 0
    for run in manifest["runs"]:
        print(f"\n[{run['method_label']}] {run['command']}")
        proc = subprocess.run(run["command_argv"], cwd=_REPO_ROOT, check=False)
        run["returncode"] = proc.returncode
        artifacts = run["expected_artifacts"]
        run["status"] = artifact_status(
            wrapper_json=Path(artifacts["wrapper_json"]),
            run_json=Path(artifacts["run_json"]),
            per_example_jsonl=Path(artifacts["per_example_jsonl"]),
        )
        run["finished_at"] = datetime.now(UTC).isoformat()
        if proc.returncode != 0:
            failures += 1
            run["status"] = "failed"
        _write_manifest(manifest, manifest_path, registry_jsonl_path)
    return failures


def _write_manifest(
    manifest: dict[str, Any],
    manifest_path: Path,
    registry_jsonl_path: Path,
) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    registry_jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    registry_jsonl_path.write_text(
        "".join(json.dumps(run, sort_keys=True) + "\n" for run in manifest["runs"])
    )


def _print_commands(manifest: dict[str, Any]) -> None:
    for run in manifest["runs"]:
        print(f"{run['method_label']}:")
        print(f"  {run['command']}")


def _selected_suites(suites: list[str] | None) -> set[str]:
    if not suites or "all" in suites:
        return set(_ALL_SUITES)
    return set(suites)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite",
        action="append",
        choices=["all", *_ALL_SUITES],
        default=None,
        help="Repeatable suite filter. Default: all.",
    )
    parser.add_argument(
        "--protocol",
        action="append",
        choices=list(_PROTOCOLS),
        default=None,
        help="Repeatable protocol filter.",
    )
    parser.add_argument(
        "--agent",
        action="append",
        choices=["simple", "react", "agent_baseline"],
        default=None,
        help="Repeatable agent filter.",
    )
    parser.add_argument("--output-dir", type=Path, default=_DEFAULT_OUTPUT_DIR)
    parser.add_argument("--staging-dir", type=Path, default=_DEFAULT_STAGING)
    parser.add_argument("--pdfs-root", type=Path, default=None)
    parser.add_argument("--hf-revision", default=PINNED_HF_REVISION)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--manifest-path", type=Path, default=None)
    parser.add_argument("--registry-jsonl-path", type=Path, default=None)
    parser.add_argument("--print-commands", action="store_true", default=False)
    parser.add_argument("--run", action="store_true", default=False)
    parser.add_argument(
        "--allow-full-sweep",
        action="store_true",
        default=False,
        help="Required with --run when --limit is omitted.",
    )
    parser.add_argument(
        "--skip-env-check",
        action="store_true",
        default=False,
        help="Skip the HF/model API key preflight before --run.",
    )
    parser.add_argument("--resume", dest="resume", action="store_true", default=True)
    parser.add_argument("--no-resume", dest="resume", action="store_false")
    return parser.parse_args()


if __name__ == "__main__":
    sys.exit(main())
