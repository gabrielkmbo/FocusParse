"""Coding-agent comparator for the related-work experiment program.

This is a comparator, not a FocusParse stage machine. It mirrors the
"agentic vision with code" idea: a think-act-observe loop over document/image
tools, with a strong bias toward using sandboxed Python for crop transforms,
annotation, counting, and numeric computation.

The implementation deliberately reuses FocusParse's existing tool registry and
eval artifact helpers. There is no provider-native code execution dependency;
all executable code goes through ``focusparse.tools.run_python`` so the run is
reproducible across backends.
"""

from __future__ import annotations

import json
import logging
import tempfile
import time
from collections.abc import Iterable
from contextlib import nullcontext
from pathlib import Path
from typing import TYPE_CHECKING, Any

from focusparse.eval.metrics import AggregateMetrics, aggregate, aggregate_by_domain
from focusparse.models.base import ModelClient
from focusparse.pipeline.react_agent import ReActAgent
from focusparse.pipeline.workflow import WorkflowResult
from focusparse.tools import ToolSpec, format_agent_tool_block, resolve_tool_set

if TYPE_CHECKING:
    from focusparse._parser_bench import BenchmarkExample

logger = logging.getLogger(__name__)

_DEFAULT_MAX_ITERATIONS = 7
_REQUIRED_TOOL_NAMES = ("inspect_region", "get_text_layer", "layout_detect", "run_python")


_CODING_AGENT_SYSTEM_PROMPT = (
    "You are a coding-agent comparator for document parsing. Work as a "
    "think-act-observe agent over the provided document images and tools.\n"
    "\n"
    "Output STRICT JSON in exactly one of these shapes:\n"
    '  {"thought": "...", "action": "<tool_name>", "action_input": {...}}\n'
    '  {"thought": "...", "final_answer": "...", '
    '"citations": [{"page": N, "bbox": [x0,y0,x1,y1]}]}\n'
    "\n"
    "Use the full +4 tool belt: inspect_region, get_text_layer, layout_detect, "
    "and run_python. Start by locating or reading likely evidence with "
    "layout_detect, get_text_layer, or inspect_region. Prefer run_python when "
    "a crop needs zooming, annotation, counting, chart-pixel measurement, "
    "axis/tick computation, visual comparison, or any arithmetic over observed "
    "values. The code tool only sees images passed via image_refs; feed it "
    "crop_ref values from inspect_region or new_image_refs from earlier "
    "run_python calls.\n"
    "\n"
    "Before final_answer, use at least one tool and cite observed evidence. "
    "Citations must use normalized [0,1] bbox coordinates on the source page, "
    "not crop coordinates. If tools do not reveal sufficient support, answer "
    "the literal string 'Unanswerable' with an empty citations list. Do not "
    "guess and do not add keys outside the JSON shapes above."
)


def coding_agent_tools() -> list[ToolSpec]:
    """Return the fixed full +4 tool belt for the coding-agent comparator."""

    tools = resolve_tool_set("full")
    _validate_full_tool_belt(tools)
    return tools


class CodingAgent(ReActAgent):
    """Think-act-observe comparator with an explicit code-execution bias."""

    def __init__(
        self,
        *,
        backend_client: ModelClient,
        tools: list[ToolSpec] | None = None,
        max_iterations: int = _DEFAULT_MAX_ITERATIONS,
    ) -> None:
        resolved_tools = list(tools) if tools is not None else coding_agent_tools()
        _validate_full_tool_belt(resolved_tools)
        super().__init__(
            backend_client=backend_client,
            tools=resolved_tools,
            max_iterations=max_iterations,
        )

    def _system_prompt(self) -> str:
        return (
            _CODING_AGENT_SYSTEM_PROMPT
            + "\n\n"
            + format_agent_tool_block(self.tools, mode="careful")
        )

    async def run(
        self,
        example: BenchmarkExample,
        images: list[Path],
        *,
        pdf_path: Path | None = None,
        crop_cache_dir: Path | None = None,
        text_layer_cache_dir: Path | None = None,
        layout_endpoint_url: str | None = None,
        hf_token: str | None = None,
        layout_cache_dir: Path | None = None,
    ) -> WorkflowResult:
        result = await super().run(
            example,
            images,
            pdf_path=pdf_path,
            crop_cache_dir=crop_cache_dir,
            text_layer_cache_dir=text_layer_cache_dir,
            layout_endpoint_url=layout_endpoint_url,
            hf_token=hf_token,
            layout_cache_dir=layout_cache_dir,
        )
        result.trace.plan["agent"] = "coding_agent"
        result.trace.plan["style"] = "think-act-observe-with-run-python"
        for step in result.trace.steps:
            if step.stage == "react_step":
                step.stage = "coding_agent_step"
            elif step.stage == "react_final":
                step.stage = "coding_agent_final"
        return result


async def run_coding_agent_eval(
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
    write_prediction_cache: bool = True,
    persist_intermediate_artifacts: bool = True,
) -> dict[str, Any]:
    """Run ``CodingAgent`` over examples with the standard comparator artifacts.

    ``persist_intermediate_artifacts=False`` keeps the protocol inputs the same,
    but stores tiles/crops/text/layout data in a per-example scratch directory
    that is removed after scoring. This lets full related-work runs finish on
    disk-constrained machines while retaining ``run.json`` and
    ``per_example.jsonl``.
    """

    from focusparse.eval.harness import (
        _agentic_summary_meta,
        _aggregate_stages,
        _env_snapshot,
        _error_record,
        _image_dims_by_page,
        _prepare_images,
        _resolve_pdf_path,
        _safe_id,
        _score_and_record,
        _should_abort_eval_on_error,
    )

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    pred_dir = output_dir / "predictions" if write_prediction_cache else None
    if pred_dir is not None:
        pred_dir.mkdir(parents=True, exist_ok=True)
    else:
        resume = False

    tools = coding_agent_tools()
    available_tools = [tool.name for tool in tools]
    agent = CodingAgent(backend_client=backend_client, tools=tools)

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
            artifact_context = (
                nullcontext(output_dir)
                if persist_intermediate_artifacts
                else tempfile.TemporaryDirectory(prefix=f"focusparse-{_safe_id(example.id)}-")
            )
            with artifact_context as artifact_root_raw:
                artifact_root = Path(artifact_root_raw)
                tile_dir = artifact_root / "tiles"
                crop_dir = artifact_root / "crops"
                text_layer_dir = artifact_root / "text_layer"
                layout_dir = artifact_root / "layout"
                images = _prepare_images(
                    example,
                    protocol=protocol,
                    images_root=images_root,
                    pdfs_root=pdfs_root,
                    tile_cache_dir=tile_dir,
                )
                agentic_meta: dict[str, object] | None = None
                if protocol == "agentic_multi_page":
                    agentic_meta = _agentic_summary_meta(example, images_root, pdfs_root, tile_dir)
                pdf_path = _resolve_pdf_path(pdfs_root, example) if pdfs_root else None
                try:
                    result = await agent.run(
                        example,
                        images,
                        pdf_path=pdf_path,
                        crop_cache_dir=crop_dir,
                        text_layer_cache_dir=text_layer_dir,
                        layout_cache_dir=layout_dir,
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
                    if _should_abort_eval_on_error(exc):
                        raise
                    logger.exception("Example %s failed: %s", example.id, exc)
                    record = _error_record(example, protocol=protocol, error=str(exc))

        per_example.append(record)

    aggregated: AggregateMetrics = aggregate(per_example)
    aggregated_by_domain = aggregate_by_domain(per_example)
    stage_aggregate = _aggregate_stages(per_example)

    run_manifest: dict[str, Any] = {
        "agent": "coding_agent",
        "tool_set": "full",
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
        "artifact_policy": {
            "write_prediction_cache": write_prediction_cache,
            "persist_intermediate_artifacts": persist_intermediate_artifacts,
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


def _validate_full_tool_belt(tools: list[ToolSpec]) -> None:
    names = [tool.name for tool in tools]
    if names != list(_REQUIRED_TOOL_NAMES):
        raise ValueError(
            "CodingAgent requires the full +4 tool belt in order: "
            + ", ".join(_REQUIRED_TOOL_NAMES)
        )


__all__ = ["CodingAgent", "coding_agent_tools", "run_coding_agent_eval"]
