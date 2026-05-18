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
        # Headline-table protocol: the simple agent gets only the per-example
        # tiled summary view (slot 0 of the prepared images list).
        "agentic_multi_page",
    }
)
_FOCUS_PROTOCOLS = frozenset(
    {
        "focus_default",
        # Headline-table protocol: the focus pipeline gets the full page
        # list; the summary view is recorded in trajectory metadata but
        # not directly consumed by the deterministic stages.
        "agentic_multi_page",
    }
)


_COMPARATOR_PROTOCOLS = frozenset(
    {
        # Comparator agents (react / agent_baseline) consume the same
        # protocols as the simple agent, but the recommended one for the
        # headline table is `agentic_multi_page`.
        "full_doc",
        "oracle_page",
        "oracle_crop",
        "tiled_2up",
        "tiled_4up",
        "tiled_8up",
        "agentic_multi_page",
    }
)


def _protocol_matches_agent(agent: str, protocol: str) -> bool:
    if agent == "focus":
        return protocol in _FOCUS_PROTOCOLS
    if agent in ("react", "llamaindex_react", "agent_baseline"):
        return protocol in _COMPARATOR_PROTOCOLS
    return protocol in _SIMPLE_PROTOCOLS


def _parse_planner_tier_by_domain(raw: str | None) -> dict[str, str] | None:
    """Parse `domain=tier,domain=tier` into a dict for FocusWorkflow.

    Returns None if `raw` is None or empty, so the workflow default
    (single-tier planner per `roles.planner`) stays in effect. Raises
    ValueError on malformed input — better to fail fast than silently
    fall back when the user opts in.
    """
    if not raw:
        return None
    out: dict[str, str] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if "=" not in entry:
            raise ValueError(f"--planner-tier-by-domain entry {entry!r} must be 'domain=tier'")
        dom, tier = entry.split("=", 1)
        out[dom.strip().lower()] = tier.strip()
    return out or None


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
            f"focus takes {sorted(_FOCUS_PROTOCOLS)}; comparators take "
            f"{sorted(_COMPARATOR_PROTOCOLS)}.",
            file=sys.stderr,
        )
        return 2

    # Deferred imports so --help works without heavy deps.
    from focusparse.cache.store import LLMResponseCache
    from focusparse.eval.harness import (
        run_comparator_eval,
        run_focus_eval,
        run_simple_eval,
    )
    from focusparse.eval.hf_loader import dataset_fingerprint, materialize_split
    from focusparse.eval.schemas import EvalRunResults, PerProtocolResults
    from focusparse.models.tiers import TierRouter
    from focusparse.utils.config import load_config

    config = load_config()
    llm_cache: LLMResponseCache | None = None
    if args.llm_cache_dir is not None:
        llm_cache = LLMResponseCache.at(args.llm_cache_dir)
        logger.info(
            "LLM cache enabled: dir=%s mode=%s (planner + localizer_rerank only).",
            args.llm_cache_dir,
            args.llm_cache_mode,
        )
    tier_router = TierRouter(config, llm_cache=llm_cache, llm_cache_mode=args.llm_cache_mode)
    resolved = _resolve_tiers(config)
    tier_sha8 = _tier_sha8(resolved)

    reasoner = config.tier_for(_REASONER_ROLE)
    backend_client = tier_router.client_for(_REASONER_ROLE)

    benchmark_jsonl, ds = materialize_split(
        args.staging_dir,
        repo_id=args.hf_repo,
        split=args.hf_split,
        revision=args.hf_revision,
        limit=None if _has_example_filter(args) else args.limit,
    )
    fingerprint = dataset_fingerprint(ds)

    # tool_set in the key so +2 / +4 variants of the same agent don't
    # collide on disk (the headline-table sweep runs both per agent).
    # Suffix is "" for the historical default ("full") so legacy paths
    # under results/hf/full-eval-v1/ keep matching.
    tool_suffix = "" if args.tool_set == "full" else f"_t{args.tool_set}"
    config_key = f"focusparse_{args.agent}_{args.protocol}_{tier_sha8}{tool_suffix}"
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
    example_ids = _requested_example_ids(args)
    if example_ids:
        examples = _filter_examples_by_ids(examples, example_ids)
        if not examples:
            print(
                "error: no requested example ids were found "
                f"({', '.join(example_ids[:5])}{'...' if len(example_ids) > 5 else ''})",
                file=sys.stderr,
            )
            return 2
    eval_limit = None if example_ids else args.limit

    if args.agent == "focus" and not args.skip_layout_preflight:
        try:
            asyncio.run(
                _preflight_layout_endpoint(
                    examples,
                    images_root=args.staging_dir,
                    max_retries=args.layout_preflight_retries,
                )
            )
        except RuntimeError as exc:
            print(
                "error: layout endpoint preflight failed; aborting focus eval before "
                f"model calls. Pass --skip-layout-preflight to override. ({exc})",
                file=sys.stderr,
            )
            return 2

    if args.agent == "focus":
        max_evidence_retries = args.max_evidence_retries
        if max_evidence_retries is None and args.max_retries is not None:
            max_evidence_retries = args.max_retries
        result = asyncio.run(
            run_focus_eval(
                examples,
                backend_client=backend_client,
                backend=reasoner.provider,
                model=reasoner.model,
                protocol=args.protocol,
                output_dir=run_dir,
                images_root=args.staging_dir,
                limit=eval_limit,
                resume=args.resume,
                config=config,
                tier_router=tier_router,
                pdfs_root=args.pdfs_root,
                max_retries=args.max_retries,
                max_evidence_retries=max_evidence_retries,
                use_evidence_graph=args.use_evidence_graph,
                auto_zoom=args.auto_zoom,
                tool_set=args.tool_set,
                use_react_inspector=args.react_inspector,
                multi_scale_packets=args.multi_scale_packets,
                chart_to_table_enabled=args.chart_to_table,
                strict_layout_detection=not args.allow_layout_fallbacks,
                layout_max_retries=args.layout_detect_retries,
                layout_timeout_s=args.layout_detect_timeout_s,
                reasoner_self_consistency_k=args.reasoner_self_consistency_k,
                planner_tier_by_domain=_parse_planner_tier_by_domain(args.planner_tier_by_domain),
                write_prediction_cache=not args.minimal_artifacts,
                compose_agentic_tiles=not args.minimal_artifacts,
            )
        )
    elif args.agent in ("react", "llamaindex_react", "agent_baseline"):
        result = asyncio.run(
            run_comparator_eval(
                examples,
                backend_client=backend_client,
                backend=reasoner.provider,
                model=reasoner.model,
                agent_kind=args.agent,
                protocol=args.protocol,
                output_dir=run_dir,
                images_root=args.staging_dir,
                limit=eval_limit,
                resume=args.resume,
                pdfs_root=args.pdfs_root,
                tool_set=args.tool_set,
                write_prediction_cache=not args.minimal_artifacts,
                persistent_tool_artifacts=not args.minimal_artifacts,
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
                limit=eval_limit,
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
    if args.visualize_trace:
        viewer_example_id = args.example_id or _first_example_id(result.get("per_example") or [])
        if viewer_example_id is None:
            print(
                "warning: --visualize-trace requested but no examples were scored", file=sys.stderr
            )
        else:
            viewer_output = args.trace_viewer_output or _default_trace_viewer_output(
                run_dir, viewer_example_id
            )
            _render_trace_viewer(
                run_dir=run_dir,
                example_id=viewer_example_id,
                output_path=viewer_output,
                staging_root=args.staging_dir,
            )
            print(f"trace viewer: {viewer_output}")
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--agent",
        choices=["simple", "focus", "react", "llamaindex_react", "agent_baseline"],
        default="simple",
        help=(
            "Method type. simple = Base VLM (no tools); focus = FocusParse "
            "stage machine; llamaindex_react = official LlamaIndex ReAct "
            "comparator; react = repo-native ReAct appendix ablation; "
            "agent_baseline = thinner generic-prompt comparator."
        ),
    )
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
            "agentic_multi_page",
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
        "--example-id",
        type=str,
        default=None,
        help="Filter the materialized split to exactly one example id. Useful with --visualize-trace.",
    )
    parser.add_argument(
        "--example-ids-file",
        type=Path,
        default=None,
        help=(
            "Filter the materialized split to the newline-delimited example ids "
            "in this file. Blank lines and # comments are ignored. Useful for "
            "mixed target/control slices."
        ),
    )
    parser.add_argument(
        "--visualize-trace",
        action="store_true",
        default=False,
        help="After the run, render the scored example's trace to a static HTML file.",
    )
    parser.add_argument(
        "--trace-viewer-output",
        type=Path,
        default=None,
        help="Optional output path for --visualize-trace. Defaults to results/trace_viewer/<run>/<example>.html.",
    )
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=1,
        help="Forward-compat only; current harness runs sequentially.",
    )
    parser.add_argument("--resume", dest="resume", action="store_true", default=True)
    parser.add_argument("--no-resume", dest="resume", action="store_false")
    parser.add_argument(
        "--minimal-artifacts",
        action="store_true",
        default=False,
        help=(
            "For disk-constrained slice experiments, skip per-example prediction "
            "cache JSONs. Focus runs also skip persistent agentic summary tile "
            "PNGs; comparator runs still compose protocol-required summary views "
            "inside per-example scratch dirs. Still writes the wrapper JSON, "
            "run.json, and per_example.jsonl. Resume is ignored for focus and "
            "comparator runs in this mode."
        ),
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=None,
        help="Override the focus workflow's verifier→retry loop budget. "
        "0 disables the loop unless --max-evidence-retries is also provided. "
        "None (default) uses FocusWorkflow's built-in full-loop default.",
    )
    parser.add_argument(
        "--max-evidence-retries",
        type=int,
        default=None,
        help=(
            "Override the focus workflow's evidence-only retry budget for "
            "expand_context/escalate_reasoner. None (default) uses the "
            "workflow default unless --max-retries is provided; then it "
            "inherits --max-retries so --max-retries 0 remains a true "
            "pre-loop baseline."
        ),
    )
    parser.add_argument(
        "--use-evidence-graph",
        action="store_true",
        default=False,
        help="Enable item 5's typed evidence-graph expansion in expand_context. "
        "Default off pending a fresh A/B under the post-2026-04-27 scorer.",
    )
    parser.add_argument(
        "--auto-zoom",
        action="store_true",
        default=False,
        help="Enable Phase 3 auto-zoom: tiny regions get a LANCZOS 2× upsample "
        "via the run_python sandbox before being handed to the reasoner. "
        "Default off pending an A/B.",
    )
    parser.add_argument(
        "--react-inspector",
        action="store_true",
        default=False,
        help="Phase 6 #1 / sprint Phase 1: route the inspect stage through "
        "an LLM-driven dispatcher (focusparse.pipeline.inspector_react) "
        "that picks which regions to inspect from the localizer's "
        "candidate list. Falls back to deterministic top-N when no "
        "inspector_dispatch tier client is available. Default off; flip "
        "after the n=148 A/B shows ≥+3pp non-overlapping CI.",
    )
    parser.add_argument(
        "--multi-scale-packets",
        action="store_true",
        default=False,
        help="Phase 6 #6 / sprint Phase 2: render both a tight crop and a "
        "wider 30%%-padded context crop per region. The reasoner sees both "
        "via EvidencePacket.multi_scale_crops. Default off pending the "
        "n=148 A/B (~+2-5pp predicted lift across both domains).",
    )
    parser.add_argument(
        "--chart-to-table",
        action="store_true",
        default=False,
        help="Phase 6 #7 / sprint Phase 3: run chart_to_table on chart "
        "regions for axis_value_interpolation / candlestick_ohlc_extraction "
        "questions. The reasoner sees the extracted CSV alongside the crop. "
        "Default off; gated by question family + figure_class so cost stays "
        "bounded. Predicted +2-4pp on Finance accuracy.",
    )
    parser.add_argument(
        "--reasoner-self-consistency-k",
        type=int,
        default=1,
        help="Phase 3b (2026-05-14 sprint): run K parallel reasoner samples "
        "on the INITIAL answer call (retries stay k=1). The picker prefers "
        "non-Unanswerable, more citations, shorter for exact_match/numeric, "
        "and higher confidence. k=2 doubles initial reasoner spend "
        "(~+$1.50 per n=148) and targets the 45 wrong_extraction_other rows "
        "in the main-stack triage. Predicted +2-3pp on top of Phase 3a v2 "
        "+ Phase 3d. Default 1 (off / back-compat).",
    )
    parser.add_argument(
        "--planner-tier-by-domain",
        default=None,
        help="Phase 3f (2026-05-15 sprint): comma-separated domain=tier pairs "
        "for per-domain planner tier routing. Example: "
        "'datasheet=frontier,finance=mid'. The 2026-05-13 sprint hybrid "
        "with this exact config hit 60.14%% on n=148 (datasheet frontier "
        "67/101, finance Haiku 22/47 = 89/148). Unmatched domains fall "
        "back to the default `roles.planner` tier in configs/default.yaml.",
    )
    parser.add_argument(
        "--tool-set",
        choices=["minimal", "full"],
        default="full",
        help=(
            "Tool belt available to the agent. minimal = inspect_region + "
            "get_text_layer (universal see-and-read). full = + layout_detect "
            "+ run_python for comparator agents; for FocusParse, full enables "
            "the corresponding stage-machine expansion/zoom path. The +2-tools "
            "/ +4-tools axis of the headline table."
        ),
    )
    parser.add_argument(
        "--skip-layout-preflight",
        action="store_true",
        default=False,
        help=(
            "Skip the focus-agent layout endpoint health check. By default, "
            "focus evals probe the shared HF layout endpoint once before any "
            "model calls so a 503/stub outage cannot produce a misleading "
            "skeleton-region A/B."
        ),
    )
    parser.add_argument(
        "--allow-layout-fallbacks",
        action="store_true",
        default=False,
        help=(
            "Allow the focus agent to continue with full-page skeleton regions "
            "when the layout endpoint fails mid-run. Default is strict for HF "
            "research evals so endpoint outages abort instead of contaminating "
            "headline numbers."
        ),
    )
    parser.add_argument(
        "--layout-preflight-retries",
        type=int,
        default=1,
        help=(
            "Retry count for the pre-run layout endpoint probe. Keep this low; "
            "the real eval still uses the layout client's normal retry policy."
        ),
    )
    parser.add_argument(
        "--layout-detect-retries",
        type=int,
        default=None,
        help=(
            "Override per-page layout detection retries during focus eval. "
            "Default uses configs/default.yaml endpoints.layout.retries."
        ),
    )
    parser.add_argument(
        "--layout-detect-timeout-s",
        type=float,
        default=None,
        help=(
            "Override per-page layout detection timeout during focus eval. "
            "Default uses configs/default.yaml endpoints.layout.timeout_s."
        ),
    )
    parser.add_argument(
        "--llm-cache-dir",
        type=Path,
        default=None,
        help=(
            "Directory for the upstream-LLM response cache (planner + region "
            "reranker). When set, runs share this cache so per-stage A/Bs are "
            "no longer dominated by upstream sampling noise. Reasoner and "
            "verifier are NEVER cached (they are the dependent variable). "
            "Default off; opt-in for variance-harness experiments."
        ),
    )
    parser.add_argument(
        "--llm-cache-mode",
        choices=["record", "replay", "record-or-replay"],
        default="record-or-replay",
        help=(
            "Cache mode when --llm-cache-dir is set. `record` always calls "
            "the backend and writes the cache (fresh recording). `replay` "
            "only reads the cache and RAISES on miss — strict reproducibility "
            "from a pinned cache. `record-or-replay` (default) reads the "
            "cache, falls back to a backend call on miss + records, which is "
            "the day-to-day mode that lets the first run record and "
            "subsequent runs replay deterministically."
        ),
    )
    return parser.parse_args()


def _filter_examples_by_id(examples: list, example_id: str) -> list:
    """Return the exact example-id match, preserving harness iterable shape."""
    return [ex for ex in examples if getattr(ex, "id", None) == example_id]


def _filter_examples_by_ids(examples: list, example_ids: list[str]) -> list:
    """Return requested ids in dataset order, preserving duplicate dataset rows."""
    wanted = set(example_ids)
    return [ex for ex in examples if getattr(ex, "id", None) in wanted]


def _requested_example_ids(args: argparse.Namespace) -> list[str]:
    ids: list[str] = []
    if args.example_id:
        ids.append(args.example_id)
    if args.example_ids_file is not None:
        ids.extend(_read_example_ids_file(args.example_ids_file))
    return _dedupe_preserve_order(ids)


def _has_example_filter(args: argparse.Namespace) -> bool:
    return bool(args.example_id or args.example_ids_file)


def _read_example_ids_file(path: Path) -> list[str]:
    ids: list[str] = []
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        ids.append(stripped)
    return ids


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _first_example_id(per_example: list[dict]) -> str | None:
    for row in per_example:
        eid = row.get("example_id")
        if eid:
            return str(eid)
    return None


def _default_trace_viewer_output(run_dir: Path, example_id: str) -> Path:
    return Path("results") / "trace_viewer" / run_dir.name / f"{example_id}.html"


async def _preflight_layout_endpoint(
    examples: list,
    *,
    images_root: Path,
    max_retries: int,
    timeout_s: float = 30.0,
    detect_layout_func=None,
) -> None:
    """Probe the shared layout endpoint before a focus eval starts.

    Focus accuracy is not comparable when `localizer` falls back to skeleton
    full-page regions. This intentionally bypasses the layout cache so it tests
    current endpoint health rather than past successful detections.
    """
    from PIL import Image

    from focusparse.tools.layout_detect import (
        LayoutEndpointUnavailable,
        StubResponseError,
        detect_layout,
    )

    image_path = _first_existing_page_image(examples, images_root)
    detector = detect_layout_func or detect_layout
    with Image.open(image_path) as im:
        width, height = im.size
    try:
        out = await detector(
            image_path.read_bytes(),
            page=1,
            image_width=width,
            image_height=height,
            cache_dir=None,
            max_retries=max_retries,
            timeout_s=timeout_s,
        )
    except (LayoutEndpointUnavailable, StubResponseError) as exc:
        raise RuntimeError(str(exc)) from exc
    logger.info(
        "layout endpoint preflight ok: image=%s size=%dx%d boxes=%d",
        image_path,
        width,
        height,
        len(getattr(out, "boxes", []) or []),
    )


def _first_existing_page_image(examples: list, images_root: Path) -> Path:
    """Return the first staged page image path available in `examples`."""
    for ex in examples:
        for rel_or_abs in getattr(ex, "page_images", None) or []:
            path = _resolve_image_path(images_root, rel_or_abs)
            if path.is_file():
                return path
    raise RuntimeError(f"no staged page image found under {images_root}")


def _resolve_image_path(images_root: Path, rel_or_abs: str) -> Path:
    path = Path(rel_or_abs)
    if path.is_absolute():
        return path
    return images_root / path


def _render_trace_viewer(
    *,
    run_dir: Path,
    example_id: str,
    output_path: Path,
    staging_root: Path,
) -> Path:
    """Render a cached prediction JSON through the static trace viewer."""
    from focusparse.traces.viewer import build_view_model, render_html

    pred_path = run_dir / "predictions" / f"{example_id}.json"
    if not pred_path.is_file():
        raise FileNotFoundError(f"prediction not found: {pred_path}")
    record = json.loads(pred_path.read_text())
    search_dirs = [
        run_dir / "crops",
        run_dir / "tiles",
        Path("cache/crops"),
    ]
    view = build_view_model(record, search_dirs=search_dirs, staging_root=staging_root)
    html_str = render_html(view, title=f"Trace · {example_id} · {run_dir.name}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_str)
    return output_path


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
        latency_ms_mean=agg.latency_ms_mean,
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
