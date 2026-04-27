"""Run FocusParse against the HF parser-bench validation split.

Single-config runner. No `--backend` flag — the reasoner comes from the tier
config (`configs/default.yaml`) and can be overridden with `--tier-override`.

    uv run python scripts/run_hf_eval.py --agent simple --protocol oracle_crop --limit 5
    uv run python scripts/run_hf_eval.py --agent simple --protocol full_doc \
        --tier-override reasoner=frontier

Writes `<output_dir>/<config_key>.json` (parser-bench-shaped, matrix-consumable)
and `<output_dir>/<config_key>/` (debug: `run.json`, `per_example.jsonl`,
`predictions/`). The run-dir doubles as the prediction cache — resuming on the
same tier config skips already-scored examples.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_STAGING = Path.home() / ".cache" / "focusparse" / "hf_staging"
_REASONER_ROLE = "reasoner"

_SIMPLE_PROTOCOLS = frozenset(
    {
        "full_doc",
        "oracle_page",
        "oracle_crop",
        "tiled_2up",
        "tiled_4up",
        "tiled_8up",
    }
)
_FOCUS_PROTOCOLS = frozenset({"focus_default"})


def _protocol_matches_agent(agent: str, protocol: str) -> bool:
    if agent == "focus":
        return protocol in _FOCUS_PROTOCOLS
    return protocol in _SIMPLE_PROTOCOLS


def main() -> int:
    args = _parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    # Apply --tier-override BEFORE loading config so FocusConfig.tier_for()
    # picks it up via the existing env-override path.
    for ov in args.tier_override:
        role, _, tier = ov.partition("=")
        if not role or not tier:
            print(f"error: --tier-override must be role=tier, got {ov!r}", file=sys.stderr)
            return 2
        os.environ[f"FOCUSPARSE_TIER_{role.upper()}"] = tier

    if not _protocol_matches_agent(args.agent, args.protocol):
        print(
            f"error: --agent {args.agent!r} is incompatible with --protocol "
            f"{args.protocol!r}. Simple takes {sorted(_SIMPLE_PROTOCOLS)}; "
            f"focus takes {sorted(_FOCUS_PROTOCOLS)}.",
            file=sys.stderr,
        )
        return 2

    # Deferred imports so --help works without heavy deps.
    from focusparse.eval.harness import run_focus_eval, run_simple_eval
    from focusparse.eval.hf_loader import dataset_fingerprint, materialize_split
    from focusparse.eval.schemas import EvalRunResults, PerProtocolResults
    from focusparse.models.tiers import TierRouter
    from focusparse.utils.config import load_config

    config = load_config()
    tier_router = TierRouter(config)
    resolved = _resolve_tiers(config)
    tier_sha8 = _tier_sha8(resolved)

    reasoner = config.tier_for(_REASONER_ROLE)
    backend_client = tier_router.client_for(_REASONER_ROLE)

    benchmark_jsonl, ds = materialize_split(
        args.staging_dir,
        repo_id=args.hf_repo,
        split=args.hf_split,
        revision=args.hf_revision,
        limit=args.limit,
    )
    fingerprint = dataset_fingerprint(ds)

    config_key = f"focusparse_{args.agent}_{args.protocol}_{tier_sha8}"
    run_dir = args.output_dir / config_key
    run_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output_dir / f"{config_key}.json"

    if args.max_concurrent > 1:
        logger.warning(
            "--max-concurrent=%d requested but harness runs sequentially; ignoring.",
            args.max_concurrent,
        )

    from focusparse._parser_bench import BenchmarkExample

    examples = [
        BenchmarkExample.model_validate_json(line)
        for line in benchmark_jsonl.read_text().splitlines()
        if line.strip()
    ]

    if args.agent == "focus":
        result = asyncio.run(
            run_focus_eval(
                examples,
                backend_client=backend_client,
                backend=reasoner.provider,
                model=reasoner.model,
                protocol=args.protocol,
                output_dir=run_dir,
                images_root=args.staging_dir,
                limit=args.limit,
                resume=args.resume,
                config=config,
                tier_router=tier_router,
                pdfs_root=args.pdfs_root,
                max_retries=args.max_retries,
            )
        )
    else:
        result = asyncio.run(
            run_simple_eval(
                examples,
                backend_client=backend_client,
                backend=reasoner.provider,
                model=reasoner.model,
                protocol=args.protocol,
                output_dir=run_dir,
                images_root=args.staging_dir,
                limit=args.limit,
                resume=args.resume,
                pdfs_root=args.pdfs_root,
            )
        )

    wrapped = _wrap_results(
        result,
        config_key=config_key,
        agent=args.agent,
        protocol=args.protocol,
        tier_sha8=tier_sha8,
        resolved_tiers=resolved,
        hf_repo=args.hf_repo,
        hf_split=args.hf_split,
        hf_revision=args.hf_revision,
        fingerprint=fingerprint,
        schemas=(EvalRunResults, PerProtocolResults),
    )
    output_path.write_text(wrapped.model_dump_json(indent=2))
    logger.info("Wrote %s", output_path)

    overall = wrapped.overall
    cost = overall.total_cost_usd or 0.0
    per_correct = overall.cost_per_correct_usd or 0.0
    print(
        f"\n{config_key}: accuracy={overall.accuracy:.1%} n={overall.count} "
        f"cost=${cost:.2f} (${per_correct:.3f}/correct)"
    )
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", choices=["simple", "focus"], default="simple")
    parser.add_argument(
        "--protocol",
        required=True,
        choices=[
            "full_doc",
            "oracle_page",
            "oracle_crop",
            "tiled_2up",
            "tiled_4up",
            "tiled_8up",
            "focus_default",
        ],
    )
    parser.add_argument(
        "--tier-override",
        action="append",
        default=[],
        metavar="ROLE=TIER",
        help="e.g. --tier-override reasoner=frontier. Repeatable.",
    )
    parser.add_argument("--hf-repo", default="gabrielbo/parser-bench")
    parser.add_argument("--hf-split", default="validation")
    parser.add_argument("--hf-revision", default=None)
    parser.add_argument("--staging-dir", type=Path, default=_DEFAULT_STAGING)
    parser.add_argument(
        "--pdfs-root",
        type=Path,
        default=None,
        help="Optional dir holding source PDFs. When set, the focus agent's "
        "router queries a native text index per example; otherwise the "
        "router falls back to the all-pages skeleton.",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("results/hf"))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=1,
        help="Forward-compat only; current harness runs sequentially.",
    )
    parser.add_argument("--resume", dest="resume", action="store_true", default=True)
    parser.add_argument("--no-resume", dest="resume", action="store_false")
    parser.add_argument(
        "--max-retries",
        type=int,
        default=None,
        help="Override the focus workflow's verifier→retry loop budget. "
        "0 disables the loop (baseline). None (default) uses FocusWorkflow's "
        "built-in default. Used to A/B item 3 against the pre-loop baseline.",
    )
    return parser.parse_args()


def _resolve_tiers(config) -> dict[str, dict]:
    """Snapshot every role's tier spec after env overrides are applied."""
    return {role: config.tier_for(role).model_dump() for role in config.roles}


def _tier_sha8(resolved: dict[str, dict]) -> str:
    """Deterministic 8-char hash of the resolved tier dict.

    `sort_keys=True` is load-bearing — Python dict ordering is stable but
    stability across Python versions and across different construction orders
    is not something we want to rely on for filenames.
    """
    payload = json.dumps(resolved, sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()[:8]


def _wrap_results(
    harness_result: dict,
    *,
    config_key: str,
    agent: str,
    protocol: str,
    tier_sha8: str,
    resolved_tiers: dict[str, dict],
    hf_repo: str,
    hf_split: str,
    hf_revision: str | None,
    fingerprint: dict,
    schemas: tuple,
):
    """Translate the harness's dict return into the parser-bench-shaped
    `EvalRunResults`. Kept separate so Phase B tests can exercise the
    transformation without network."""
    EvalRunResults, PerProtocolResults = schemas
    agg = harness_result["aggregate"]
    per_example = harness_result["per_example"]

    abstain = sum(1 for r in per_example if _looks_abstain(r.get("answer_pred")))
    abstain_rate = abstain / len(per_example) if per_example else 0.0

    overall = PerProtocolResults(
        accuracy=agg.accuracy,
        abstain_rate=abstain_rate,
        page_recall=agg.page_recall_mean,
        bbox_iou=agg.bbox_iou_mean,
        count=agg.n,
        total_cost_usd=agg.usd_total,
        cost_per_correct_usd=agg.usd_per_correct,
        total_input_tokens=int(round(agg.tokens_in_mean * agg.n)) if agg.n else 0,
        total_output_tokens=int(round(agg.tokens_out_mean * agg.n)) if agg.n else 0,
        # focus-agent extras (populated only when agent == 'focus' post-Phase-2)
        evidence_reward_mean=(agg.evidence_reward_mean if agent == "focus" else None),
        lazy_answer_rate=(agg.lazy_answer_rate if agent == "focus" else None),
        tool_calls_mean=(agg.tool_calls_mean if agent == "focus" else None),
    )
    return EvalRunResults(
        config_key=config_key,
        agent=agent,
        protocol=protocol,
        tier_sha8=tier_sha8,
        resolved_tiers=resolved_tiers,
        hf_repo=hf_repo,
        hf_split=hf_split,
        hf_revision=hf_revision,
        dataset_fingerprint=fingerprint,
        overall=overall,
    )


def _looks_abstain(text: str | None) -> bool:
    if not text:
        return False
    t = text.lower()
    return any(k in t for k in ("unanswerable", "cannot be determined", "n/a"))


if __name__ == "__main__":
    sys.exit(main())
