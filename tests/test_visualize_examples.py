"""Tests for scripts/visualize_examples.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import visualize_examples as ve  # noqa: E402


def _make_spec(parent: Path, name: str, rows: list[dict]) -> Path:
    """Build a fake spec dir with a per_example.jsonl + predictions/."""
    spec = parent / name
    (spec / "predictions").mkdir(parents=True)
    jsonl = spec / "per_example.jsonl"
    with jsonl.open("w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
            (spec / "predictions" / f"{row['example_id']}.json").write_text(
                json.dumps(
                    {
                        "example_id": row["example_id"],
                        "answer_correct": row["answer_correct"],
                        "answer_pred": row.get("answer_pred", "x"),
                        "answer_gold": row.get("answer_gold", "x"),
                        "citations": [],
                        "trace": {"steps": [], "evidence_snapshot": None},
                    }
                )
            )
    return spec


def test_discover_specs_filters_by_predictions(tmp_path: Path) -> None:
    _make_spec(tmp_path, "focusparse_simple_agentic_multi_page_xx", [])
    _make_spec(tmp_path, "focusparse_focus_agentic_multi_page_xx", [])
    _make_spec(tmp_path, "focusparse_focus_agentic_multi_page_xx_tminimal", [])
    # A non-spec dir without predictions/ should be ignored.
    (tmp_path / "not_a_spec").mkdir()
    discovered = ve.discover_specs(tmp_path)
    assert "simple" in discovered
    assert "focus_4" in discovered
    assert "focus_2" in discovered
    assert "not_a_spec" not in discovered


def test_load_correctness_via_jsonl(tmp_path: Path) -> None:
    spec = _make_spec(
        tmp_path,
        "focusparse_simple_x",
        [
            {"example_id": "dat-A-0001", "answer_correct": 1.0},
            {"example_id": "dat-B-0001", "answer_correct": 0.0},
        ],
    )
    c = ve.load_correctness(spec)
    assert c == {"dat-A-0001": 1.0, "dat-B-0001": 0.0}


def test_pick_examples_buckets() -> None:
    base = {"a": 1.0, "b": 0.0, "c": 0.0, "d": 0.0}
    focus = {"a": 0.0, "b": 1.0, "c": 0.0, "d": 0.0}
    react = {"a": 0.0, "b": 0.0, "c": 1.0, "d": 0.0}
    others = {"a": 0.0, "b": 0.0, "c": 0.0, "d": 0.0}
    correctness = {
        "simple": base,
        "focus_4": focus,
        "react_4": react,
        "react_2": others,
        "agent_baseline_2": others,
        "agent_baseline_4": others,
        "focus_2": others,
    }
    picks = ve.pick_examples(correctness, seed=42)
    assert picks["correct_by_focus_only"] == "b"
    assert picks["correct_by_base_only"] == "a"
    assert picks["correct_by_react_not_base"] == "c"
    assert picks["wrong_by_everyone"] == "d"


def test_pick_examples_deterministic() -> None:
    correctness = {
        "simple": {f"x{i}": 0.0 for i in range(5)},
        "focus_4": {f"x{i}": 1.0 for i in range(5)},
        "react_4": {f"x{i}": 0.0 for i in range(5)},
        "react_2": {f"x{i}": 0.0 for i in range(5)},
        "agent_baseline_2": {f"x{i}": 0.0 for i in range(5)},
        "agent_baseline_4": {f"x{i}": 0.0 for i in range(5)},
        "focus_2": {f"x{i}": 0.0 for i in range(5)},
    }
    a = ve.pick_examples(correctness, seed=42)
    b = ve.pick_examples(correctness, seed=42)
    assert a == b


def test_pick_examples_returns_none_when_no_candidates() -> None:
    correctness = {
        "simple": {"a": 1.0},
        "focus_4": {"a": 1.0},
        "react_4": {"a": 1.0},
        "react_2": {"a": 1.0},
        "agent_baseline_2": {"a": 1.0},
        "agent_baseline_4": {"a": 1.0},
        "focus_2": {"a": 1.0},
    }
    picks = ve.pick_examples(correctness, seed=42)
    assert picks["correct_by_focus_only"] is None
    assert picks["wrong_by_everyone"] is None


def test_render_index_writes_grid(tmp_path: Path) -> None:
    out = tmp_path / "index.html"
    picks = {b: None for b in ve.BUCKETS}
    picks["correct_by_focus_only"] = "dat-Foo-0001"
    specs = {key: tmp_path for key in ve.SPEC_KEYS}
    correctness = {key: {"dat-Foo-0001": 1.0 if key == "focus_4" else 0.0} for key in ve.SPEC_KEYS}
    ve.render_index(picks, specs, correctness, out)
    text = out.read_text()
    assert "Trace viewer · headline-v1" in text
    assert "dat-Foo-0001" in text
    assert "no candidate" in text  # for the empty buckets
