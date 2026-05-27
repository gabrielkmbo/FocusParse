"""Evaluation harness — runs a workflow across a benchmark slice.

`run_simple_eval` runs the single-shot baseline (parser-bench reproducibility).
`run_focus_eval` runs the agentic `FocusWorkflow` (Phase 2 skeleton wired —
stages are deterministic placeholders with one real VLM call at the reasoner).

Per-example records include: answer_correct, page_recall, bbox_iou,
evidence_reward, tokens_in/out, usd, latency, tool_calls, is_lazy. They
aggregate 1:1 into `focusparse.eval.metrics.AggregateMetrics`.

Prediction cache (`<output_dir>/predictions/<example_id>.json`) short-circuits
re-runs on the same examples — the cache key is the example id; changing the
question or the backend requires a new `output_dir`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from focusparse.eval.metrics import AggregateMetrics, aggregate, aggregate_by_domain
from focusparse.eval.scoring import (
    max_iou_over_alternates,
    page_recall,
    score_answer,
    score_evidence_reward,
)
from focusparse.eval.stage_metrics import StageMetrics, aggregate_stage_metrics
from focusparse.models._retry import is_model_throttle_error
from focusparse.models.base import ModelClient
from focusparse.pipeline.workflow import FocusWorkflow, SimpleBaselineAgent, WorkflowResult
from focusparse.tools.layout_detect import LayoutEndpointUnavailable, StubResponseError

if TYPE_CHECKING:
    from focusparse._parser_bench import BenchmarkExample

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def run_simple_eval(
    examples: Iterable[BenchmarkExample],
    *,
    backend_client: ModelClient,
    backend: str,
    model: str,
    protocol: str,
    output_dir: Path,
    images_root: Path,
    limit: int | None = None,
    resume: bool = True,
    pdfs_root: Path | None = None,
) -> dict[str, Any]:
    """Run the single-shot baseline over an iterable of examples.

    Args:
        examples: Pre-loaded iterable of `BenchmarkExample`.
        backend_client: Instantiated `ModelClient` (gemini/openai/anthropic).
        backend, model: Recorded in the run manifest for reproducibility.
        protocol: One of `full_doc` | `oracle_page` | `oracle_crop`.
        output_dir: Per-run directory. Created if absent. Predictions are
            cached under `<output_dir>/predictions/`.
        images_root: Root directory that `example.page_images` paths are
            resolved against (staging root, usually).
        limit: Max examples to score. `None` = run all.
        resume: If True and a prediction cache hit exists, skip the API call.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    pred_dir = output_dir / "predictions"
    pred_dir.mkdir(parents=True, exist_ok=True)

    agent = SimpleBaselineAgent(backend_client=backend_client, protocol=protocol)
    per_example: list[dict[str, Any]] = []

    started_at = time.time()
    n = 0
    for example in examples:
        if limit is not None and n >= limit:
            break
        n += 1

        cache_path = pred_dir / f"{_safe_id(example.id)}.json"
        record: dict[str, Any] | None = None
        if resume and cache_path.exists():
            try:
                record = json.loads(cache_path.read_text())
                record["cache_hit"] = True
            except (json.JSONDecodeError, OSError):
                record = None

        if record is None:
            images = _prepare_images(
                example,
                protocol=protocol,
                images_root=images_root,
                pdfs_root=pdfs_root,
                tile_cache_dir=output_dir / "tiles",
            )
            # Simple-agent slice: for `agentic_multi_page` we only show the
            # model the summary view (slot 0). The page list is also in
            # `images` for tool-using methods, but the Base VLM has no
            # tools so it would just see redundant input.
            agentic_meta: dict[str, object] | None = None
            if protocol == "agentic_multi_page":
                agentic_meta = _agentic_summary_meta(
                    example, images_root, pdfs_root, output_dir / "tiles"
                )
                if images:
                    images = images[:1]
            try:
                image_pages = _ordered_pages_for_images(example, images, protocol)
                result: WorkflowResult = await agent.run(example, images, image_pages=image_pages)
                image_dims = _image_dims_by_page(example, images)
                record = _score_and_record(
                    example,
                    result,
                    protocol=protocol,
                    image_dims_by_page=image_dims,
                    image_pages=image_pages,
                )
                if agentic_meta is not None:
                    record["agentic_meta"] = agentic_meta
                cache_path.write_text(json.dumps(record, default=str))
            except Exception as exc:
                if _should_abort_eval_on_error(exc):
                    raise
                logger.exception("Example %s failed: %s", example.id, exc)
                record = _error_record(example, protocol=protocol, error=str(exc))

        per_example.append(record)

    aggregated: AggregateMetrics = aggregate(per_example)
    aggregated_by_domain = aggregate_by_domain(per_example)
    stage_aggregate = _aggregate_stages(per_example)

    run_manifest: dict[str, Any] = {
        "agent": "simple",
        "backend": backend,
        "model": model,
        "protocol": protocol,
        "n_examples": n,
        "limit": limit,
        "started_at": started_at,
        "ended_at": time.time(),
        "aggregate": aggregated.model_dump(),
        "aggregate_by_domain": {k: v.model_dump() for k, v in aggregated_by_domain.items()},
        "stage_aggregate": stage_aggregate.model_dump(),
        "env_snapshot": _env_snapshot(),
    }
    (output_dir / "run.json").write_text(json.dumps(run_manifest, default=str, indent=2))
    (output_dir / "per_example.jsonl").write_text(
        "\n".join(json.dumps(r, default=str) for r in per_example) + ("\n" if per_example else "")
    )

    return {
        "manifest": run_manifest,
        "aggregate": aggregated,
        "aggregate_by_domain": aggregated_by_domain,
        "stage_aggregate": stage_aggregate,
        "per_example": per_example,
        "output_dir": str(output_dir),
    }


async def run_comparator_eval(
    examples: Iterable[BenchmarkExample],
    *,
    backend_client: ModelClient,
    backend: str,
    model: str,
    agent_kind: str,  # "react" | "agent_baseline"
    protocol: str,
    output_dir: Path,
    images_root: Path,
    limit: int | None = None,
    resume: bool = True,
    pdfs_root: Path | None = None,
    tool_set: str = "full",
) -> dict[str, Any]:
    """Run a comparator agent (ReAct loop or generic Agent baseline) over examples.

    Mirrors the contract of `run_simple_eval` / `run_focus_eval` so the
    matrix harness can dispatch to all four method types uniformly.
    The comparator agent's tool belt is resolved from `tool_set`
    (minimal → 2 tools; full → 4 tools).

    Distinguishes from the focus path by *not* having any FocusParse
    stage machine — just a think→act→observe loop. This is the
    architectural ablation that makes the headline-table claim falsifiable.
    """
    from focusparse.pipeline.agent_baseline import AgentBaselineAgent
    from focusparse.pipeline.react_agent import ReActAgent
    from focusparse.tools import resolve_tool_set

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    pred_dir = output_dir / "predictions"
    pred_dir.mkdir(parents=True, exist_ok=True)

    tools = resolve_tool_set(tool_set)
    available_tools = [tool.name for tool in tools]
    if agent_kind == "react":
        agent = ReActAgent(backend_client=backend_client, tools=tools)
    elif agent_kind == "agent_baseline":
        agent = AgentBaselineAgent(backend_client=backend_client, tools=tools)
    else:
        raise ValueError(f"Unknown comparator agent_kind: {agent_kind!r}")

    per_example: list[dict[str, Any]] = []
    started_at = time.time()
    n = 0
    for example in examples:
        if limit is not None and n >= limit:
            break
        n += 1

        cache_path = pred_dir / f"{_safe_id(example.id)}.json"
        record: dict[str, Any] | None = None
        if resume and cache_path.exists():
            try:
                record = json.loads(cache_path.read_text())
                record["cache_hit"] = True
            except (json.JSONDecodeError, OSError):
                record = None

        if record is None:
            images = _prepare_images(
                example,
                protocol=protocol,
                images_root=images_root,
                pdfs_root=pdfs_root,
                tile_cache_dir=output_dir / "tiles",
            )
            agentic_meta: dict[str, object] | None = None
            if protocol == "agentic_multi_page":
                agentic_meta = _agentic_summary_meta(
                    example, images_root, pdfs_root, output_dir / "tiles"
                )
            pdf_path = _resolve_pdf_path(pdfs_root, example) if pdfs_root else None
            try:
                result: WorkflowResult = await agent.run(
                    example,
                    images,
                    pdf_path=pdf_path,
                    crop_cache_dir=output_dir / "crops",
                    text_layer_cache_dir=output_dir / "text_layer",
                )
                image_dims = _image_dims_by_page(example, images)
                record = _score_and_record(
                    example,
                    result,
                    protocol=protocol,
                    image_dims_by_page=image_dims,
                    available_tools=available_tools,
                )
                if agentic_meta is not None:
                    record["agentic_meta"] = agentic_meta
                cache_path.write_text(json.dumps(record, default=str))
            except Exception as exc:
                if _should_abort_eval_on_error(exc):
                    raise
                logger.exception("Example %s failed: %s", example.id, exc)
                record = _error_record(example, protocol=protocol, error=str(exc))

        per_example.append(record)

    aggregated: AggregateMetrics = aggregate(per_example)
    aggregated_by_domain = aggregate_by_domain(per_example)
    stage_aggregate = _aggregate_stages(per_example)

    run_manifest: dict[str, Any] = {
        "agent": agent_kind,
        "tool_set": tool_set,
        "available_tools": available_tools,
        "backend": backend,
        "model": model,
        "protocol": protocol,
        "n_examples": n,
        "limit": limit,
        "started_at": started_at,
        "ended_at": time.time(),
        "aggregate": aggregated.model_dump(),
        "aggregate_by_domain": {k: v.model_dump() for k, v in aggregated_by_domain.items()},
        "stage_aggregate": stage_aggregate.model_dump(),
        "env_snapshot": _env_snapshot(),
    }
    (output_dir / "run.json").write_text(json.dumps(run_manifest, default=str, indent=2))
    (output_dir / "per_example.jsonl").write_text(
        "\n".join(json.dumps(r, default=str) for r in per_example) + ("\n" if per_example else "")
    )

    return {
        "manifest": run_manifest,
        "aggregate": aggregated,
        "aggregate_by_domain": aggregated_by_domain,
        "stage_aggregate": stage_aggregate,
        "per_example": per_example,
        "output_dir": str(output_dir),
    }


async def run_focus_eval(
    examples: Iterable[BenchmarkExample],
    *,
    backend_client: ModelClient,
    backend: str,
    model: str,
    protocol: str,
    output_dir: Path,
    images_root: Path,
    limit: int | None = None,
    resume: bool = True,
    config: Any = None,
    tier_router: Any = None,
    pdfs_root: Path | None = None,
    max_retries: int | None = None,
    max_evidence_retries: int | None = None,
    use_evidence_graph: bool = False,
    auto_zoom: bool = False,
    tool_set: str = "full",
    use_react_inspector: bool = False,
    multi_scale_packets: bool = False,
    chart_to_table_enabled: bool = False,
    disable_rerank: bool = False,
    disable_expand_context: bool = False,
    disable_answer_shape_repair: bool = False,
    strict_layout_detection: bool = False,
    layout_max_retries: int | None = None,
    layout_timeout_s: float | None = None,
    reasoner_self_consistency_k: int = 1,
    planner_tier_by_domain: dict[str, str] | None = None,
    write_prediction_cache: bool = True,
    compose_agentic_tiles: bool = True,
) -> dict[str, Any]:
    """Run `FocusWorkflow` over an iterable of examples.

    Mirrors `run_simple_eval`'s contract so `scripts/run_hf_eval.py` can route
    to either without branching. The focus agent always sees *all* pages —
    the protocol knob that matters for baselines (full_doc/oracle_page/
    oracle_crop) is a simple-agent concept; for the agentic pipeline we pass
    the full document and let the router do its job. `protocol` here is
    recorded for provenance and defaults to `focus_default`.

    Args:
        examples: Pre-loaded iterable of `BenchmarkExample`.
        backend_client: Reasoner `ModelClient` (resolved by caller from
            `TierRouter.client_for("reasoner")`).
        backend, model: Recorded in the run manifest for reproducibility.
        protocol: Typically `focus_default`. Recorded in per-example rows.
        output_dir, images_root, limit, resume: Same semantics as `run_simple_eval`.
        config: Optional `FocusConfig` passed through to the workflow for
            budget-aware planning. Skeleton workflow reads only `.budget`.
        tier_router: Optional `TierRouter`. When provided, the workflow's
            non-reasoner stages (currently: planner) resolve their clients
            through it. When absent, those stages fall back to deterministic
            placeholders.
        pdfs_root: Optional directory where source PDFs live. When provided,
            the harness resolves `pdfs_root / example.source_pdf` and passes
            it to `FocusWorkflow.run(pdf_path=...)`, which feeds native text
            into the FTS router. Missing files silently degrade to the
            skeleton router — the run keeps going.
        strict_layout_detection: when True, layout endpoint outage/stub errors
            abort the eval instead of becoming skeleton-region examples.
        layout_max_retries / layout_timeout_s: optional overrides for the
            layout detector transport. None falls through to config/defaults.
        write_prediction_cache: when False, skip per-example prediction JSONs
            and disable resume. Intended for disk-constrained slice runs; the
            aggregate manifest and per_example.jsonl are still written.
        compose_agentic_tiles: when False, skip summary tile PNG creation for
            agentic_multi_page focus runs. Focus still receives the real page
            images, which is the behavior used by the workflow itself.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    pred_dir = output_dir / "predictions" if write_prediction_cache else None
    if pred_dir is not None:
        pred_dir.mkdir(parents=True, exist_ok=True)
    else:
        resume = False

    workflow_kwargs: dict[str, Any] = {
        "backend_client": backend_client,
        "config": config,
        "tier_router": tier_router,
        "allow_layout_endpoint_fallback": not strict_layout_detection,
        "layout_max_retries": layout_max_retries,
        "layout_timeout_s": layout_timeout_s,
    }
    if max_retries is not None:
        # Caller-side override (e.g. baseline=0 vs item-3=2) controls the
        # verifier→retry loop. None falls through to FocusWorkflow's built-
        # in default.
        workflow_kwargs["max_retries"] = max_retries
    if max_evidence_retries is not None:
        # Separate budget for evidence-only controller actions
        # (`expand_context` / `escalate_reasoner`). This lets the default
        # workflow try one low-risk repair while keeping localization retries
        # opt-in.
        workflow_kwargs["max_evidence_retries"] = max_evidence_retries
    if use_evidence_graph:
        # Item-5 toggle: typed graph expansion in expand_context. Off by
        # default pending a fresh A/B under the post-2026-04-27 scorer.
        workflow_kwargs["use_evidence_graph"] = True
    if auto_zoom:
        # Phase-3 toggle: deterministic LANCZOS 2× upsample of tiny crops.
        # Workflow forces this off when tool_set=="minimal" (run_python is
        # not in the +2-tools belt), but we still surface the flag here so
        # the tier-router log records the caller's intent.
        workflow_kwargs["auto_zoom"] = True
    if tool_set != "full":
        # +2-tools ablation row of the headline table. Workflow validates
        # the value; harness just forwards.
        workflow_kwargs["tool_set"] = tool_set
    if use_react_inspector:
        # Sprint Phase 1 (2026-05-04, Phase 6 #1): LLM-driven inspector.
        workflow_kwargs["use_react_inspector"] = True
    if multi_scale_packets:
        # Sprint Phase 2 (2026-05-04, Phase 6 #6): tight + context crops.
        workflow_kwargs["multi_scale_packets"] = True
    if chart_to_table_enabled:
        # Sprint Phase 3 (2026-05-04, Phase 6 #7): chart_to_table extraction
        # gated on question_family + figure_class inside the inspector.
        workflow_kwargs["chart_to_table_enabled"] = True
    if disable_rerank:
        # Paper mechanism ablation: preserve localizer ordering and skip the
        # query-conditioned reranker call.
        workflow_kwargs["disable_rerank"] = True
    if disable_expand_context:
        # Paper mechanism ablation: keep the full tool belt except the
        # context-expansion stage. Unlike tool_set=minimal this can still use
        # run_python/auto-zoom when enabled.
        workflow_kwargs["disable_expand_context"] = True
    if disable_answer_shape_repair:
        # Paper mechanism ablation: preserve verifier scoring and evidence
        # repair budgets, but block answer-shape-specific retry/selection
        # guards so output normalization can be isolated from evidence
        # construction.
        workflow_kwargs["disable_answer_shape_repair"] = True
    if reasoner_self_consistency_k != 1:
        # Phase 3b (2026-05-14 sprint): K-sample reasoner self-consistency on
        # the initial answer call. k=2 default-off; opt-in via CLI flag.
        # Costs ~k× initial reasoner spend on n=148. The workflow constructor
        # validates k >= 1.
        workflow_kwargs["reasoner_self_consistency_k"] = reasoner_self_consistency_k
    if planner_tier_by_domain:
        # Phase 3f (2026-05-15 sprint): per-domain planner tier. Datasheet ->
        # frontier (gpt-5.4) gains +2.9pp on datasheet; finance -> mid (Haiku)
        # gains +4.2pp on finance vs the single-tier alternatives.
        workflow_kwargs["planner_tier_by_domain"] = planner_tier_by_domain
    workflow = FocusWorkflow(**workflow_kwargs)
    available_tools = workflow.available_tools()
    per_example: list[dict[str, Any]] = []

    started_at = time.time()
    n = 0
    for example in examples:
        if limit is not None and n >= limit:
            break
        n += 1

        cache_path = pred_dir / f"{_safe_id(example.id)}.json" if pred_dir is not None else None
        record: dict[str, Any] | None = None
        if cache_path is not None and resume and cache_path.exists():
            try:
                record = json.loads(cache_path.read_text())
                record["cache_hit"] = True
            except (json.JSONDecodeError, OSError):
                record = None

        if record is None:
            # Focus agent always sees all pages — routing is its job.
            images = [_resolve(images_root, p) for p in (example.page_images or [])]
            pdf_path = _resolve_pdf_path(pdfs_root, example)
            # For `agentic_multi_page` we also compose the summary view so
            # the per-example record carries `summary_tile_size` for
            # appendix breakdowns. The focus pipeline itself only consumes
            # real pages (its `_images_by_page` ignores non-page-named
            # files), so prepending the summary view is harmless.
            agentic_meta: dict[str, object] | None = None
            if protocol == "agentic_multi_page":
                if compose_agentic_tiles:
                    agentic_images = _prepare_images(
                        example,
                        protocol=protocol,
                        images_root=images_root,
                        pdfs_root=pdfs_root,
                        tile_cache_dir=output_dir / "tiles",
                    )
                    if agentic_images:
                        images = agentic_images
                agentic_meta = _agentic_summary_meta(
                    example, images_root, pdfs_root, output_dir / "tiles"
                )
            try:
                result: WorkflowResult = await workflow.run(
                    example, images, protocol=protocol, pdf_path=pdf_path
                )
                image_dims = _image_dims_by_page(example, images)
                record = _score_and_record(
                    example,
                    result,
                    protocol=protocol,
                    image_dims_by_page=image_dims,
                    available_tools=available_tools,
                )
                if agentic_meta is not None:
                    record["agentic_meta"] = agentic_meta
                if cache_path is not None:
                    cache_path.write_text(json.dumps(record, default=str))
            except Exception as exc:
                if _should_abort_eval_on_error(
                    exc,
                    strict_layout_detection=strict_layout_detection,
                ):
                    raise
                logger.exception("Example %s failed: %s", example.id, exc)
                record = _error_record(example, protocol=protocol, error=str(exc))

        per_example.append(record)

    aggregated: AggregateMetrics = aggregate(per_example)
    aggregated_by_domain = aggregate_by_domain(per_example)
    stage_aggregate = _aggregate_stages(per_example)

    run_manifest: dict[str, Any] = {
        "agent": "focus",
        "tool_set": tool_set,
        "available_tools": available_tools,
        "focus_features": {
            "auto_zoom": workflow.auto_zoom,
            "chart_to_table_enabled": workflow.chart_to_table_enabled,
            "use_react_inspector": workflow.use_react_inspector,
            "multi_scale_packets": workflow.multi_scale_packets,
            "use_evidence_graph": workflow.use_evidence_graph,
            "disable_rerank": workflow.disable_rerank,
            "disable_expand_context": workflow.disable_expand_context,
            "disable_answer_shape_repair": workflow.disable_answer_shape_repair,
        },
        "backend": backend,
        "model": model,
        "protocol": protocol,
        "n_examples": n,
        "limit": limit,
        "started_at": started_at,
        "ended_at": time.time(),
        "aggregate": aggregated.model_dump(),
        "aggregate_by_domain": {k: v.model_dump() for k, v in aggregated_by_domain.items()},
        "stage_aggregate": stage_aggregate.model_dump(),
        "artifact_policy": {
            "write_prediction_cache": write_prediction_cache,
            "compose_agentic_tiles": compose_agentic_tiles,
        },
        "env_snapshot": _env_snapshot(),
    }
    (output_dir / "run.json").write_text(json.dumps(run_manifest, default=str, indent=2))
    (output_dir / "per_example.jsonl").write_text(
        "\n".join(json.dumps(r, default=str) for r in per_example) + ("\n" if per_example else "")
    )

    return {
        "manifest": run_manifest,
        "aggregate": aggregated,
        "aggregate_by_domain": aggregated_by_domain,
        "stage_aggregate": stage_aggregate,
        "per_example": per_example,
        "output_dir": str(output_dir),
    }


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _prepare_images(
    example: BenchmarkExample,
    *,
    protocol: str,
    images_root: Path,
    pdfs_root: Path | None = None,
    tile_cache_dir: Path | None = None,
) -> list[Path]:
    """Resolve + filter + (for oracle_crop / tiled_*) compose page images.

    Tiled protocols (`tiled_2up` / `tiled_4up` / `tiled_8up`) compose the
    gold supporting page(s) plus PDF-rendered noise pages into one
    contact-sheet PNG, mirroring parser-bench's `prepare_tiled_images`.
    Requires a PDF for noise-rendering when N > len(staged_pages); falls
    back to staged-pages-only when no PDF is wired.

    `agentic_multi_page` is the headline-table protocol: returns
    `[summary_view, ...page_list]` where `summary_view` is a per-example
    tiled composition at a sampled tile size in {2,4,8}. Caller is
    responsible for slicing — `run_simple_eval` takes only `[summary_view]`,
    `run_focus_eval` keeps the full list.
    """
    from focusparse.eval.tile import (
        TILE_SIZES,
        prepare_agentic_multi_page,
        prepare_tiled_images,
    )

    all_pages = [_resolve(images_root, p) for p in (example.page_images or [])]
    supporting_pages = list(example.supporting_pages or [])

    if protocol == "full_doc":
        return all_pages

    if protocol == "oracle_page":
        # `page_images` is ordered by `supporting_pages` — take the same prefix.
        if not supporting_pages:
            return all_pages
        return all_pages[: len(supporting_pages)]

    if protocol == "oracle_crop":
        return _make_oracle_crops(example, all_pages, images_root)

    if protocol in TILE_SIZES:
        n_tile = TILE_SIZES[protocol]
        cache_dir = tile_cache_dir or (images_root.parent / "tile_cache")
        pdf_path = _resolve_pdf_path(pdfs_root, example) if pdfs_root else None
        return prepare_tiled_images(
            example,
            n_tile,
            staged_pages=all_pages,
            pdf_path=pdf_path,
            tile_cache_dir=cache_dir,
        )

    if protocol == "agentic_multi_page":
        cache_dir = tile_cache_dir or (images_root.parent / "tile_cache")
        pdf_path = _resolve_pdf_path(pdfs_root, example) if pdfs_root else None
        bundle = prepare_agentic_multi_page(
            example,
            staged_pages=all_pages,
            pdf_path=pdf_path,
            cache_dir=cache_dir,
        )
        out: list[Path] = []
        if bundle.summary_view is not None:
            out.append(bundle.summary_view)
        out.extend(bundle.page_list)
        return out

    raise ValueError(f"Unknown protocol: {protocol!r}")


def _agentic_summary_meta(
    example: BenchmarkExample,
    images_root: Path,
    pdfs_root: Path | None,
    tile_cache_dir: Path | None,
) -> dict[str, object]:
    """Per-example metadata for the agentic_multi_page protocol.

    Returns `{summary_tile_size, has_summary_view}`. Cheap (no rendering;
    `prepare_agentic_multi_page` is content-addressed so reuse hits the
    cache when called repeatedly with the same example/cache_dir). Useful
    for recording in per-example records so the headline table can be
    split by tile-size as an appendix experiment.
    """
    from focusparse.eval.tile import sample_agentic_tile_size

    return {
        "summary_tile_size": sample_agentic_tile_size(example.id),
        # `has_summary_view` is the truthiness of the summary path; we
        # compute it lazily by checking the cache at lookup time.
        "summary_view_cached": _summary_view_cached(example, images_root, tile_cache_dir),
    }


def _summary_view_cached(
    example: BenchmarkExample,
    images_root: Path,
    tile_cache_dir: Path | None,
) -> bool:
    """Check whether a summary-view PNG already exists on disk."""
    from focusparse.eval.tile import sample_agentic_tile_size

    cache_dir = tile_cache_dir or (images_root.parent / "tile_cache")
    n = sample_agentic_tile_size(example.id)
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", example.id)
    return (cache_dir / f"{safe_id}_tiled_{n}up.png").exists()


def _resolve(images_root: Path, rel_or_abs: str) -> Path:
    p = Path(rel_or_abs)
    if p.is_absolute():
        return p
    return images_root / p


def _resolve_pdf_path(
    pdfs_root: Path | None,
    example: BenchmarkExample,
) -> Path | None:
    """Return the on-disk PDF for this example, or None.

    Tries `<pdfs_root>/<source_pdf>` first, then `<pdfs_root>/<doc_stem>/
    <source_pdf>` (parser-bench's nested layout). Returns None when no
    `pdfs_root` is configured or neither location exists — the workflow
    keeps running with a skeleton router.
    """
    if pdfs_root is None:
        return None
    src = getattr(example, "source_pdf", None)
    if not src:
        return None
    candidate = pdfs_root / src
    if candidate.exists():
        return candidate
    doc_stem = Path(src).stem
    nested = pdfs_root / doc_stem / src
    if nested.exists():
        return nested
    return None


def _ordered_pages_for_images(
    example: BenchmarkExample,
    images: list[Path],
    protocol: str,
) -> list[int] | None:
    """Per-protocol map of image-index -> source page number.

    The simple agent's prompt uses this to tell the model which page
    corresponds to which image, so citations come back with real page
    numbers (not 1-indexed positional). For tiled protocols the page list
    is the constituent pages packed into the contact sheet.

    Returns None when the mapping can't be determined (older fixtures
    without `_page_NNNN_` filenames + no supporting_pages hint).
    """
    import re as _re

    from focusparse.eval.tile import TILE_SIZES

    if protocol in TILE_SIZES:
        # Tiled protocols: caller still has the raw staged page list, so
        # use those page numbers (the tile is a composition; the model
        # should cite the underlying pages).
        return _pages_from_filenames(example.page_images or [])

    pat = _re.compile(r"_page_(\d+)")
    pages: list[int] = []
    for idx, img_path in enumerate(images):
        m = pat.search(img_path.name)
        if m:
            pages.append(int(m.group(1)))
        elif example.supporting_pages and idx < len(example.supporting_pages):
            pages.append(int(example.supporting_pages[idx]))
        else:
            pages.append(idx + 1)
    return pages or None


def _pages_from_filenames(rel_paths: list[str]) -> list[int] | None:
    """Extract page numbers from `..._page_NNNN_300dpi.png` filenames."""
    import re as _re

    pat = _re.compile(r"_page_(\d+)")
    out: list[int] = []
    for p in rel_paths:
        m = pat.search(Path(p).name)
        if m:
            out.append(int(m.group(1)))
    return out or None


def _image_dims_by_page(
    example: BenchmarkExample,
    images: list[Path],
) -> dict[int, tuple[int, int]]:
    """Map 1-indexed page -> (width, height) for resolved page image paths.

    Needed by the scoring layer to normalize pixel-space gold bboxes against
    normalized [0,1] predicted bboxes. Missing/unreadable files are silently
    omitted — scoring degrades gracefully to raw-coord IoU on that page.
    """
    import re

    from PIL import Image

    pat = re.compile(r"_page_(\d+)")
    dims: dict[int, tuple[int, int]] = {}
    for idx, img_path in enumerate(images):
        if not img_path.exists():
            continue
        m = pat.search(img_path.name)
        page = int(m.group(1)) if m else idx + 1
        try:
            with Image.open(img_path) as img:
                dims[page] = (int(img.width), int(img.height))
        except (OSError, ValueError):
            continue
    # Also index by the BenchmarkExample's supporting_pages order when the
    # filename didn't carry a page number (older fixtures). No-op when the
    # name regex above already found the page.
    _ = example  # intentionally unused — reserved for future override logic
    return dims


def _make_oracle_crops(
    example: BenchmarkExample,
    all_pages: list[Path],
    images_root: Path,
) -> list[Path]:
    """Crop each supporting page image to the union of its supporting bboxes.

    Writes crops into `<images_root>/.oracle_crops/<example_id>/page_NN.png` so
    re-runs hit disk cache. Coords in `BBox` are normalized [0, 1].
    """
    from PIL import Image

    crop_dir = images_root / ".oracle_crops" / _safe_id(example.id)
    crop_dir.mkdir(parents=True, exist_ok=True)

    by_page: dict[int, list[Any]] = {}
    for bbox in example.supporting_bboxes:
        by_page.setdefault(int(bbox.page), []).append(bbox)

    supporting_pages = list(example.supporting_pages or [])
    crops: list[Path] = []
    for idx, page_num in enumerate(supporting_pages):
        if idx >= len(all_pages):
            continue
        src = all_pages[idx]
        if not src.exists():
            continue
        boxes_on_page = by_page.get(int(page_num), [])
        if not boxes_on_page:
            crops.append(src)
            continue

        out_path = crop_dir / f"page_{int(page_num):04d}.png"
        if not out_path.exists():
            with Image.open(src) as img:
                w, h = img.size
                x0 = min(b.x0 for b in boxes_on_page)
                y0 = min(b.y0 for b in boxes_on_page)
                x1 = max(b.x1 for b in boxes_on_page)
                y1 = max(b.y1 for b in boxes_on_page)
                # parser-bench BBox is documented as pixel-space; older
                # callers may pass normalized [0,1]. Detect by magnitude.
                if max(x0, y0, x1, y1) <= 1.0:
                    x0, y0, x1, y1 = x0 * w, y0 * h, x1 * w, y1 * h
                box_px = (
                    max(0, int(x0)),
                    max(0, int(y0)),
                    min(w, int(x1)),
                    min(h, int(y1)),
                )
                img.crop(box_px).save(out_path, format="PNG")
        crops.append(out_path)
    return crops


def _remap_positional_pages(
    citations: list[dict[str, Any]],
    image_pages: list[int] | None,
) -> list[dict[str, Any]]:
    """Remap 1-indexed positional citation pages to source pages.

    The simple agent (and any VLM that doesn't internalize the page-mapping
    hint) tends to emit `page=1` for the first image, `page=2` for the
    second, etc. When `image_pages` is provided, treat any citation page
    that's a valid positional index AND not already in `image_pages` as
    positional and remap it. Citations that already use a real source page
    pass through untouched (idempotent).
    """
    if not image_pages:
        return citations
    out: list[dict[str, Any]] = []
    page_set = set(image_pages)
    for c in citations:
        p = c.get("page")
        if isinstance(p, int) and 1 <= p <= len(image_pages) and p not in page_set:
            c = {**c, "page": image_pages[p - 1]}
        out.append(c)
    return out


def _score_and_record(
    example: BenchmarkExample,
    result: WorkflowResult,
    *,
    protocol: str,
    image_dims_by_page: dict[int, tuple[int, int]] | None = None,
    image_pages: list[int] | None = None,
    available_tools: list[str] | None = None,
) -> dict[str, Any]:
    """Score one prediction and flatten into a per-example record.

    `image_dims_by_page` forwards to scoring so pixel-space gold bboxes
    and normalized [0,1] predicted bboxes compare correctly.
    `image_pages` enables positional → source-page remapping for citations
    when the model emitted page=1..N rather than the actual source pages.
    """
    from focusparse._parser_bench import BBox as _BBox

    citations = _remap_positional_pages(list(result.citations), image_pages)
    predicted_pages = [int(c["page"]) for c in citations if "page" in c]
    predicted_bboxes: list[Any] = []
    for c in citations:
        bbox = c.get("bbox")
        if not (isinstance(bbox, list) and len(bbox) == 4):
            continue
        try:
            predicted_bboxes.append(
                _BBox(
                    page=int(c["page"]),
                    x0=float(bbox[0]),
                    y0=float(bbox[1]),
                    x1=float(bbox[2]),
                    y1=float(bbox[3]),
                )
            )
        except (TypeError, ValueError, KeyError):
            continue

    answer = score_answer(result.answer, example)
    recall = page_recall(predicted_pages, [int(p) for p in (example.supporting_pages or [])])
    iou = max_iou_over_alternates(predicted_bboxes, example, image_dims_by_page=image_dims_by_page)
    tool_calls = sum(
        1 for step in result.trace.steps if step.action == "tool_call" or step.tool is not None
    )
    evidence = score_evidence_reward(
        prediction_text=result.answer,
        predicted_pages=predicted_pages,
        predicted_bboxes=predicted_bboxes,
        tool_calls=[{"tool": s.tool} for s in result.trace.steps if s.tool is not None],
        example=example,
        largest_crop_area_ratio=0.0,
        image_dims_by_page=image_dims_by_page,
    )
    is_lazy = int(tool_calls == 0 or not predicted_bboxes)
    tool_diagnostics = _tool_diagnostics_from_trace(
        result,
        evidence_reward=evidence,
        available_tools=available_tools,
    )

    # Trace as a plain dict so the stage-metrics module can read it without
    # depending on the workflow internals. Stages get summed across multi-
    # step instances (the verifier-loop case) by `compute_stage_metrics`.
    # `obs_summary` and `confidence` are kept on disk so the per-trace
    # viewer (Phase 6 sub-plan, 2026-05-04) can render what the LLM saw
    # at each step. `evidence_snapshot` is the v2 field — the final
    # packets the reasoner used. v3 adds artifacts + debug_events for the
    # one-example dashboard; all are absent/defaulted on legacy traces.
    evidence_snapshot = getattr(result.trace, "evidence_snapshot", None)
    artifacts = getattr(result.trace, "artifacts", [])
    debug_events = getattr(result.trace, "debug_events", [])
    trace_dict = {
        "steps": [
            {
                "step_index": step.step_index,
                "stage": step.stage,
                "tier": step.tier,
                "action": step.action,
                "tool": step.tool,
                "args": step.args,
                "obs_ref": step.obs_ref,
                "obs_summary": step.obs_summary,
                "tokens_in": step.tokens_in,
                "tokens_out": step.tokens_out,
                "usd": step.usd,
                "latency_ms": step.latency_ms,
                "confidence": step.confidence,
            }
            for step in result.trace.steps
        ],
        "evidence_snapshot": (
            [p.model_dump(mode="json") for p in evidence_snapshot]
            if evidence_snapshot is not None
            else None
        ),
        "artifacts": [a.model_dump(mode="json") for a in artifacts],
        "debug_events": [e.model_dump(mode="json") for e in debug_events],
    }

    telemetry = dict(result.telemetry or {})
    telemetry.update(
        {
            "available_tools": tool_diagnostics["available_tools"],
            "selected_tools": tool_diagnostics["selected_tools"],
            "tool_call_sequence": tool_diagnostics["tool_call_sequence"],
            "failed_tool_call_count": tool_diagnostics["failed_tool_call_count"],
            "useful_tool_call_count": tool_diagnostics["useful_tool_call_count"],
            "irrelevant_tool_call_count": tool_diagnostics["irrelevant_tool_call_count"],
            "answer_changed_after_tool": tool_diagnostics["answer_changed_after_tool"],
            "verifier_supported_after_tool": tool_diagnostics["verifier_supported_after_tool"],
        }
    )

    record = {
        "example_id": example.id,
        "protocol": protocol,
        # `domain` is recorded so `aggregate_by_domain` can bucket without
        # re-loading the benchmark. Stem (`"datasheet"`/`"finance"`) is
        # extracted at aggregation time via `metrics._domain_stem`.
        "domain": str(getattr(example, "domain", "")) or None,
        "answer_pred": result.answer,
        "answer_gold": example.answer,
        "answer_correct": answer,
        "page_recall": recall,
        "bbox_iou": iou,
        "evidence_reward": evidence,
        "is_lazy": is_lazy,
        "tool_calls": tool_calls,
        "tokens_in": result.telemetry.get("tokens_in", 0),
        "tokens_out": result.telemetry.get("tokens_out", 0),
        "usd": result.telemetry.get("usd") or 0.0,
        "latency_ms": result.telemetry.get("latency_ms", 0),
        "citations": citations,
        "cache_hit": False,
        **tool_diagnostics,
        "telemetry": telemetry,
        "trace": trace_dict,
    }

    # Stage-level metrics. Pulled forward from Phase 4 (2026-04-27) as the
    # measurement gate for items 3-5 of the SOTA-leverage plan.
    from focusparse.eval.stage_metrics import compute_stage_metrics

    stages = compute_stage_metrics(record, example, image_dims_by_page=image_dims_by_page)
    record["stages"] = stages.model_dump(mode="json")

    return record


def _tool_diagnostics_from_trace(
    result: WorkflowResult,
    *,
    evidence_reward: float,
    available_tools: list[str] | None = None,
) -> dict[str, Any]:
    """Per-example tool instrumentation for +2/+4 ablations.

    `tool_calls` stays historically compatible. This helper adds a richer,
    explicitly named view that treats FocusParse's deterministic
    `expand_context` stage as a tool-like action without changing the
    aggregate metric used by old headline tables.
    """
    telemetry = result.telemetry or {}
    available = list(available_tools or telemetry.get("available_tools") or [])
    sequence: list[str] = []
    failed_count = 0

    for step in result.trace.steps:
        if step.action == "tool_error":
            failed_count += 1
            sequence.append(_canonical_tool_name(step.tool or step.stage))
            continue
        if step.action == "tool_call" or step.tool is not None:
            sequence.append(_canonical_tool_name(step.tool or step.stage))
            continue
        if step.stage == "expand_context" and step.action != "passthrough":
            sequence.append("expand_context")

    selected_tools = list(dict.fromkeys(sequence))
    useful_count = len(sequence) if sequence and evidence_reward > 0 else 0
    irrelevant_count = len(sequence) if sequence and evidence_reward <= 0 else 0

    return {
        "available_tools": available,
        "selected_tools": selected_tools,
        "tool_call_sequence": sequence,
        "failed_tool_call_count": failed_count,
        "useful_tool_call_count": useful_count,
        "irrelevant_tool_call_count": irrelevant_count,
        "answer_changed_after_tool": telemetry.get("answer_changed_after_tool"),
        "verifier_supported_after_tool": telemetry.get("verifier_supported_after_tool"),
    }


def _canonical_tool_name(name: str | None) -> str:
    if not name:
        return "unknown"
    if name == "deterministic_inspector":
        return "inspect_region"
    return name


def _error_record(example: BenchmarkExample, *, protocol: str, error: str) -> dict[str, Any]:
    return {
        "example_id": example.id,
        "protocol": protocol,
        "error": error,
        "answer_pred": None,
        "answer_gold": example.answer,
        "answer_correct": 0.0,
        "page_recall": 0.0,
        "bbox_iou": 0.0,
        "evidence_reward": 0.0,
        "is_lazy": 1,
        "available_tools": [],
        "selected_tools": [],
        "tool_call_sequence": [],
        "failed_tool_call_count": 0,
        "useful_tool_call_count": 0,
        "irrelevant_tool_call_count": 0,
        "answer_changed_after_tool": None,
        "verifier_supported_after_tool": None,
        "tool_calls": 0,
        "tokens_in": 0,
        "tokens_out": 0,
        "usd": 0.0,
        "latency_ms": 0,
        "citations": [],
        "cache_hit": False,
    }


def _should_abort_eval_on_error(
    exc: Exception,
    *,
    strict_layout_detection: bool = False,
) -> bool:
    """Return True for infrastructure failures that invalidate the run.

    Ordinary per-row model exceptions remain error rows so local development
    can continue. Provider throttling/quota failures are different: once the
    retry wrapper gives up, counting those rows as benchmark failures creates a
    misleading accuracy artifact instead of a valid scientific run.
    """

    if is_model_throttle_error(exc):
        return True
    return strict_layout_detection and isinstance(
        exc, (LayoutEndpointUnavailable, StubResponseError)
    )


def _aggregate_stages(per_example: list[dict[str, Any]]):
    """Aggregate the per-example `stages` blocks into one bundle.

    Each per-example record carries a `stages` dict (set by
    `_score_and_record`). We rehydrate them as `StageMetrics` so the
    aggregator can do per-field means without re-typing every key.
    Records that pre-date the `stages` field (older cached predictions)
    fall through to the default `StageMetrics()` so resume runs don't
    crash mid-aggregation — the aggregate just won't include them.
    """
    bundles: list[StageMetrics] = []
    for r in per_example:
        raw = r.get("stages")
        if raw is None:
            bundles.append(StageMetrics())
            continue
        try:
            bundles.append(StageMetrics.model_validate(raw))
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("stage metrics deserialize failed for %s: %s", r.get("example_id"), exc)
            bundles.append(StageMetrics())
    return aggregate_stage_metrics(bundles)


def _safe_id(example_id: str) -> str:
    """Filesystem-safe stem for an example id. Short sha fallback for oddly-shaped ids."""
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in example_id)
    if len(safe) > 120 or not safe:
        return hashlib.sha1(example_id.encode("utf-8")).hexdigest()[:16]
    return safe


def _env_snapshot() -> dict[str, Any]:
    """Capture just enough env state to diagnose a run later."""
    return {
        "has_openai_key": bool(os.environ.get("OPENAI_API_KEY")),
        "has_anthropic_key": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "has_gemini_key": bool(
            os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        ),
        "has_hf_token": bool(os.environ.get("HF_TOKEN")),
        "tier_overrides": {k: v for k, v in os.environ.items() if k.startswith("FOCUSPARSE_TIER_")},
    }


__all__ = ["run_simple_eval", "run_focus_eval"]
