"""Materialize a HuggingFace parser-bench split to a local staging layout.

Bridges the embedded-image HF dataset (`gabrielbo/parser-bench`) and the
FocusParse eval harness so `run_simple_eval` / `run_focus_eval` can consume
it with resolvable `page_images` paths and idempotent re-runs.

Companion to `focusparse.dataset.loader.BenchmarkLoader`:
  * Use `BenchmarkLoader._iter_hf()` for streaming (CI, smoke, one-off iteration).
  * Use `materialize_split()` here for full evals, matrix runs, and
    reproducibility — writes `<staging>/benchmark.jsonl` +
    `<staging>/data/processed/<doc>/images/*_page_NNNN_300dpi.png` and returns
    the JSONL path plus the raw `Dataset` (for fingerprinting).

Stress variants are filtered on load because the HF dataset does not publish
`original_bboxes` and `oracle_crop` would mis-score them — this matches
parser-bench's own `hf_loader` rationale.

Schema access uses the `_parser_bench` file-path shim so this module is safe
to import even when the `third_party/parser-bench/` submodule is absent;
`_row_to_example()` is the only function that actually dereferences the schema.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datasets import Dataset

logger = logging.getLogger(__name__)

_DEFAULT_REPO = "gabrielbo/parser-bench"
# HF "validation" == parser-bench "test" (our paper benchmark). See
# parser-bench's scripts/push_to_hf.py SPLIT_MAP.
_DEFAULT_SPLIT = "validation"
_HF_REQUEST_SPLIT_ALIASES = {
    "dev": "train",
    "test": "validation",
    "holdout": "test",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def materialize_split(
    staging_root: Path,
    *,
    repo_id: str = _DEFAULT_REPO,
    split: str = _DEFAULT_SPLIT,
    revision: str | None = None,
    limit: int | None = None,
    force: bool = False,
) -> tuple[Path, Dataset]:
    """Materialize an HF split into `<staging_root>/benchmark.jsonl` + images.

    Idempotent: if `benchmark.jsonl` already has the expected row count, we
    return without re-writing (individual PNGs are still skipped on disk even
    on a cold run via `out_path.exists()` gating).

    Args:
        staging_root: Directory under which we create `data/processed/...`
            and `benchmark.jsonl`. Safe to reuse across runs.
        repo_id: HuggingFace dataset repo id.
        split: HF split name. `"validation"` is our paper test benchmark.
        revision: HF dataset commit SHA. Pin for paper reproducibility.
        limit: If set, only materialize the first N rows.
        force: If True, re-materialize even when the staging dir looks complete.

    Returns:
        `(benchmark_jsonl_path, hf_dataset)`. The runner consumes the JSONL;
        the caller may pass the `Dataset` to `dataset_fingerprint()` for a
        reproducibility manifest.
    """
    # Local (inside-function) import so `hf_loader` itself is importable in
    # environments that don't have `datasets` installed.
    from datasets import load_dataset

    split = _HF_REQUEST_SPLIT_ALIASES.get(split, split)
    staging_root = Path(staging_root)
    staging_root.mkdir(parents=True, exist_ok=True)
    processed_root = staging_root / "data" / "processed"
    processed_root.mkdir(parents=True, exist_ok=True)
    benchmark_jsonl = staging_root / "benchmark.jsonl"

    logger.info(
        "Loading HF dataset %s (split=%s, revision=%s)",
        repo_id,
        split,
        revision or "HEAD",
    )
    ds = load_dataset(repo_id, split=split, revision=revision)
    ds = _filter_stress_rows(ds)
    if limit is not None:
        ds = ds.select(range(min(limit, len(ds))))

    # Idempotency gate: if JSONL already has the right row count, reuse.
    if not force and benchmark_jsonl.exists():
        with benchmark_jsonl.open() as f:
            existing = sum(1 for _ in f)
        if existing == len(ds):
            logger.info(
                "Staging %s already complete (%d rows). Reusing.",
                staging_root,
                existing,
            )
            return benchmark_jsonl, ds

    logger.info("Materializing %d rows into %s", len(ds), staging_root)
    with benchmark_jsonl.open("w") as out:
        for row in ds:
            example = _row_to_example(row, processed_root)
            out.write(example.model_dump_json() + "\n")

    logger.info("Wrote %s", benchmark_jsonl)
    return benchmark_jsonl, ds


def dataset_fingerprint(ds: Dataset) -> dict:
    """Return a dict uniquely identifying a materialized dataset revision.

    Used by the matrix summary and per-run JSON so a future reader can verify
    they're reproducing the same numbers against the same data.
    """
    info = ds.info
    split_obj = ds.split
    return {
        "num_rows": len(ds),
        "fingerprint": ds._fingerprint,
        "split": str(split_obj) if split_obj is not None else None,
        "version": str(info.version) if info.version else None,
        "description": info.description if info.description else None,
    }


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _filter_stress_rows(ds: Dataset) -> Dataset:
    """Drop pre-baked stress variants (contact_sheet_Nup, downscale, ...).

    Stress rows lack `original_bboxes`, which `oracle_crop` requires for
    scoring. The published HF dataset keeps legacy stress rows for historical
    study; the current protocol grid generates its own adversarial conditions
    at runtime, so pre-baked stress variants would double-count. Safe no-op
    when the `stress_type` column is absent (older dataset revisions).
    """
    if "stress_type" not in ds.column_names:
        return ds
    stress_types = ds["stress_type"]
    keep_mask = [s in (None, "", "none") for s in stress_types]
    dropped = len(keep_mask) - sum(keep_mask)
    if dropped == 0:
        return ds
    offender_counts = Counter(
        s for s, keep in zip(stress_types, keep_mask, strict=True) if not keep
    )
    logger.info(
        "Filtered %d stress rows from HF split (kept %d canonical): %s",
        dropped,
        sum(keep_mask),
        dict(offender_counts),
    )
    return ds.select([i for i, keep in enumerate(keep_mask) if keep])


def _page_num_from_hf_image_index(idx: int, row: dict) -> int:
    """Derive the source page number for the i-th entry in `page_images`.

    HF `page_images` are ordered by `supporting_pages`. Most rows have one
    supporting page; multi-page rows list both in the same order.
    """
    supporting = row.get("supporting_pages") or []
    if idx < len(supporting):
        return int(supporting[idx])
    return idx + 1


_HF_SPLIT_ALIASES = {"validation": "dev", "val": "dev"}


def _normalize_split(value: str | None) -> str | None:
    if not value:
        return None
    return _HF_SPLIT_ALIASES.get(value, value)


def _row_to_example(row: dict, processed_root: Path):
    """Convert one HF row to a `BenchmarkExample` with resolvable paths.

    Writes page images under `processed_root/<doc_stem>/images/` with names
    matching `*_page_<NNNN>_300dpi.png`. Path strings in `page_images` are
    stored *relative to `staging_root`* (i.e. `processed_root.parent.parent`)
    so the harness can invoke with `project_root=<staging_root>`.
    """
    # Lazy import so this module stays importable without the parser-bench
    # submodule initialized. Callers that actually construct examples obviously
    # need the schema present.
    from focusparse._parser_bench import BBox, BenchmarkExample

    source_pdf_name = row["source_pdf"]
    doc_stem = Path(source_pdf_name).stem
    doc_images_dir = processed_root / doc_stem / "images"
    doc_images_dir.mkdir(parents=True, exist_ok=True)
    staging_root = processed_root.parent.parent

    page_image_paths: list[str] = []
    for idx, pil_img in enumerate(row["page_images"]):
        if pil_img is None:
            continue
        page_num = _page_num_from_hf_image_index(idx, row)
        fname = f"{doc_stem}_page_{page_num:04d}_300dpi.png"
        out_path = doc_images_dir / fname
        if not out_path.exists():
            pil_img.save(out_path, format="PNG")
        page_image_paths.append(str(out_path.relative_to(staging_root)))

    supporting_bboxes = [BBox(**b) for b in json.loads(row.get("supporting_bboxes") or "[]")]
    alternate_bboxes = [BBox(**b) for b in json.loads(row.get("alternate_bboxes") or "[]")]

    return BenchmarkExample(
        id=row["id"],
        domain=row["domain"],
        source_pdf=source_pdf_name,
        page_images=page_image_paths,
        question=row["question"],
        answer=row["answer"],
        answer_type=row["answer_type"],
        answer_unit=row.get("answer_unit"),
        tolerance=row.get("tolerance"),
        supporting_pages=list(row.get("supporting_pages") or []),
        supporting_bboxes=supporting_bboxes,
        alternate_bboxes=alternate_bboxes,
        evidence_relations=[],
        multi_region_required=bool(row.get("multi_region_required", False)),
        requires_visual=bool(row.get("requires_visual", True)),
        difficulty={
            "visual": int(row.get("difficulty_visual", 1)),
            "reasoning": int(row.get("difficulty_reasoning", 1)),
            "localization": int(row.get("difficulty_localization", 1)),
        },
        question_family=row.get("question_family", ""),
        stress_type=row.get("stress_type") or "none",
        reasoning_chain=row.get("reasoning_chain"),
        evidence_page_spread=int(row.get("evidence_page_spread", 0)),
        adversarial_type=row.get("adversarial_type"),
        split=_normalize_split(row.get("split")),
        original_bboxes=[],
    )


__all__ = [
    "materialize_split",
    "dataset_fingerprint",
]
