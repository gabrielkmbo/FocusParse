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


def _write_per_example(spec_dir: Path, records: list[dict]) -> None:
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "per_example.jsonl").write_text("\n".join(json.dumps(r) for r in records) + "\n")


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


def test_diagnose_prefers_per_example_jsonl_over_prediction_filenames(tmp_path: Path) -> None:
    spec = tmp_path / "focusparse_focus_x"
    pred = spec / "predictions"
    _write_record(pred, example_id="safe-id", correct=0.0)
    _write_per_example(
        spec,
        [
            {
                "example_id": "raw id with spaces",
                "answer_correct": 1.0,
                "is_lazy": 0,
                "citations": [{"page": 1}],
                "tool_calls": 1,
                "usd": 0.01,
                "trace": {"steps": []},
            },
            {
                "example_id": "another/raw:id",
                "answer_correct": 0.0,
                "is_lazy": 1,
                "citations": [],
                "tool_calls": 0,
                "usd": 0.02,
                "trace": {"steps": []},
            },
        ],
    )

    diag = dp.diagnose_spec(spec)

    assert diag.n_examples == 2
    assert diag.accuracy == 0.5


def test_evidence_packet_quality_resolves_answer_packet_citations(tmp_path: Path) -> None:
    spec = tmp_path / "focusparse_focus_x"
    _write_per_example(
        spec,
        [
            {
                "example_id": "a",
                "answer_correct": 0.0,
                "is_lazy": 0,
                "citations": [{"page": 1, "bbox": [0, 0, 1, 1]}],
                "trace": {
                    "evidence_snapshot": [
                        {
                            "packet_id": "pkt_text",
                            "text_layer_snippet": "VCC max 3.6 V",
                            "ocr_snippet": None,
                            "chart_csv": None,
                            "linked_crop_refs": [],
                            "linked_neighbor_types": [],
                        },
                        {
                            "packet_id": "pkt_image",
                            "text_layer_snippet": None,
                            "ocr_snippet": None,
                            "chart_csv": None,
                            "linked_crop_refs": ["/crop/caption.png"],
                            "linked_neighbor_types": ["caption"],
                        },
                    ],
                    "steps": [
                        {
                            "stage": "answer",
                            "action": "llm_call",
                            "obs_summary": '{"answer": "x", "citations": ["pkt_image"]}',
                        },
                        {
                            "stage": "verify",
                            "action": "llm_call",
                            "args": {"supported": False},
                        },
                    ],
                },
            }
        ],
    )

    diag = dp.diagnose_spec(spec)

    assert diag.total_evidence_packets == 2
    assert diag.packet_text_coverage_rate == 0.5
    assert diag.packet_linked_context_rate == 0.5
    assert diag.cited_packet_count == 1
    assert diag.cited_packet_resolved_rate == 1.0
    assert diag.cited_packet_text_coverage_rate == 0.0
    assert diag.cited_packet_linked_context_rate == 1.0
    assert diag.cited_packet_image_only_rate == 1.0
    assert diag.verifier_unsupported_cited_image_only_rate == 1.0


def test_evidence_packet_quality_counts_chart_attempts_from_debug_packets(
    tmp_path: Path,
) -> None:
    spec = tmp_path / "focusparse_focus_x"
    _write_per_example(
        spec,
        [
            {
                "example_id": "a",
                "answer_correct": 0.0,
                "trace": {
                    "evidence_snapshot": [
                        {
                            "packet_id": "pkt_old",
                            "ocr_snippet": None,
                            "chart_csv": None,
                        }
                    ],
                    "debug_events": [
                        {
                            "stage": "inspect",
                            "payload": {
                                "packets": [
                                    {
                                        "packet_id": "pkt_chart",
                                        "ocr_snippet": "Chart packet",
                                        "chart_csv": None,
                                        "provenance_args_hash": (
                                            "inspect_region:image|chart_to_table:attempt|"
                                            "chart_to_table:empty"
                                        ),
                                    },
                                    {
                                        "packet_id": "pkt_text",
                                        "text_layer_snippet": "plain text",
                                        "provenance_args_hash": "inspect_region:image",
                                    },
                                ]
                            },
                        }
                    ],
                },
            }
        ],
    )

    diag = dp.diagnose_spec(spec)

    assert diag.total_evidence_packets == 2
    assert diag.packet_chart_attempt_rate == 0.5
    assert diag.packet_chart_empty_rate == 0.5
    assert diag.packet_chart_error_rate == 0.0


def test_evidence_packet_quality_counts_unresolved_answer_citation(tmp_path: Path) -> None:
    spec = tmp_path / "focusparse_focus_x"
    _write_per_example(
        spec,
        [
            {
                "example_id": "a",
                "answer_correct": 0.0,
                "trace": {
                    "evidence_snapshot": [{"packet_id": "pkt_000"}],
                    "steps": [
                        {
                            "stage": "answer",
                            "action": "llm_call",
                            "obs_summary": '```json\n{"answer":"x","citations":["missing"]}\n```',
                        }
                    ],
                },
            }
        ],
    )

    diag = dp.diagnose_spec(spec)

    assert diag.cited_packet_count == 1
    assert diag.cited_packet_resolved_rate == 0.0
    assert diag.cited_packet_text_coverage_rate is None


def test_failure_reason_breakdown_buckets_incorrect_examples(tmp_path: Path) -> None:
    spec = tmp_path / "focusparse_focus_x"
    _write_per_example(
        spec,
        [
            {
                "example_id": "loc",
                "answer_correct": 0.0,
                "is_lazy": 0,
                "citations": [{"page": 1, "bbox": [0, 0, 1, 1]}],
                "stages": {"localization": {"region_recall": 0.0}},
                "trace": {
                    "evidence_snapshot": [{"packet_id": "pkt_loc", "text_layer_snippet": "x"}],
                    "debug_events": [
                        {"stage": "answer", "payload": {"citations": ["pkt_loc"]}},
                    ],
                },
            },
            {
                "example_id": "image",
                "answer_correct": 0.0,
                "is_lazy": 0,
                "citations": [{"page": 2, "bbox": [0, 0, 1, 1]}],
                "stages": {"localization": {"region_recall": 1.0}},
                "trace": {
                    "evidence_snapshot": [
                        {
                            "packet_id": "pkt_image",
                            "text_layer_snippet": None,
                            "ocr_snippet": None,
                            "chart_csv": None,
                        }
                    ],
                    "debug_events": [
                        {"stage": "answer", "payload": {"citations": ["pkt_image"]}},
                    ],
                    "steps": [
                        {
                            "stage": "verify",
                            "action": "llm_call",
                            "args": {"supported": False},
                        }
                    ],
                },
            },
            {
                "example_id": "ok",
                "answer_correct": 1.0,
                "is_lazy": 0,
                "citations": [{"page": 3, "bbox": [0, 0, 1, 1]}],
                "trace": {"steps": []},
            },
        ],
    )

    diag = dp.diagnose_spec(spec)
    md = dp.render_markdown([diag])

    assert diag.failure_reasons["localization_miss"] == 1
    assert diag.failure_reasons["cited_image_only"] == 1
    assert "top_failure" in md
    assert "incorrect-example failure reasons" in md


def test_answer_packet_citations_prefer_debug_events(tmp_path: Path) -> None:
    spec = tmp_path / "focusparse_focus_x"
    _write_per_example(
        spec,
        [
            {
                "example_id": "a",
                "answer_correct": 1.0,
                "trace": {
                    "evidence_snapshot": [
                        {"packet_id": "pkt_debug", "text_layer_snippet": "debug text"},
                        {"packet_id": "pkt_obs", "text_layer_snippet": None},
                    ],
                    "debug_events": [
                        {
                            "stage": "answer",
                            "payload": {"citations": ["pkt_debug"]},
                        }
                    ],
                    "steps": [
                        {
                            "stage": "answer",
                            "action": "llm_call",
                            "obs_summary": '{"answer":"x","citations":["pkt_obs"]}',
                        }
                    ],
                },
            }
        ],
    )

    diag = dp.diagnose_spec(spec)

    assert diag.cited_packet_count == 1
    assert diag.cited_packet_text_coverage_rate == 1.0


def test_focus_stage_diagnostics_capture_verifier_and_expand_context(tmp_path: Path) -> None:
    spec = tmp_path / "focusparse_focus_x"
    pred = spec / "predictions"
    _write_record(
        pred,
        example_id="a",
        steps=[
            {
                "stage": "inspect",
                "action": "tool_call",
                "tool": "deterministic_inspector",
                "args": {"n_packets": 2},
            },
            {
                "stage": "expand_context",
                "action": "deterministic",
                "tool": None,
                "args": {"n_neighbors_attached": 3},
            },
            {
                "stage": "verify",
                "action": "llm_call",
                "tool": None,
                "args": {"supported": False, "next_action": "expand_context"},
            },
        ],
    )
    _write_record(
        pred,
        example_id="b",
        correct=1.0,
        steps=[
            {
                "stage": "inspect",
                "action": "tool_call",
                "tool": "deterministic_inspector",
                "args": {"n_packets": 1},
            },
            {
                "stage": "verify",
                "action": "llm_call",
                "tool": None,
                "args": {"supported": True, "next_action": "accept"},
            },
        ],
    )

    diag = dp.diagnose_spec(spec)

    assert diag.verifier_unsupported_rate == 0.5
    assert diag.verifier_next_actions == {"expand_context": 1, "accept": 1}
    assert diag.verifier_unsupported_next_actions == {"expand_context": 1}
    assert diag.incorrect_verifier_next_actions == {"expand_context": 1}
    assert diag.expand_context_called_rate == 0.5
    assert diag.mean_neighbors_attached == 1.5
    assert diag.tool_sequence_top == [("deterministic_inspector", 2)]


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


def test_resolve_spec_dirs_accepts_per_example_jsonl(tmp_path: Path) -> None:
    parent = tmp_path / "headline"
    spec = parent / "spec_from_run_jsonl"
    spec.mkdir(parents=True)
    (spec / "per_example.jsonl").write_text("{}\n")

    resolved = dp._resolve_spec_dirs([parent])

    assert resolved == [spec]


def test_render_markdown_smoke(tmp_path: Path) -> None:
    spec = tmp_path / "focusparse_simple"
    pred = spec / "predictions"
    _write_record(pred, example_id="a", correct=1.0)
    md = dp.render_markdown([dp.diagnose_spec(spec)])
    assert "Predictions diagnostics" in md
    assert "focusparse_simple" in md
    assert "expand_called" in md


def test_verifier_next_actions_render_and_export(tmp_path: Path) -> None:
    spec = tmp_path / "focusparse_focus_x"
    _write_per_example(
        spec,
        [
            {
                "example_id": "correct_accept",
                "answer_correct": 1.0,
                "is_lazy": 0,
                "citations": [],
                "trace": {
                    "steps": [
                        {
                            "stage": "verify",
                            "action": "llm_call",
                            "args": {"supported": True, "next_action": "accept"},
                        }
                    ]
                },
            },
            {
                "example_id": "wrong_expand",
                "answer_correct": 0.0,
                "is_lazy": 0,
                "citations": [{"page": 1}],
                "trace": {
                    "steps": [
                        {
                            "stage": "verify",
                            "action": "llm_call",
                            "args": {"supported": False, "next_action": "expand_context"},
                        }
                    ]
                },
            },
            {
                "example_id": "wrong_retry",
                "answer_correct": 0.0,
                "is_lazy": 0,
                "citations": [{"page": 2}],
                "trace": {
                    "steps": [
                        {
                            "stage": "verify",
                            "action": "llm_call",
                            "args": {
                                "supported": False,
                                "next_action": "retry_localization",
                            },
                        }
                    ]
                },
            },
            {
                "example_id": "wrong_accept",
                "answer_correct": 0.0,
                "is_lazy": 0,
                "citations": [{"page": 3}],
                "trace": {
                    "steps": [
                        {
                            "stage": "verify",
                            "action": "llm_call",
                            "args": {"supported": True, "next_action": "accept"},
                        }
                    ]
                },
            },
        ],
    )

    diag = dp.diagnose_spec(spec)
    md = dp.render_markdown([diag])
    exported = dp.to_json([diag])["specs"][0]

    assert diag.verifier_next_actions == {
        "accept": 2,
        "expand_context": 1,
        "retry_localization": 1,
    }
    assert diag.verifier_unsupported_next_actions == {
        "expand_context": 1,
        "retry_localization": 1,
    }
    assert diag.incorrect_verifier_next_actions == {
        "accept": 1,
        "expand_context": 1,
        "retry_localization": 1,
    }
    assert "top_verifier_action" in md
    assert "unsupported verifier next_action counts" in md
    assert exported["incorrect_verifier_next_actions"]["accept"] == 1
