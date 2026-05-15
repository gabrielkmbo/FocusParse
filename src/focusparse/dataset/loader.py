"""Unified benchmark loader.

Default: stream parquet from HuggingFace (`gabrielbo/parser-bench`) — works
from a fresh clone with only `HF_TOKEN`.

Fallback: read from a local parser-bench checkout's `data/candidates/*.jsonl`
plus processed page PNGs under `data/processed/<doc>/images/` — required when
you need pristine 300 DPI pages for `oracle_crop` or coding-driven zoom.

Both paths yield pydantic `BenchmarkExample` objects from parser-bench's schema
(imported via `focusparse._parser_bench`).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from focusparse._parser_bench import BenchmarkExample

_HF_SPLIT_ALIASES = {
    "dev": "train",
    "test": "validation",
    "holdout": "test",
}


class BenchmarkLoader:
    """Load `BenchmarkExample` rows from HF (streaming) or local disk."""

    def __init__(
        self,
        *,
        source: str = "hf",
        hf_repo: str = "gabrielbo/parser-bench",
        revision: str | None = None,
        local_root: Path | str | None = None,
    ) -> None:
        if source not in ("hf", "local"):
            raise ValueError(f"source must be 'hf' or 'local'; got {source!r}")
        self.source = source
        self.hf_repo = hf_repo
        self.revision = revision
        self.local_root = Path(local_root) if local_root else None

    # --- classmethods ----------------------------------------------------

    @classmethod
    def from_hf(
        cls,
        repo: str = "gabrielbo/parser-bench",
        revision: str | None = None,
    ) -> BenchmarkLoader:
        return cls(source="hf", hf_repo=repo, revision=revision)

    @classmethod
    def from_local(cls, parser_bench_root: Path | str) -> BenchmarkLoader:
        return cls(source="local", local_root=parser_bench_root)

    # --- iteration -------------------------------------------------------

    def iter_split(
        self,
        split: str,
        *,
        limit: int | None = None,
    ) -> Iterator[BenchmarkExample]:
        """Yield up to `limit` examples for the requested split."""
        if self.source == "hf":
            yield from self._iter_hf(split, limit)
        else:
            yield from self._iter_local(split, limit)

    # --- HF streaming ----------------------------------------------------

    def _iter_hf(self, split: str, limit: int | None) -> Iterator[BenchmarkExample]:
        # Deferred import so `focus status` doesn't pull `datasets` when offline.
        from datasets import load_dataset

        ds = load_dataset(
            self.hf_repo,
            split=hf_split_name(split),
            revision=self.revision,
            streaming=True,
        )
        for count, row in enumerate(ds, start=1):
            yield _row_to_example(row)
            if limit is not None and count >= limit:
                return

    # --- local disk ------------------------------------------------------

    def _iter_local(self, split: str, limit: int | None) -> Iterator[BenchmarkExample]:
        from focusparse._parser_bench import BenchmarkExample as _BE

        if self.local_root is None:
            raise ValueError("local_root must be set for source='local'")
        jsonl = self.local_root / "data" / "benchmark" / f"{split}.jsonl"
        if not jsonl.exists():
            jsonl = self.local_root / "data" / "candidates" / "candidates.jsonl"
        if not jsonl.exists():
            raise FileNotFoundError(
                f"No local benchmark file at {jsonl}; expected "
                "data/benchmark/<split>.jsonl or data/candidates/candidates.jsonl"
            )
        count = 0
        with open(jsonl) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                ex = _BE.model_validate_json(line)
                if ex.split is not None and str(ex.split) != split and ex.split != split:
                    continue
                yield ex
                count += 1
                if limit is not None and count >= limit:
                    return


def _row_to_example(row: dict[str, Any]) -> BenchmarkExample:
    """Convert a raw HF parquet row into a BenchmarkExample.

    The HF dataset embeds `supporting_bboxes` etc. as JSON strings (see
    parser-bench push_to_hf.py). Deserialize fields that need it.
    """
    from focusparse._parser_bench import BenchmarkExample as _BE

    normalized = dict(row)
    for field_name in (
        "supporting_bboxes",
        "alternate_bboxes",
        "evidence_relations",
        "original_bboxes",
        "difficulty",
        "supporting_pages",
        "page_images",
        "distractor_region_ids",
    ):
        value = normalized.get(field_name)
        if isinstance(value, str):
            with suppress(json.JSONDecodeError):
                normalized[field_name] = json.loads(value)
    if "difficulty" not in normalized or normalized.get("difficulty") in (None, ""):
        normalized["difficulty"] = {
            "visual": int(normalized.get("difficulty_visual", 1) or 1),
            "reasoning": int(normalized.get("difficulty_reasoning", 1) or 1),
            "localization": int(normalized.get("difficulty_localization", 1) or 1),
        }
    page_images = normalized.get("page_images")
    if isinstance(page_images, list):
        normalized["page_images"] = [p for p in page_images if isinstance(p, str)]
    return _BE.model_validate(normalized)


def hf_split_name(split: str) -> str:
    """Map legacy parser-bench local split names to current HF split names."""
    return _HF_SPLIT_ALIASES.get(split, split)
