"""Tests for scripts/diagnose_predictions.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow importing the script as a module.
ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import diagnose_predictions as dp  # noqa: E402


def _write_record(
    pred_dir: Path,
    *,
    example_id: str,
    correct: float = 0.0,
    is_lazy: int = 0,
    citations: list[dict] | None = None,
    tool_calls: int = 0,
    usd: float = 0.0,
    steps: list[dict] | None = None,
) -> None:
    pred_dir.mkdir(parents=True, exist_ok=True)
    (pred_dir / f"{example_id}.json").write_text(
        json.dumps(
            {
                "example_id": example_id,
                "answer_correct": correct,
                "is_lazy": is_lazy,
                "citations": citations or [],
                "tool_calls": tool_calls,
                "usd": usd,
                "trace": {"steps": steps or []},
            }
        )
    )


def test_diagnose_empty_dir(tmp_path: Path) -> None:
    spec = tmp_path / "spec"
    spec.mkdir()
    diag = dp.diagnose_spec(spec)
    assert diag.n_examples == 0


def test_lazy_rate_and_accuracy(tmp_path: Path) -> None:
    spec = tmp_path / "focusparse_simple"
    pred = spec / "predictions"
    _write_record(pred, example_id="a", correct=1.0, is_lazy=1)
    _write_record(pred, example_id="b", correct=0.0, is_lazy=1)
    _write_record(pred, example_id="c", correct=1.0, is_lazy=0, citations=[{"page": 1}])

    diag = dp.diagnose_spec(spec)
    assert diag.n_examples == 3
    assert diag.accuracy == 2 / 3
    assert diag.lazy_answer_rate == 2 / 3
    # premature_final is None for non-comparator specs
    assert diag.premature_final_rate is None


def test_premature_final_for_react(tmp_path: Path) -> None:
    spec = tmp_path / "focusparse_react_agentic_multi_page_xyz"
    pred = spec / "predictions"
    # Premature: only step is react_final, no tool calls.
    _write_record(
        pred,
        example_id="a",
        is_lazy=1,
        steps=[{"stage": "react_final", "action": "final_answer", "tool": None}],
    )
    # Not premature: has a tool_call before react_final.
    _write_record(
        pred,
        example_id="b",
        is_lazy=0,
        tool_calls=1,
        citations=[{"page": 1}],
        steps=[
            {
                "stage": "react_step",
                "action": "tool_call",
                "tool": "inspect_region",
                "args": {"action_input": {"doc_path": "x", "page": 1}},
            },
            {"stage": "react_final", "action": "final_answer", "tool": None},
        ],
    )
    diag = dp.diagnose_spec(spec)
    assert diag.premature_final_rate == 0.5
    assert diag.mean_tool_calls == 0.5


def test_tool_error_categorization(tmp_path: Path) -> None:
    spec = tmp_path / "focusparse_react_x"
    pred = spec / "predictions"
    _write_record(
        pred,
        example_id="a",
        steps=[
            {
                "stage": "react_step",
                "action": "tool_error",
                "tool": "inspect_region",
                "args": {"error": "validation_error"},
            },
            {
                "stage": "react_step",
                "action": "tool_error",
                "tool": "inspect_region",
                "args": {"error": "tool_runtime_error"},
            },
            {"stage": "react_final", "action": "final_answer", "tool": None},
        ],
    )
    diag = dp.diagnose_spec(spec)
    assert diag.n_tool_errors == 2
    assert diag.error_categories["validation_error"] == 1
    assert diag.error_categories["tool_runtime_error"] == 1


def test_action_input_shape_topn(tmp_path: Path) -> None:
    spec = tmp_path / "focusparse_react_x"
    pred = spec / "predictions"
    for i in range(3):
        _write_record(
            pred,
            example_id=f"a{i}",
            steps=[
                {
                    "stage": "react_step",
                    "action": "tool_call",
                    "tool": "inspect_region",
                    "args": {"action_input": {"doc_path": "x", "page": 1}},
                }
            ],
        )
    diag = dp.diagnose_spec(spec)
    shapes = diag.action_input_top["inspect_region"]
    assert shapes[0][0] == "{doc_path:str, page:int}"
    assert shapes[0][1] == 3


def test_resolve_spec_dirs_walks_parent(tmp_path: Path) -> None:
    parent = tmp_path / "headline"
    parent.mkdir()
    a = parent / "spec_a"
    (a / "predictions").mkdir(parents=True)
    b = parent / "spec_b"
    (b / "predictions").mkdir(parents=True)
    parent_no_pred = parent / "not_a_spec"
    parent_no_pred.mkdir()
    resolved = dp._resolve_spec_dirs([parent])
    assert {p.name for p in resolved} == {"spec_a", "spec_b"}


def test_render_markdown_smoke(tmp_path: Path) -> None:
    spec = tmp_path / "focusparse_simple"
    pred = spec / "predictions"
    _write_record(pred, example_id="a", correct=1.0)
    md = dp.render_markdown([dp.diagnose_spec(spec)])
    assert "Predictions diagnostics" in md
    assert "focusparse_simple" in md
