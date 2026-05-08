"""Shim that loads parser-bench's pydantic schema from the git submodule.

Parser-bench uses `src/utils/schema.py` as its canonical data model. Importing
it via a file-path-based loader (rather than adding `third_party/parser-bench`
to sys.path) avoids colliding with our own `src/focusparse` layout.

If the submodule is missing, use a narrow compatibility schema that covers the
published HF benchmark rows. The submodule remains canonical whenever present;
the fallback only keeps eval runners usable in environments where private
submodule auth is unavailable.
"""

from __future__ import annotations

import importlib.util
import sys
from enum import StrEnum
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from pydantic import BaseModel, Field

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA_PATH = _REPO_ROOT / "third_party" / "parser-bench" / "src" / "utils" / "schema.py"


def _load_parser_bench_schema(schema_path: Path = _SCHEMA_PATH) -> Any:
    if not schema_path.exists():
        return _fallback_schema_module()
    spec = importlib.util.spec_from_file_location("_pb_schema", schema_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_pb_schema"] = mod
    spec.loader.exec_module(mod)
    return mod


def _fallback_schema_module() -> Any:
    """Return the subset of parser-bench schema used by FocusParse evals."""

    class Domain(StrEnum):
        FINANCE = "finance"
        DATASHEET = "datasheet"

    class AnswerType(StrEnum):
        NUMERIC = "numeric"
        EXACT_MATCH = "exact_match"
        MULTIPLE_CHOICE = "multiple_choice"
        BOOLEAN = "boolean"
        UNANSWERABLE = "unanswerable"

    class Split(StrEnum):
        DEV = "dev"
        TEST = "test"
        HOLDOUT = "holdout"

    class StressType(StrEnum):
        NONE = "none"
        CONTACT_SHEET_2UP = "contact_sheet_2up"
        CONTACT_SHEET_4UP = "contact_sheet_4up"
        CONTACT_SHEET_8UP = "contact_sheet_8up"
        DOWNSCALE = "downscale"
        SPATIAL_SEPARATION = "spatial_separation"
        LEGEND_PLOT_SPLIT = "legend_plot_split"

    class RegionType(StrEnum):
        TABLE = "table"
        CHART = "chart"
        CURVE = "curve"
        CAPTION = "caption"
        FOOTNOTE = "footnote"
        LEGEND = "legend"
        AXIS_LABEL = "axis_label"
        PIN_DIAGRAM = "pin_diagram"
        PACKAGE_DRAWING = "package_drawing"
        SCHEMATIC = "schematic"
        TIMING_DIAGRAM = "timing_diagram"
        TEXT_BLOCK = "text_block"
        PAGE_FURNITURE = "page_furniture"
        OTHER = "other"

    class EdgeType(StrEnum):
        LEGEND_SERIES = "legend->series"
        AXIS_LABEL_CHART = "axis_label->chart_axis"
        FOOTNOTE_CHART = "footnote->chart"
        FOOTNOTE_TABLE = "footnote->table"
        CAPTION_FIGURE = "caption->figure"
        CAPTION_TABLE = "caption->table"
        CONDITION_NOTE_ROW = "condition_note->table_row"
        PIN_LABEL_DIAGRAM = "pin_label->pin_diagram"
        SAME_PAGE_ADJACENT = "same_page_adjacent"
        CROSS_PAGE_CONTINUATION = "cross_page_continuation"
        DISTANT_CROSS_REF = "distant_cross_ref"

    class BBox(BaseModel):
        page: int
        x0: float
        y0: float
        x1: float
        y1: float

    class EvidenceRelation(BaseModel):
        type: EdgeType
        source_bbox: BBox
        target_bbox: BBox

    class DifficultyScores(BaseModel):
        visual: int = Field(ge=1, le=3)
        reasoning: int = Field(ge=1, le=3)
        localization: int = Field(ge=1, le=3)

    class BenchmarkExample(BaseModel):
        id: str
        domain: Domain
        source_pdf: str
        page_images: list[str]
        question: str
        answer: str
        answer_type: AnswerType
        answer_unit: str | None = None
        tolerance: float | None = None
        supporting_pages: list[int]
        supporting_bboxes: list[BBox]
        alternate_bboxes: list[BBox] = []
        evidence_relations: list[EvidenceRelation] = []
        multi_region_required: bool = False
        requires_visual: bool = True
        difficulty: DifficultyScores
        question_family: str
        stress_type: StressType = StressType.NONE
        original_bboxes: list[BBox] = []
        split: Split | None = None
        reasoning_chain: str | None = None
        evidence_page_spread: int = 0
        distractor_region_ids: list[str] = []
        adversarial_type: str | None = None

    return SimpleNamespace(
        BenchmarkExample=BenchmarkExample,
        BBox=BBox,
        Domain=Domain,
        AnswerType=AnswerType,
        Split=Split,
        StressType=StressType,
        RegionType=RegionType,
        EdgeType=EdgeType,
        DifficultyScores=DifficultyScores,
        EvidenceRelation=EvidenceRelation,
    )


_schema = _load_parser_bench_schema()

BenchmarkExample = _schema.BenchmarkExample
BBox = _schema.BBox
Domain = _schema.Domain
AnswerType = _schema.AnswerType
Split = _schema.Split
StressType = _schema.StressType
RegionType = _schema.RegionType
EdgeType = _schema.EdgeType
DifficultyScores = _schema.DifficultyScores
EvidenceRelation = _schema.EvidenceRelation

__all__ = [
    "BenchmarkExample",
    "BBox",
    "Domain",
    "AnswerType",
    "Split",
    "StressType",
    "RegionType",
    "EdgeType",
    "DifficultyScores",
    "EvidenceRelation",
]
