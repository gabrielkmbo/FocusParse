"""Visual smoke test for the focus pipeline.

Runs `FocusWorkflow` on one benchmark example and produces human-readable
artifacts:
  * a console dump of every `TrajectoryStep` (stage, tier, tokens, latency)
  * a PNG per supporting page with gold (green) and predicted (red) bboxes
    drawn on top
  * a JSON with the full trajectory + citations + answer

Default example: the first row of the materialized HF staging split.

Usage:
    set -a; source .env; set +a
    uv run python scripts/smoke_visualize.py
    uv run python scripts/smoke_visualize.py --example-id dat-Arm_EE382N_4-0001
    uv run python scripts/smoke_visualize.py --output-dir results/smoke-visual
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger("smoke_visualize")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--staging-dir",
        type=Path,
        default=Path.home() / ".cache" / "focusparse" / "hf_staging",
    )
    p.add_argument(
        "--example-id",
        type=str,
        default=None,
        help="Example id to run (default: first row in staging's benchmark.jsonl)",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=Path("results/smoke-visual"),
    )
    p.add_argument(
        "--protocol",
        type=str,
        default="focus_default",
    )
    return p.parse_args()


async def _run() -> int:
    args = _parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    # Deferred imports so --help works without pulling the world.
    from focusparse.models.tiers import TierRouter
    from focusparse.pipeline.workflow import FocusWorkflow
    from focusparse.utils.config import load_config

    # Mirror run_hf_eval's env-override convention: let the reasoner be
    # configurable via FOCUSPARSE_TIER_REASONER at shell level.
    config = load_config()
    tier_router = TierRouter(config)
    backend_client = tier_router.client_for("reasoner")

    bench_path = args.staging_dir / "benchmark.jsonl"
    if not bench_path.exists():
        logger.error("staging benchmark missing: %s", bench_path)
        logger.error("run `uv run python scripts/run_hf_eval.py --limit 1` first to materialize")
        return 2

    example = _load_example(bench_path, args.example_id)
    if example is None:
        logger.error("could not find example in %s", bench_path)
        return 2

    images = [_resolve_image(args.staging_dir, p) for p in (example.page_images or [])]
    logger.info("example=%s, %d image(s)", example.id, len(images))
    logger.info("question: %s", example.question)
    logger.info("gold answer: %s", example.answer)

    args.output_dir.mkdir(parents=True, exist_ok=True)

    workflow = FocusWorkflow(
        backend_client=backend_client,
        config=config,
        tier_router=tier_router,
    )
    result = await workflow.run(example, images, protocol=args.protocol)

    _print_trajectory(result.trace)
    print()
    print(f"PREDICTED ANSWER: {result.answer!r}")
    print(f"GOLD ANSWER:      {example.answer!r}")
    print(f"CITATIONS:        {result.citations}")
    print()

    _draw_bbox_overlays(example, result, images, args.output_dir)
    _dump_trajectory_json(example, result, args.output_dir)

    print(f"wrote artifacts to {args.output_dir}")
    return 0


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _load_example(bench_path: Path, example_id: str | None) -> Any | None:
    from focusparse._parser_bench import BenchmarkExample

    for line in bench_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        ex = BenchmarkExample.model_validate_json(line)
        if example_id is None or ex.id == example_id:
            return ex
    return None


def _resolve_image(staging_dir: Path, rel: str) -> Path:
    return staging_dir / rel


# ---------------------------------------------------------------------------
# Presentation
# ---------------------------------------------------------------------------


def _print_trajectory(trace) -> None:
    print()
    print("=" * 72)
    print(f"TRAJECTORY for {trace.example_id}")
    print("=" * 72)
    for step in trace.steps:
        hdr = f"[{step.step_index}] {step.stage:18s} tier={step.tier:12s} action={step.action}"
        if step.tool:
            hdr += f" tool={step.tool}"
        print(hdr)
        if step.args:
            args_str = json.dumps(step.args, default=str)
            if len(args_str) > 140:
                args_str = args_str[:137] + "..."
            print(f"    args: {args_str}")
        if step.obs_summary:
            summary = step.obs_summary.replace("\n", " ")
            if len(summary) > 140:
                summary = summary[:137] + "..."
            print(f"    obs:  {summary}")
        if step.tokens_in or step.tokens_out:
            usd = f" ${step.usd:.4f}" if step.usd else ""
            print(
                f"    llm:  tokens_in={step.tokens_in} tokens_out={step.tokens_out} "
                f"latency_ms={step.latency_ms}{usd}"
            )
        if step.confidence is not None:
            print(f"    conf: {step.confidence:.3f}")
    print("=" * 72)


def _draw_bbox_overlays(
    example: Any,
    result: Any,
    images: list[Path],
    output_dir: Path,
) -> None:
    """Draw gold (green) + predicted (red) bboxes on each page image."""
    from PIL import Image, ImageDraw

    images_by_page = _images_by_page(example, images)
    gold_by_page: dict[int, list[tuple[float, float, float, float]]] = {}
    for b in example.supporting_bboxes or []:
        gold_by_page.setdefault(b.page, []).append((b.x0, b.y0, b.x1, b.y1))

    pred_by_page: dict[int, list[tuple[float, float, float, float]]] = {}
    for c in result.citations:
        page = int(c.get("page", 0))
        bbox = c.get("bbox")
        if not (isinstance(bbox, list) and len(bbox) == 4):
            continue
        pred_by_page.setdefault(page, []).append(tuple(float(v) for v in bbox))

    # Gold bboxes are in absolute PDF-point coords (parser-bench convention).
    # Predicted bboxes are in normalized [0,1] (FocusParse convention).
    # We render each with its own coordinate interpretation.
    pages_to_render = sorted(set(images_by_page) | set(gold_by_page) | set(pred_by_page))
    for page in pages_to_render:
        img_path = images_by_page.get(page)
        if img_path is None or not img_path.exists():
            logger.warning("skipping page %d — no image at %s", page, img_path)
            continue
        with Image.open(img_path) as img:
            rgb = img.convert("RGB").copy()
        draw = ImageDraw.Draw(rgb)
        w, h = rgb.width, rgb.height

        # Gold: parser-bench encodes these in absolute PDF-point coords at
        # whatever DPI the rendered image used. The staging PNG is named
        # with _300dpi_; parser-bench renders at 300 DPI → 72pt scale =
        # 4.1667x. We accept the bbox as-is in image pixel coords, because
        # parser-bench's supporting_bboxes are already pixel-space at 300dpi
        # for the checked-in page images.
        for gx0, gy0, gx1, gy1 in gold_by_page.get(page, []):
            draw.rectangle(
                [gx0, gy0, gx1, gy1],
                outline=(0, 200, 0),
                width=8,
            )
            _label(draw, gx0, gy0, "GOLD", (0, 200, 0))

        # Predicted: normalized [0,1] → multiply by image dims.
        for px0, py0, px1, py1 in pred_by_page.get(page, []):
            draw.rectangle(
                [px0 * w, py0 * h, px1 * w, py1 * h],
                outline=(220, 0, 0),
                width=6,
            )
            _label(draw, px0 * w, py0 * h, "PRED", (220, 0, 0))

        out_path = output_dir / f"page_{page:04d}_overlay.png"
        rgb.save(out_path, format="PNG")
        logger.info("wrote %s", out_path)


def _label(draw, x: float, y: float, text: str, fill: tuple[int, int, int]) -> None:
    # Best-effort text label; no font loaded = default bitmap font
    # which is tiny but still readable.
    draw.text((max(0, x + 4), max(0, y + 4)), text, fill=fill)


def _images_by_page(example: Any, images: list[Path]) -> dict[int, Path]:
    import re

    pat = re.compile(r"_page_(\d+)")
    mapping: dict[int, Path] = {}
    for idx, img in enumerate(images):
        m = pat.search(img.name)
        page = int(m.group(1)) if m else idx + 1
        mapping[page] = img
    return mapping


def _dump_trajectory_json(example: Any, result: Any, output_dir: Path) -> None:
    payload = {
        "example_id": example.id,
        "question": example.question,
        "gold_answer": example.answer,
        "gold_pages": list(example.supporting_pages or []),
        "predicted_answer": result.answer,
        "predicted_citations": result.citations,
        "telemetry": result.telemetry,
        "trajectory": [_step_to_dict(s) for s in result.trace.steps],
    }
    out_path = output_dir / "trajectory.json"
    out_path.write_text(json.dumps(payload, default=str, indent=2))
    logger.info("wrote %s", out_path)


def _step_to_dict(step) -> dict[str, Any]:
    if is_dataclass(step):
        return asdict(step)
    # Pydantic fallback.
    for attr in ("model_dump", "dict"):
        fn = getattr(step, attr, None)
        if callable(fn):
            return fn()
    return {k: getattr(step, k, None) for k in dir(step) if not k.startswith("_")}


def main() -> int:
    # Mirror the .env loading run_hf_eval relies on.
    for env in (".env",):
        p = Path(env)
        if not p.exists():
            continue
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip("'").strip('"'))
    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())
