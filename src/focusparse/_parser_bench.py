"""Shim that loads parser-bench's pydantic schema from the git submodule.

Parser-bench uses `src/utils/schema.py` as its canonical data model. Importing
it via a file-path-based loader (rather than adding `third_party/parser-bench`
to sys.path) avoids colliding with our own `src/focusparse` layout.

If the submodule is missing, raise a clear error pointing at the init step.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA_PATH = _REPO_ROOT / "third_party" / "parser-bench" / "src" / "utils" / "schema.py"


def _load_parser_bench_schema() -> Any:
    if not _SCHEMA_PATH.exists():
        raise FileNotFoundError(
            f"parser-bench schema not found at {_SCHEMA_PATH}.\n"
            "Run from the repo root:\n"
            "  git submodule add https://github.com/gabrielkmbo/parse-bench "
            "third_party/parser-bench\n"
            "  git submodule update --init --recursive"
        )
    spec = importlib.util.spec_from_file_location("_pb_schema", _SCHEMA_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_pb_schema"] = mod
    spec.loader.exec_module(mod)
    return mod


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
