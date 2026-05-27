"""Static FocusParse pipeline demo builder.

The demo is intentionally a presentation layer over existing run outputs. It
does not call models, change trace schemas, or depend on stale crop cache refs:
page images are copied from the current staging root and crops are regenerated
from recorded normalized boxes.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image

from focusparse.traces.viewer import DEFAULT_STAGING_ROOT, example_id_to_doc_stem, find_page_image

DEFAULT_SPEC_DIR = Path(
    "results/hf/sprint-2026-05-15/answer-shape-normalizer-oai-run2/"
    "focusparse_focus_agentic_multi_page_8c5e328d"
)
DEFAULT_BENCHMARK_JSONL = Path(
    "results/audits/parser-bench-golden-audit-2026-05-11/fetch_cache/"
    "validation_3774c67f8b814392b6d04c939e904f749a3f52eb.jsonl"
)
DEFAULT_OUTPUT_DIR = Path("results/trace_viewer/pipeline-demo")

CURATED_EXAMPLE_IDS = [
    "dat-Arm_EE382N_4-0001",
    "dat-adrv9040-reference-manual-ug-2192-0041",
    "dat-infineon-applicationnote-linear-mode-operation-safe-operation-diagram-mosfets-applicationnotes-en-0018",
    "dat-ads1299-0023",
    "dat-DS5091D-00-0036",
    "fin-10-K-0036",
    "fin-bis_qr_2025_mar-0050",
    "fin-boe_fsr_2024_jun-0007",
    "fin-bis_ar_2024-0062",
    "fin-fed_fsr_2023_apr-0052",
]

STAGE_ORDER = [
    "plan",
    "route_pages",
    "localize",
    "rerank",
    "inspect",
    "expand_context",
    "answer",
    "verify",
]

STAGE_META: dict[str, dict[str, str]] = {
    "plan": {
        "label": "PLAN",
        "title": "Question plan and answer contract",
        "why": "The harness fixes the target answer shape before it spends visual budget.",
        "saw": "Question text, requested evidence style, answer type, and rough search terms.",
    },
    "route_pages": {
        "label": "ROUTE_PAGES",
        "title": "Cheap page routing",
        "why": "The agent narrows a long document to pages worth localizing.",
        "saw": "FTS/BM25 page candidates, page tiles, and plan-derived keywords.",
    },
    "localize": {
        "label": "LOCALIZE",
        "title": "Layout-driven candidate regions",
        "why": "High recall here sets the ceiling for later reasoning.",
        "saw": "Detected tables, charts, captions, and visual elements as bbox candidates.",
    },
    "rerank": {
        "label": "RERANK",
        "title": "Visual/text relevance reranking",
        "why": "The harness spends expensive inspection calls on fewer, sharper regions.",
        "saw": "Candidate regions rescored against the question and the planned evidence need.",
    },
    "inspect": {
        "label": "INSPECT",
        "title": "Tool inspection into evidence packets",
        "why": "Raw page regions become the structured packet contract passed to the reasoner.",
        "saw": "Crops, OCR snippets, text-layer snippets, chart extracts, and provenance tags.",
    },
    "expand_context": {
        "label": "EXPAND_CONTEXT",
        "title": "Attach linked context",
        "why": "Adjacent titles, captions, legends, and rows often disambiguate the crop.",
        "saw": "Neighbor packets, linked snippets, and extra context around selected evidence.",
    },
    "answer": {
        "label": "ANSWER",
        "title": "Citation-grounded answer",
        "why": "The frontier reasoner only sees packets, not the whole document.",
        "saw": "Evidence packets, citation boxes, answer history, and answer-shape constraints.",
    },
    "verify": {
        "label": "VERIFY",
        "title": "Verifier and retry decision",
        "why": "A mid-tier verifier checks whether the cited answer satisfies the contract.",
        "saw": "Predicted answer, citations, verifier rationale, retry action, and gold boxes.",
    },
}


@dataclass(frozen=True)
class DemoBuildResult:
    """Summary returned by the demo build entrypoint."""

    output_dir: Path
    example_count: int
    asset_count: int


@dataclass
class PageAsset:
    """Internal page asset record with an absolute source for crop generation."""

    page: int
    src: str
    abs_path: Path
    width: int
    height: int

    def public(self) -> dict[str, Any]:
        return {
            "page": self.page,
            "src": self.src,
            "width": self.width,
            "height": self.height,
        }


class AssetContext:
    """Copies current page images and materializes crop PNGs for one bundle."""

    def __init__(self, output_dir: Path, staging_root: Path) -> None:
        self.output_dir = output_dir
        self.staging_root = staging_root
        self.page_cache: dict[tuple[str, int], PageAsset] = {}
        self.assets_written: set[str] = set()
        for name in ("pages", "crops", "tiles"):
            (self.output_dir / "assets" / name).mkdir(parents=True, exist_ok=True)

    @property
    def count(self) -> int:
        return len(self.assets_written)

    def page_asset(self, example_id: str, page: int) -> PageAsset | None:
        key = (example_id, page)
        if key in self.page_cache:
            return self.page_cache[key]
        page_path = find_page_image(example_id, page, staging_root=self.staging_root)
        if page_path is None:
            return None
        out = self.output_dir / "assets" / "pages" / f"{safe_slug(example_id)}_p{page:04d}.png"
        if not out.is_file():
            shutil.copyfile(page_path, out)
        with Image.open(out) as img:
            width, height = img.size
        rel = _rel(self.output_dir, out)
        self.assets_written.add(rel)
        asset = PageAsset(page=page, src=rel, abs_path=out, width=width, height=height)
        self.page_cache[key] = asset
        return asset

    def crop_asset(
        self,
        *,
        example_id: str,
        page: int,
        bbox_norm: list[float],
        name: str,
    ) -> str | None:
        page_asset = self.page_asset(example_id, page)
        if page_asset is None:
            return None
        out = (
            self.output_dir
            / "assets"
            / "crops"
            / f"{safe_slug(example_id)}_p{page:04d}_{safe_slug(name)[:60]}.png"
        )
        if crop_page_image(page_asset.abs_path, bbox_norm, out):
            rel = _rel(self.output_dir, out)
            self.assets_written.add(rel)
            return rel
        return None

    def tile_assets(self, spec_dir: Path, example_id: str) -> list[dict[str, Any]]:
        tiles_dir = spec_dir / "tiles"
        if not tiles_dir.is_dir():
            return []
        copied = []
        for path in sorted(tiles_dir.glob(f"{example_id}_tiled_*.png")):
            out = self.output_dir / "assets" / "tiles" / f"{safe_slug(path.stem)}.png"
            if not out.is_file():
                shutil.copyfile(path, out)
            rel = _rel(self.output_dir, out)
            self.assets_written.add(rel)
            with Image.open(out) as img:
                width, height = img.size
            copied.append({"src": rel, "width": width, "height": height, "label": path.stem})
        return copied


def build_pipeline_demo(
    *,
    spec_dir: Path = DEFAULT_SPEC_DIR,
    benchmark_jsonl: Path | None = DEFAULT_BENCHMARK_JSONL,
    staging_root: Path = DEFAULT_STAGING_ROOT,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    example_ids: list[str] | None = None,
    limit: int | None = None,
) -> DemoBuildResult:
    """Build the Vercel-ready static bundle."""

    spec_dir = Path(spec_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    records = load_prediction_records(spec_dir)
    selected_ids = select_example_ids(records, requested_example_ids=example_ids, limit=limit)
    records_by_id = {_example_id(r): r for r in records}
    benchmark = load_benchmark_lookup(benchmark_jsonl) if benchmark_jsonl else {}
    run_meta = load_run_meta(spec_dir)
    assets = AssetContext(output_dir, Path(staging_root))

    examples = [
        build_example(
            records_by_id[example_id],
            benchmark.get(example_id, {}),
            spec_dir=spec_dir,
            assets=assets,
        )
        for example_id in selected_ids
        if example_id in records_by_id
    ]

    data = {
        "generatedAt": datetime.now(UTC).isoformat(),
        "sourceRun": str(spec_dir),
        "benchmarkJsonl": str(benchmark_jsonl) if benchmark_jsonl else None,
        "stagingRoot": "<focusparse-hf-staging>",
        "stageOrder": STAGE_ORDER,
        "stageMeta": STAGE_META,
        "run": run_meta,
        "examples": examples,
    }
    write_static_bundle(data, output_dir)
    return DemoBuildResult(
        output_dir=output_dir, example_count=len(examples), asset_count=assets.count
    )


def load_prediction_records(spec_dir: Path) -> list[dict[str, Any]]:
    """Load per-example prediction records, preferring `per_example.jsonl`."""

    per_example = Path(spec_dir) / "per_example.jsonl"
    if per_example.is_file():
        return [row for row in _read_jsonl(per_example) if _example_id(row)]

    predictions_dir = Path(spec_dir) / "predictions"
    if not predictions_dir.is_dir():
        raise FileNotFoundError(f"No per_example.jsonl or predictions/ under {spec_dir}")
    records = []
    for path in sorted(predictions_dir.glob("*.json")):
        try:
            record = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        record.setdefault("artifact_id", path.stem)
        if _example_id(record):
            records.append(record)
    return records


def load_run_meta(spec_dir: Path) -> dict[str, Any]:
    run_json = Path(spec_dir) / "run.json"
    if not run_json.is_file():
        return {}
    try:
        run = json.loads(run_json.read_text())
    except json.JSONDecodeError:
        return {}
    aggregate = run.get("aggregate") or {}
    return {
        "runId": run.get("run_id") or run.get("id") or Path(spec_dir).name,
        "agent": run.get("agent"),
        "protocol": run.get("protocol"),
        "n": aggregate.get("n"),
        "accuracy": aggregate.get("accuracy"),
        "pageRecallMean": aggregate.get("page_recall_mean"),
        "bboxIouMean": aggregate.get("bbox_iou_mean"),
        "evidenceRewardMean": aggregate.get("evidence_reward_mean"),
        "lazyAnswerRate": aggregate.get("lazy_answer_rate"),
        "usdTotal": aggregate.get("usd_total"),
        "usdPerCorrect": aggregate.get("usd_per_correct"),
    }


def load_benchmark_lookup(path: Path) -> dict[str, dict[str, Any]]:
    """Load question/gold metadata keyed by example id."""

    lookup = {}
    path = Path(path)
    if not path.is_file():
        return lookup
    for row in _read_jsonl(path):
        example_id = row.get("id") or row.get("example_id")
        if not example_id:
            continue
        lookup[str(example_id)] = {
            "id": example_id,
            "question": row.get("question") or row.get("query"),
            "answer": row.get("answer") or row.get("gold_answer"),
            "answer_type": row.get("answer_type"),
            "supporting_pages": coerce_int_list(row.get("supporting_pages")),
            "supporting_bboxes": coerce_bbox_list(row.get("supporting_bboxes")),
            "alternate_bboxes": coerce_bbox_list(row.get("alternate_bboxes")),
        }
    return lookup


def select_example_ids(
    records: list[dict[str, Any]],
    *,
    requested_example_ids: list[str] | None = None,
    limit: int | None = None,
) -> list[str]:
    """Select repeatable examples, defaulting to the curated hard set."""

    available = {_example_id(record) for record in records}
    desired = requested_example_ids or CURATED_EXAMPLE_IDS
    selected = [example_id for example_id in desired if example_id in available]
    if limit is not None:
        selected = selected[: max(0, limit)]
    return selected


def normalize_bbox(bbox: Any, image_size: tuple[int, int]) -> list[float] | None:
    """Return a clamped normalized bbox from either normalized or pixel coords."""

    coords = bbox_from_any(bbox)
    if coords is None:
        return None
    width, height = image_size
    if max(coords) > 1.5:
        if width <= 0 or height <= 0:
            return None
        coords = [coords[0] / width, coords[1] / height, coords[2] / width, coords[3] / height]
    x0, y0, x1, y1 = coords
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    clamped = [
        max(0.0, min(1.0, x0)),
        max(0.0, min(1.0, y0)),
        max(0.0, min(1.0, x1)),
        max(0.0, min(1.0, y1)),
    ]
    if clamped[2] <= clamped[0] or clamped[3] <= clamped[1]:
        return None
    return clamped


def crop_page_image(
    page_path: Path, bbox_norm: list[float], output_path: Path, pad: float = 0.01
) -> bool:
    """Crop one normalized box from a page image and write a PNG asset."""

    bbox = normalize_bbox(bbox_norm, (1, 1))
    if bbox is None:
        return False
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(page_path) as img:
        width, height = img.size
        x0 = max(0, int((bbox[0] - pad) * width))
        y0 = max(0, int((bbox[1] - pad) * height))
        x1 = min(width, int((bbox[2] + pad) * width))
        y1 = min(height, int((bbox[3] + pad) * height))
        if x1 <= x0 or y1 <= y0:
            return False
        img.crop((x0, y0, x1, y1)).save(output_path)
    return True


def build_example(
    record: dict[str, Any],
    benchmark_row: dict[str, Any],
    *,
    spec_dir: Path,
    assets: AssetContext,
) -> dict[str, Any]:
    example_id = _example_id(record)
    trace = record.get("trace") or {}
    debug_events = trace.get("debug_events") if isinstance(trace, dict) else []
    debug_events = debug_events if isinstance(debug_events, list) else []
    steps = trace.get("steps") if isinstance(trace, dict) else []
    steps = steps if isinstance(steps, list) else []
    question = (
        benchmark_row.get("question")
        or (trace.get("question") if isinstance(trace, dict) else None)
        or record.get("question")
    )
    answer_gold = record.get("answer_gold") or benchmark_row.get("answer")
    citations = record.get("citations") if isinstance(record.get("citations"), list) else []
    gold_overlays = _gold_overlays(example_id, benchmark_row, assets)
    citation_overlays = _citation_overlays(example_id, citations, assets)
    tile_assets = assets.tile_assets(spec_dir, example_id)

    stages = {
        stage: _build_stage(
            stage,
            example_id=example_id,
            steps=steps,
            debug_events=debug_events,
            record=record,
            benchmark_row=benchmark_row,
            assets=assets,
            gold_overlays=gold_overlays,
            citation_overlays=citation_overlays,
            tile_assets=tile_assets,
        )
        for stage in STAGE_ORDER
    }

    example_pages = [
        page_asset.public()
        for (cached_id, _page), page_asset in sorted(
            assets.page_cache.items(), key=lambda item: item[0]
        )
        if cached_id == example_id
    ]

    return {
        "id": example_id,
        "title": _title_for_example(example_id),
        "domain": _domain_label(record.get("domain") or example_id.split("-", 1)[0]),
        "docStem": example_id_to_doc_stem(example_id),
        "question": question,
        "answerPred": record.get("answer_pred"),
        "answerGold": answer_gold,
        "answerCorrect": record.get("answer_correct"),
        "isLazy": record.get("is_lazy"),
        "metrics": {
            "pageRecall": record.get("page_recall"),
            "bboxIou": record.get("bbox_iou"),
            "evidenceReward": record.get("evidence_reward"),
            "toolCalls": record.get("tool_calls"),
            "tokensIn": record.get("tokens_in"),
            "tokensOut": record.get("tokens_out"),
            "usd": record.get("usd"),
            "latencyMs": record.get("latency_ms"),
            "retriesUsed": record.get("retries_used"),
            "evidenceRetries": record.get("evidence_retries"),
            "loopTermination": record.get("loop_termination"),
        },
        "toolUse": _tool_use_summary(steps, debug_events),
        "pages": example_pages,
        "tiles": tile_assets,
        "stages": stages,
    }


def write_static_bundle(data: dict[str, Any], output_dir: Path) -> None:
    """Write index, CSS, JS, data, and Vercel config."""

    output_dir = Path(output_dir)
    assets_dir = output_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "index.html").write_text(HTML_TEXT, encoding="utf-8")
    (assets_dir / "styles.css").write_text(CSS_TEXT, encoding="utf-8")
    data_text = "window.FOCUSPARSE_DEMO_DATA = "
    data_text += json.dumps(data, ensure_ascii=True, separators=(",", ":"), default=str)
    data_text += ";\n"
    (assets_dir / "demo-data.js").write_text(data_text, encoding="utf-8")
    (assets_dir / "demo.js").write_text(JS_TEXT, encoding="utf-8")
    (output_dir / "vercel.json").write_text(
        json.dumps({"cleanUrls": True, "trailingSlash": False}, indent=2) + "\n",
        encoding="utf-8",
    )


def _build_stage(
    stage: str,
    *,
    example_id: str,
    steps: list[dict[str, Any]],
    debug_events: list[dict[str, Any]],
    record: dict[str, Any],
    benchmark_row: dict[str, Any],
    assets: AssetContext,
    gold_overlays: list[dict[str, Any]],
    citation_overlays: list[dict[str, Any]],
    tile_assets: list[dict[str, Any]],
) -> dict[str, Any]:
    stage_steps = [step for step in steps if step.get("stage") == stage]
    stage_events = [event for event in debug_events if event.get("stage") == stage]
    overlays = _stage_overlays(stage, example_id, stage_events, assets)
    if stage in {"answer", "verify"}:
        overlays = [*overlays, *citation_overlays, *gold_overlays]
    elif stage in {"localize", "rerank", "inspect", "expand_context"}:
        stage_pages = {overlay["page"] for overlay in overlays}
        overlays = [
            *overlays,
            *[overlay for overlay in citation_overlays if overlay["page"] in stage_pages],
            *[overlay for overlay in gold_overlays if overlay["page"] in stage_pages],
        ]

    pages = _stage_page_assets(stage, example_id, stage_steps, stage_events, overlays, assets)
    crops = _stage_crops(stage, example_id, overlays, assets)
    context_cards = _linked_context_cards(stage, stage_events)
    logs = _stage_logs(stage_steps, stage_events, record, benchmark_row)
    return {
        "id": stage,
        "label": STAGE_META[stage]["label"],
        "title": STAGE_META[stage]["title"],
        "why": STAGE_META[stage]["why"],
        "saw": STAGE_META[stage]["saw"],
        "whatHappened": _stage_happened(stage, stage_steps, stage_events, record),
        "whyItMattered": _stage_mattered(stage, record),
        "agentSaw": _stage_saw(stage, stage_steps, stage_events, overlays, crops, tile_assets),
        "pages": [page.public() for page in pages],
        "overlays": overlays,
        "crops": [*crops, *context_cards],
        "logs": logs,
    }


def _stage_overlays(
    stage: str,
    example_id: str,
    stage_events: list[dict[str, Any]],
    assets: AssetContext,
) -> list[dict[str, Any]]:
    if stage == "localize":
        events = [event for event in stage_events if event.get("event_type") == "candidate_regions"]
        return _candidate_overlays(example_id, events[:1], assets, "candidate")
    if stage == "rerank":
        events = [event for event in stage_events if event.get("event_type") == "candidate_regions"]
        return _candidate_overlays(example_id, events[-1:], assets, "candidate")
    if stage in {"inspect", "expand_context"}:
        events = [event for event in stage_events if event.get("event_type") == "evidence_packets"]
        return _packet_overlays(example_id, events[-1:], assets)
    return []


def _candidate_overlays(
    example_id: str,
    events: list[dict[str, Any]],
    assets: AssetContext,
    kind: str,
) -> list[dict[str, Any]]:
    overlays = []
    for event in events:
        for idx, item in enumerate(_payload_items(event, "regions")):
            page = _int_or_none(item.get("page"))
            if page is None:
                continue
            page_asset = assets.page_asset(example_id, page)
            bbox = _normalized_for_asset(item.get("bbox_norm") or item.get("bbox"), page_asset)
            if bbox is None:
                continue
            score = item.get("relevance") or item.get("score") or item.get("confidence")
            label = item.get("region_type") or item.get("region_id") or f"candidate {idx + 1}"
            overlays.append(
                {
                    "id": item.get("region_id") or f"candidate-{idx + 1}",
                    "kind": kind,
                    "page": page,
                    "bbox": bbox,
                    "label": str(label),
                    "score": score,
                    "text": _best_snippet(item),
                    "rank": idx + 1,
                }
            )
    return overlays


def _packet_overlays(
    example_id: str,
    events: list[dict[str, Any]],
    assets: AssetContext,
) -> list[dict[str, Any]]:
    overlays = []
    for event in events:
        for idx, item in enumerate(_payload_items(event, "packets")):
            page = _int_or_none(item.get("page"))
            if page is None:
                continue
            page_asset = assets.page_asset(example_id, page)
            bbox = _normalized_for_asset(item.get("bbox_norm") or item.get("bbox"), page_asset)
            if bbox is None:
                continue
            label = item.get("packet_id") or item.get("region_type") or f"packet {idx + 1}"
            overlays.append(
                {
                    "id": item.get("packet_id") or f"packet-{idx + 1}",
                    "kind": "selected",
                    "page": page,
                    "bbox": bbox,
                    "label": str(label),
                    "score": item.get("confidence"),
                    "text": _best_snippet(item),
                    "rank": idx + 1,
                    "tool": item.get("provenance_tool"),
                }
            )
    return overlays


def _citation_overlays(
    example_id: str,
    citations: list[dict[str, Any]],
    assets: AssetContext,
) -> list[dict[str, Any]]:
    overlays = []
    for idx, citation in enumerate(citations):
        page = _int_or_none(citation.get("page"))
        if page is None:
            continue
        page_asset = assets.page_asset(example_id, page)
        bbox = _normalized_for_asset(citation.get("bbox") or citation.get("bbox_norm"), page_asset)
        if bbox is None:
            continue
        overlays.append(
            {
                "id": f"citation-{idx + 1}",
                "kind": "citation",
                "page": page,
                "bbox": bbox,
                "label": f"citation {idx + 1}",
                "score": citation.get("confidence"),
                "text": _best_snippet(citation),
                "rank": idx + 1,
            }
        )
    return overlays


def _gold_overlays(
    example_id: str,
    benchmark_row: dict[str, Any],
    assets: AssetContext,
) -> list[dict[str, Any]]:
    overlays = []
    for idx, item in enumerate(benchmark_row.get("supporting_bboxes") or []):
        page = _int_or_none(item.get("page"))
        if page is None:
            continue
        page_asset = assets.page_asset(example_id, page)
        bbox = _normalized_for_asset(item, page_asset)
        if bbox is None:
            continue
        overlays.append(
            {
                "id": f"gold-{idx + 1}",
                "kind": "gold",
                "page": page,
                "bbox": bbox,
                "label": f"gold {idx + 1}",
                "score": None,
                "text": benchmark_row.get("answer"),
                "rank": idx + 1,
            }
        )
    return overlays


def _stage_page_assets(
    stage: str,
    example_id: str,
    stage_steps: list[dict[str, Any]],
    stage_events: list[dict[str, Any]],
    overlays: list[dict[str, Any]],
    assets: AssetContext,
) -> list[PageAsset]:
    pages = [
        overlay["page"] for overlay in overlays if _int_or_none(overlay.get("page")) is not None
    ]
    if stage == "route_pages":
        for step in stage_steps:
            pages.extend(coerce_int_list((step.get("args") or {}).get("candidate_pages")))
        for event in stage_events:
            payload = event.get("payload") or {}
            pages.extend(coerce_int_list(payload.get("candidate_pages")))
    if stage == "plan" and not pages:
        for step in stage_steps:
            pages.extend(coerce_int_list((step.get("args") or {}).get("candidate_pages")))
    unique_pages = _ordered_unique_ints(pages)[:6]
    resolved = []
    for page in unique_pages:
        asset = assets.page_asset(example_id, page)
        if asset is not None:
            resolved.append(asset)
    return resolved


def _stage_crops(
    stage: str,
    example_id: str,
    overlays: list[dict[str, Any]],
    assets: AssetContext,
) -> list[dict[str, Any]]:
    if stage in {"plan", "route_pages"}:
        return []
    max_crops = 8 if stage in {"localize", "rerank", "inspect", "expand_context"} else 6
    crop_cards = []
    for idx, overlay in enumerate(overlays[:max_crops]):
        src = assets.crop_asset(
            example_id=example_id,
            page=int(overlay["page"]),
            bbox_norm=overlay["bbox"],
            name=f"{stage}_{idx + 1}_{overlay['kind']}",
        )
        crop_cards.append(
            {
                "src": src,
                "label": overlay.get("label"),
                "kind": overlay.get("kind"),
                "page": overlay.get("page"),
                "score": overlay.get("score"),
                "text": overlay.get("text"),
            }
        )
    return crop_cards


def _linked_context_cards(stage: str, stage_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if stage != "expand_context":
        return []
    cards = []
    for event in stage_events:
        if event.get("event_type") != "evidence_packets":
            continue
        for item in _payload_items(event, "packets"):
            linked_types = item.get("linked_neighbor_types") or []
            snippets = []
            for key in ("text_layer_snippet", "ocr_snippet", "chart_csv"):
                if item.get(key):
                    snippets.append(f"{key}: {_shorten(item[key], 420)}")
            if linked_types or snippets:
                cards.append(
                    {
                        "src": None,
                        "label": item.get("packet_id") or "linked context",
                        "kind": "context",
                        "page": item.get("page"),
                        "score": item.get("confidence"),
                        "text": "; ".join([f"neighbors={linked_types}", *snippets]),
                    }
                )
    return cards[:10]


def _stage_logs(
    stage_steps: list[dict[str, Any]],
    stage_events: list[dict[str, Any]],
    record: dict[str, Any],
    benchmark_row: dict[str, Any],
) -> list[dict[str, Any]]:
    logs = []
    for step in stage_steps:
        logs.append(
            {
                "kind": "step",
                "stage": step.get("stage"),
                "action": step.get("action"),
                "tool": step.get("tool"),
                "tier": step.get("tier"),
                "confidence": step.get("confidence"),
                "tokens": {
                    "in": step.get("tokens_in"),
                    "out": step.get("tokens_out"),
                    "usd": step.get("usd"),
                    "latencyMs": step.get("latency_ms"),
                },
                "args": _trim_json(step.get("args") or {}),
                "observation": _shorten(step.get("obs_summary"), 1200),
            }
        )
    for event in stage_events:
        logs.append(
            {
                "kind": "debug_event",
                "stage": event.get("stage"),
                "eventType": event.get("event_type"),
                "payload": _trim_json(event.get("payload") or {}),
            }
        )
    if not logs and stage_steps == [] and stage_events == []:
        logs.append(
            {
                "kind": "record_summary",
                "payload": {
                    "answerPred": record.get("answer_pred"),
                    "answerGold": record.get("answer_gold") or benchmark_row.get("answer"),
                    "answerCorrect": record.get("answer_correct"),
                    "pageRecall": record.get("page_recall"),
                    "bboxIou": record.get("bbox_iou"),
                    "evidenceReward": record.get("evidence_reward"),
                },
            }
        )
    return logs


def _tool_use_summary(
    steps: list[dict[str, Any]],
    debug_events: list[dict[str, Any]],
) -> dict[str, Any]:
    tools = [step.get("tool") for step in steps if step.get("tool")]
    useful_tools = []
    for step in steps:
        if step.get("tool") and step.get("obs_summary"):
            useful_tools.append(step.get("tool"))
    verifier_events = [event for event in debug_events if event.get("stage") == "verify"]
    return {
        "available": [
            "inspect_region(image)",
            "inspect_region(element)",
            "inspect_region(region)",
            "get_text_layer",
            "expand_context",
            "run_python",
            "chart_to_table",
        ],
        "called": _ordered_unique([str(tool) for tool in tools]),
        "useful": _ordered_unique([str(tool) for tool in useful_tools]),
        "sequence": [
            {
                "stage": step.get("stage"),
                "action": step.get("action"),
                "tool": step.get("tool"),
                "confidence": step.get("confidence"),
            }
            for step in steps
            if step.get("tool") or step.get("stage") in STAGE_ORDER
        ],
        "verifierEvents": [_trim_json(event.get("payload") or {}) for event in verifier_events],
    }


def _stage_happened(
    stage: str,
    stage_steps: list[dict[str, Any]],
    stage_events: list[dict[str, Any]],
    record: dict[str, Any],
) -> str:
    if stage == "plan":
        summary = _first_nonempty([step.get("obs_summary") for step in stage_steps])
        return _shorten(summary, 520) or "The planner established the answer contract."
    if stage == "route_pages":
        pages = []
        for step in stage_steps:
            pages.extend(coerce_int_list((step.get("args") or {}).get("candidate_pages")))
        return (
            f"Routed to candidate pages {pages[:8]}."
            if pages
            else "Page routing evidence was recorded."
        )
    if stage in {"localize", "rerank"}:
        count = sum(len(_payload_items(event, "regions")) for event in stage_events)
        return f"Produced {count} candidate region records for this stage."
    if stage in {"inspect", "expand_context"}:
        count = sum(len(_payload_items(event, "packets")) for event in stage_events)
        return f"Built {count} evidence packet records with crops and snippets."
    if stage == "answer":
        return f"Answered `{record.get('answer_pred')}` from packet evidence."
    if stage == "verify":
        retries = record.get("retries_used") or 0
        return f"Verifier completed with retries_used={retries} and termination={record.get('loop_termination')}."
    return "Stage recorded trace data."


def _stage_mattered(stage: str, record: dict[str, Any]) -> str:
    if stage in {"localize", "rerank", "inspect", "expand_context"}:
        return (
            f"This stage affects page recall={_fmt(record.get('page_recall'))}, "
            f"bbox IoU={_fmt(record.get('bbox_iou'))}, and "
            f"evidence reward={_fmt(record.get('evidence_reward'))}."
        )
    if stage == "answer":
        return "Answering is constrained to evidence packets, which makes failures inspectable."
    if stage == "verify":
        return (
            "Verifier decisions explain whether the run stopped, retried, or preserved an answer."
        )
    return STAGE_META[stage]["why"]


def _stage_saw(
    stage: str,
    stage_steps: list[dict[str, Any]],
    stage_events: list[dict[str, Any]],
    overlays: list[dict[str, Any]],
    crops: list[dict[str, Any]],
    tile_assets: list[dict[str, Any]],
) -> str:
    if stage == "route_pages" and tile_assets:
        return f"Page tile assets available: {len(tile_assets)} mixed summary images."
    if overlays:
        kinds = ", ".join(f"{kind}:{count}" for kind, count in _count_by_kind(overlays).items())
        return f"Visible overlays on staged page PNGs: {kinds}."
    if crops:
        return f"Crop/context carousel contains {len(crops)} items."
    if stage_steps:
        tools = [step.get("tool") for step in stage_steps if step.get("tool")]
        return f"Recorded {len(stage_steps)} step(s); tools={tools or ['none']}."
    if stage_events:
        return f"Recorded {len(stage_events)} debug event(s)."
    return STAGE_META[stage]["saw"]


def _payload_items(event: dict[str, Any], key: str) -> list[dict[str, Any]]:
    payload = event.get("payload") or {}
    items = payload.get(key) or payload.get("regions" if key == "packets" else "packets") or []
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _normalized_for_asset(value: Any, page_asset: PageAsset | None) -> list[float] | None:
    if page_asset is None:
        return normalize_bbox(value, (1, 1))
    return normalize_bbox(value, (page_asset.width, page_asset.height))


def bbox_from_any(value: Any) -> list[float] | None:
    if isinstance(value, dict):
        try:
            return [float(value["x0"]), float(value["y0"]), float(value["x1"]), float(value["y1"])]
        except (KeyError, TypeError, ValueError):
            return None
    if isinstance(value, (list, tuple)) and len(value) == 4:
        try:
            return [float(v) for v in value]
        except (TypeError, ValueError):
            return None
    return None


def coerce_bbox_list(value: Any) -> list[dict[str, Any]]:
    parsed = _json_if_string(value)
    if not isinstance(parsed, list):
        return []
    out = []
    for item in parsed:
        if isinstance(item, dict) and bbox_from_any(item) is not None:
            out.append(item)
        elif isinstance(item, (list, tuple)) and len(item) == 4:
            out.append({"page": None, "x0": item[0], "y0": item[1], "x1": item[2], "y1": item[3]})
    return out


def coerce_int_list(value: Any) -> list[int]:
    parsed = _json_if_string(value)
    if not isinstance(parsed, list):
        return []
    out = []
    for item in parsed:
        maybe = _int_or_none(item)
        if maybe is not None:
            out.append(maybe)
    return out


def safe_slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value)).strip("-") or "asset"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _example_id(record: dict[str, Any]) -> str:
    return str(record.get("example_id") or record.get("id") or "")


def _title_for_example(example_id: str) -> str:
    stem = example_id_to_doc_stem(example_id)
    suffix = example_id.rsplit("-", 1)[-1]
    return f"{stem} / {suffix}"


def _domain_label(value: Any) -> str:
    text = str(value).split(".")[-1].lower()
    if text in {"dat", "datasheet"}:
        return "datasheet"
    if text in {"fin", "finance"}:
        return "finance"
    return text


def _json_if_string(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _ordered_unique(items: list[str]) -> list[str]:
    seen = set()
    out = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _ordered_unique_ints(items: list[Any]) -> list[int]:
    seen = set()
    out = []
    for item in items:
        maybe = _int_or_none(item)
        if maybe is None or maybe in seen:
            continue
        seen.add(maybe)
        out.append(maybe)
    return out


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _best_snippet(item: dict[str, Any]) -> str | None:
    for key in (
        "needed_for",
        "reason",
        "text",
        "text_layer_snippet",
        "ocr_snippet",
        "chart_csv",
        "caption",
    ):
        if item.get(key):
            return _shorten(item[key], 360)
    return None


def _first_nonempty(values: list[Any]) -> str | None:
    for value in values:
        if value:
            return str(value)
    return None


def _shorten(value: Any, limit: int = 600) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", _scrub_text(str(value))).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 15].rstrip() + " ... [trimmed]"


def _scrub_text(text: str) -> str:
    """Remove local absolute paths before data is written to a public bundle."""

    text = re.sub(r"/Users/[^/]+/projects/FocusParse/", "<repo>/", text)
    text = re.sub(r"/Users/[^/]+/\.cache/focusparse/[^\s\"']+", "<focusparse-cache>", text)
    return text


def _trim_json(value: Any, *, max_str: int = 1500, max_list: int = 40) -> Any:
    if isinstance(value, dict):
        return {str(k): _trim_json(v, max_str=max_str, max_list=max_list) for k, v in value.items()}
    if isinstance(value, list):
        trimmed = [_trim_json(v, max_str=max_str, max_list=max_list) for v in value[:max_list]]
        if len(value) > max_list:
            trimmed.append({"_trimmed_items": len(value) - max_list})
        return trimmed
    if isinstance(value, str):
        return _shorten(value, max_str)
    return value


def _fmt(value: Any) -> str:
    if isinstance(value, int | float):
        return f"{float(value):.3f}"
    if value is None:
        return "n/a"
    return str(value)


def _count_by_kind(overlays: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for overlay in overlays:
        kind = str(overlay.get("kind") or "unknown")
        counts[kind] = counts.get(kind, 0) + 1
    return counts


def _rel(output_dir: Path, path: Path) -> str:
    return path.relative_to(output_dir).as_posix()


HTML_TEXT = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>FocusParse Pipeline Demo</title>
  <link rel="stylesheet" href="assets/styles.css">
</head>
<body>
  <main id="app" class="app-shell">
    <div class="loading">Loading FocusParse pipeline demo...</div>
  </main>
  <script src="assets/demo-data.js"></script>
  <script src="assets/demo.js"></script>
</body>
</html>
"""


CSS_TEXT = r"""
:root {
  color-scheme: light;
  --ink: #172033;
  --muted: #5d697b;
  --line: #d8dee8;
  --panel: #ffffff;
  --surface: #f6f7f9;
  --blue: #2563eb;
  --green: #0f766e;
  --amber: #b45309;
  --red: #b91c1c;
  --violet: #6d28d9;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  background: var(--surface);
  color: var(--ink);
}

button {
  font: inherit;
}

.app-shell {
  min-height: 100vh;
  display: grid;
  grid-template-columns: 300px minmax(0, 1fr);
  grid-template-rows: auto 1fr;
}

.topbar {
  grid-column: 1 / -1;
  display: flex;
  gap: 20px;
  align-items: center;
  justify-content: space-between;
  padding: 14px 18px;
  background: #101828;
  color: #fff;
}

.brand-title { margin: 0; font-size: 17px; font-weight: 700; }
.brand-subtitle { margin: 4px 0 0; color: #cbd5e1; font-size: 12px; }
.run-metrics { display: flex; flex-wrap: wrap; gap: 10px; justify-content: flex-end; }
.metric-pill {
  border: 1px solid rgba(255,255,255,0.24);
  border-radius: 6px;
  padding: 6px 8px;
  min-width: 78px;
}
.metric-pill span { display: block; color: #cbd5e1; font-size: 10px; text-transform: uppercase; }
.metric-pill strong { display: block; font-size: 13px; }

.sidebar {
  border-right: 1px solid var(--line);
  background: #fff;
  padding: 14px;
  overflow-y: auto;
  max-height: calc(100vh - 72px);
}

.sidebar h2, .panel-title {
  margin: 0 0 10px;
  font-size: 13px;
  letter-spacing: 0;
  text-transform: uppercase;
  color: var(--muted);
}

.example-button {
  display: block;
  width: 100%;
  text-align: left;
  border: 1px solid var(--line);
  background: #fff;
  border-radius: 8px;
  padding: 10px;
  margin-bottom: 8px;
  cursor: pointer;
}
.example-button.active {
  border-color: var(--blue);
  box-shadow: inset 3px 0 0 var(--blue);
}
.example-title { font-weight: 700; font-size: 13px; overflow-wrap: anywhere; }
.example-meta { color: var(--muted); font-size: 12px; margin-top: 4px; }
.status-ok { color: var(--green); font-weight: 700; }
.status-bad { color: var(--red); font-weight: 700; }

.workspace {
  min-width: 0;
  display: grid;
  grid-template-rows: auto auto 1fr;
  max-height: calc(100vh - 72px);
}

.question-panel {
  background: #fff;
  border-bottom: 1px solid var(--line);
  padding: 14px 18px;
}
.question-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.7fr) minmax(240px, 0.8fr);
  gap: 16px;
}
.question-text { margin: 0; line-height: 1.45; font-size: 15px; }
.answer-boxes {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}
.answer-box {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 8px;
  min-width: 0;
}
.answer-box span { display: block; color: var(--muted); font-size: 10px; text-transform: uppercase; }
.answer-box strong { display: block; margin-top: 4px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; overflow-wrap: anywhere; }

.stage-strip {
  display: flex;
  gap: 8px;
  padding: 10px 18px;
  overflow-x: auto;
  background: #fdfefe;
  border-bottom: 1px solid var(--line);
}
.stage-button {
  flex: 0 0 auto;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
  color: var(--ink);
  padding: 8px 10px;
  cursor: pointer;
  font-size: 12px;
  font-weight: 700;
}
.stage-button.active {
  border-color: #111827;
  background: #111827;
  color: #fff;
}

.content-grid {
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(420px, 1.3fr) minmax(360px, 0.9fr);
  gap: 0;
}

.visual-panel, .detail-panel {
  min-width: 0;
  overflow-y: auto;
  padding: 14px 18px;
}
.visual-panel { border-right: 1px solid var(--line); }

.panel {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 12px;
}

.page-tabs, .toggle-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}
.mini-button, .toggle-button {
  border: 1px solid var(--line);
  border-radius: 6px;
  background: #fff;
  padding: 6px 8px;
  cursor: pointer;
  font-size: 12px;
}
.mini-button.active, .toggle-button.active {
  border-color: var(--blue);
  color: var(--blue);
}

.page-frame {
  position: relative;
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #e9edf3;
  max-height: 62vh;
}
.page-wrap {
  position: relative;
  display: inline-block;
  min-width: 100%;
}
.page-image {
  display: block;
  width: min(100%, 920px);
  height: auto;
}
.overlay-layer {
  position: absolute;
  inset: 0;
  pointer-events: none;
}
.bbox {
  position: absolute;
  border: 2px solid;
  background: rgba(255,255,255,0.06);
}
.bbox-label {
  position: absolute;
  left: -2px;
  top: -22px;
  min-width: 26px;
  max-width: 180px;
  color: #fff;
  font-size: 11px;
  padding: 2px 5px;
  border-radius: 4px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.bbox-candidate { border-color: var(--blue); }
.bbox-candidate .bbox-label { background: var(--blue); }
.bbox-selected { border-color: var(--green); }
.bbox-selected .bbox-label { background: var(--green); }
.bbox-citation { border-color: var(--amber); }
.bbox-citation .bbox-label { background: var(--amber); }
.bbox-gold { border-color: var(--red); border-style: dashed; }
.bbox-gold .bbox-label { background: var(--red); }

.crop-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 10px;
}
.crop-card {
  border: 1px solid var(--line);
  border-radius: 8px;
  overflow: hidden;
  background: #fff;
}
.crop-card img {
  width: 100%;
  height: 130px;
  object-fit: contain;
  background: #eef2f7;
  display: block;
}
.crop-body { padding: 8px; font-size: 12px; }
.crop-label { font-weight: 700; overflow-wrap: anywhere; }
.crop-text { color: var(--muted); margin-top: 4px; line-height: 1.35; }

.narrative h3 { margin: 0 0 8px; font-size: 18px; }
.narrative dl { margin: 0; }
.narrative dt { color: var(--muted); font-size: 11px; text-transform: uppercase; margin-top: 10px; }
.narrative dd { margin: 4px 0 0; line-height: 1.45; }

.tool-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: 6px;
}
.tool-chip {
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 6px;
  font-size: 12px;
  background: #fbfcfe;
}

.log-panel pre {
  margin: 0;
  max-height: 36vh;
  overflow: auto;
  font-size: 11px;
  line-height: 1.45;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.empty {
  padding: 18px;
  color: var(--muted);
  text-align: center;
}

@media (max-width: 980px) {
  .app-shell {
    grid-template-columns: 1fr;
    grid-template-rows: auto auto 1fr;
  }
  .sidebar {
    border-right: 0;
    border-bottom: 1px solid var(--line);
    max-height: 240px;
  }
  .workspace {
    max-height: none;
  }
  .question-grid, .content-grid {
    grid-template-columns: 1fr;
  }
  .visual-panel {
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }
  .page-frame {
    max-height: 58vh;
  }
  .topbar {
    align-items: flex-start;
    flex-direction: column;
  }
  .run-metrics {
    justify-content: flex-start;
  }
}

@media (max-width: 560px) {
  .answer-boxes {
    grid-template-columns: 1fr;
  }
  .sidebar {
    max-height: 210px;
  }
  .stage-strip {
    padding: 8px;
  }
  .question-panel, .visual-panel, .detail-panel {
    padding: 10px;
  }
}
"""


JS_TEXT = r"""
const DATA = window.FOCUSPARSE_DEMO_DATA;

const state = {
  exampleIndex: 0,
  stageId: "plan",
  pageIndex: 0,
  visible: { candidate: true, selected: true, citation: true, gold: true },
};

function h(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (key === "class") node.className = value;
    else if (key === "dataset") {
      for (const [dataKey, dataValue] of Object.entries(value)) node.dataset[dataKey] = dataValue;
    } else if (key === "onclick") node.addEventListener("click", value);
    else if (key === "onload") node.addEventListener("load", value);
    else if (key === "text") node.textContent = value;
    else node.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child == null) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function fmt(value, digits = 3) {
  if (value == null || Number.isNaN(value)) return "n/a";
  if (typeof value === "number") return value.toFixed(digits);
  return String(value);
}

function money(value) {
  if (value == null || Number.isNaN(value)) return "n/a";
  return "$" + Number(value).toFixed(4);
}

function currentExample() {
  return DATA.examples[state.exampleIndex];
}

function currentStage() {
  const example = currentExample();
  return example.stages[state.stageId] || example.stages.plan;
}

function render() {
  const app = document.getElementById("app");
  app.textContent = "";
  app.append(topbar(), sidebar(), workspace());
  requestAnimationFrame(renderOverlays);
}

function topbar() {
  const run = DATA.run || {};
  return h("header", { class: "topbar" },
    h("div", {},
      h("h1", { class: "brand-title", text: "FocusParse Pipeline Demo" }),
      h("p", { class: "brand-subtitle", text: `${DATA.examples.length} curated traces from ${run.runId || "run output"}` })
    ),
    h("div", { class: "run-metrics" },
      metricPill("n", run.n),
      metricPill("accuracy", fmt(run.accuracy)),
      metricPill("page recall", fmt(run.pageRecallMean)),
      metricPill("bbox IoU", fmt(run.bboxIouMean)),
      metricPill("usd/correct", money(run.usdPerCorrect))
    )
  );
}

function metricPill(label, value) {
  return h("div", { class: "metric-pill" }, h("span", { text: label }), h("strong", { text: value ?? "n/a" }));
}

function sidebar() {
  return h("aside", { class: "sidebar" },
    h("h2", { text: "Examples" }),
    DATA.examples.map((example, index) => {
      const active = index === state.exampleIndex ? " active" : "";
      const ok = Number(example.answerCorrect) >= 1;
      return h("button", {
        class: "example-button" + active,
        dataset: { testid: `example-${example.id}` },
        onclick: () => {
          state.exampleIndex = index;
          state.stageId = "plan";
          state.pageIndex = 0;
          render();
        }
      },
        h("div", { class: "example-title", text: example.title }),
        h("div", { class: "example-meta" },
          h("span", { class: ok ? "status-ok" : "status-bad", text: ok ? "correct" : "wrong" }),
          ` | ${example.domain} | IoU ${fmt(example.metrics.bboxIou)}`
        )
      );
    })
  );
}

function workspace() {
  return h("section", { class: "workspace" }, questionPanel(), stageStrip(), contentGrid());
}

function questionPanel() {
  const example = currentExample();
  return h("div", { class: "question-panel" },
    h("div", { class: "question-grid" },
      h("p", { class: "question-text", text: example.question || "No question text available." }),
      h("div", { class: "answer-boxes" },
        answerBox("prediction", example.answerPred),
        answerBox("gold", example.answerGold)
      )
    )
  );
}

function answerBox(label, value) {
  return h("div", { class: "answer-box" }, h("span", { text: label }), h("strong", { text: value ?? "n/a" }));
}

function stageStrip() {
  return h("nav", { class: "stage-strip" },
    DATA.stageOrder.map((stageId) => {
      const meta = DATA.stageMeta[stageId] || { label: stageId };
      return h("button", {
        class: "stage-button" + (stageId === state.stageId ? " active" : ""),
        dataset: { testid: `stage-${stageId}`, stage: stageId },
        onclick: () => {
          state.stageId = stageId;
          state.pageIndex = 0;
          render();
        },
        text: meta.label
      });
    })
  );
}

function contentGrid() {
  return h("div", { class: "content-grid" },
    h("section", { class: "visual-panel" }, visualPanel(), cropPanel()),
    h("section", { class: "detail-panel" }, narrativePanel(), toolsPanel(), logPanel())
  );
}

function visualPanel() {
  const stage = currentStage();
  const pages = stage.pages || [];
  if (!pages.length) {
    return h("div", { class: "panel" }, h("div", { class: "empty", text: "No page image was needed or resolved for this stage." }));
  }
  if (state.pageIndex >= pages.length) state.pageIndex = 0;
  const page = pages[state.pageIndex];
  return h("div", { class: "panel" },
    h("div", { class: "page-tabs" },
      pages.map((p, index) => h("button", {
        class: "mini-button" + (index === state.pageIndex ? " active" : ""),
        onclick: () => {
          state.pageIndex = index;
          render();
        },
        text: `Page ${p.page}`
      }))
    ),
    overlayToggles(),
    h("div", { class: "page-frame" },
      h("div", { class: "page-wrap" },
        h("img", { class: "page-image", src: page.src, alt: `Page ${page.page}`, onload: renderOverlays }),
        h("div", { class: "overlay-layer" })
      )
    )
  );
}

function overlayToggles() {
  return h("div", { class: "toggle-row" },
    ["candidate", "selected", "citation", "gold"].map((kind) => h("button", {
      class: "toggle-button" + (state.visible[kind] ? " active" : ""),
      dataset: { testid: `toggle-${kind}` },
      onclick: () => {
        state.visible[kind] = !state.visible[kind];
        renderOverlays();
        document.querySelector(`[data-testid="toggle-${kind}"]`)?.classList.toggle("active", state.visible[kind]);
      },
      text: kind
    }))
  );
}

function renderOverlays() {
  const layer = document.querySelector(".overlay-layer");
  const img = document.querySelector(".page-image");
  if (!layer || !img || !img.complete) return;
  layer.textContent = "";
  layer.style.width = img.clientWidth + "px";
  layer.style.height = img.clientHeight + "px";
  const stage = currentStage();
  const page = (stage.pages || [])[state.pageIndex];
  if (!page) return;
  const overlays = (stage.overlays || []).filter((overlay) => overlay.page === page.page && state.visible[overlay.kind]);
  for (const overlay of overlays) {
    const [x0, y0, x1, y1] = overlay.bbox;
    const box = h("div", { class: `bbox bbox-${overlay.kind}` },
      h("div", { class: "bbox-label", text: overlay.label || overlay.kind })
    );
    box.style.left = `${x0 * img.clientWidth}px`;
    box.style.top = `${y0 * img.clientHeight}px`;
    box.style.width = `${Math.max(2, (x1 - x0) * img.clientWidth)}px`;
    box.style.height = `${Math.max(2, (y1 - y0) * img.clientHeight)}px`;
    layer.append(box);
  }
}

function cropPanel() {
  const stage = currentStage();
  const crops = stage.crops || [];
  return h("div", { class: "panel" },
    h("h2", { class: "panel-title", text: "Crops and context" }),
    crops.length ? h("div", { class: "crop-grid" }, crops.map(cropCard)) : h("div", { class: "empty", text: "No crop assets for this stage." })
  );
}

function cropCard(crop) {
  return h("article", { class: "crop-card" },
    crop.src ? h("img", { src: crop.src, alt: crop.label || "crop" }) : null,
    h("div", { class: "crop-body" },
      h("div", { class: "crop-label", text: `${crop.label || crop.kind || "context"} | p.${crop.page ?? "?"}` }),
      h("div", { class: "crop-text", text: crop.text || "" })
    )
  );
}

function narrativePanel() {
  const stage = currentStage();
  return h("div", { class: "panel narrative" },
    h("h3", { text: stage.title }),
    h("dl", {},
      h("dt", { text: "What happened" }),
      h("dd", { text: stage.whatHappened }),
      h("dt", { text: "Why it mattered" }),
      h("dd", { text: stage.whyItMattered }),
      h("dt", { text: "What the agent saw" }),
      h("dd", { text: stage.agentSaw })
    )
  );
}

function toolsPanel() {
  const example = currentExample();
  const tools = example.toolUse || {};
  return h("div", { class: "panel" },
    h("h2", { class: "panel-title", text: "Tool use" }),
    h("div", { class: "tool-list" },
      (tools.available || []).map((tool) => h("div", { class: "tool-chip", text: tool }))
    ),
    h("pre", { class: "crop-text", text: JSON.stringify({
      called: tools.called || [],
      useful: tools.useful || [],
      verifierEvents: tools.verifierEvents || []
    }, null, 2) })
  );
}

function logPanel() {
  const stage = currentStage();
  return h("div", { class: "panel log-panel" },
    h("h2", { class: "panel-title", text: "Structured logs" }),
    h("pre", { dataset: { testid: "log-panel" }, text: JSON.stringify(stage.logs || [], null, 2) })
  );
}

window.addEventListener("resize", renderOverlays);
render();
"""
