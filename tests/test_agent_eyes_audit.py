"""Tests for scripts/build_agent_eyes_audit.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import build_agent_eyes_audit as aea  # noqa: E402


def _record(example_id: str, *, correct: float, iou: float = 0.8) -> dict:
    return {
        "example_id": example_id,
        "domain": "Domain.DATASHEET",
        "answer_pred": "Vgs=2.9V",
        "answer_gold": "Vgs = 2.9 V",
        "answer_correct": correct,
        "page_recall": 1.0,
        "bbox_iou": iou,
        "evidence_reward": 0.0,
        "telemetry": {"retries_used": 1, "loop_terminated": "exhausted"},
        "trace": {
            "question": "What is the curve label?",
            "steps": [
                {
                    "stage": "plan",
                    "args": {
                        "question_family": "curve_axis_reading",
                        "routing_policy": "layout_first",
                        "budget_class": "easy_local",
                    },
                }
            ],
            "debug_events": [
                {
                    "stage": "answer",
                    "event_type": "answer",
                    "retry_attempt": 0,
                    "payload": {
                        "answer": "Vgs=2.9V",
                        "citations": ["pkt_000"],
                        "confidence": 0.8,
                        "evidence_scope": "full",
                    },
                },
                {
                    "stage": "verify",
                    "event_type": "verdict",
                    "payload": {
                        "supported": False,
                        "next_action": "expand_context",
                        "reason": "crop is too small",
                        "diagnostics": {
                            "target_packet_ids": ["pkt_000"],
                            "missing_context": ["axis_label"],
                        },
                    },
                },
            ],
            "evidence_snapshot": [
                {
                    "packet_id": "pkt_000",
                    "page": 2,
                    "bbox_norm": [0.1, 0.2, 0.3, 0.4],
                    "region_type": "line_chart",
                    "confidence": 0.9,
                    "local_crop_ref": "abc.png",
                    "linked_neighbor_types": ["caption"],
                    "multi_scale_crops": [{"scale": "tight", "bbox_norm": [0.1, 0.2, 0.3, 0.4]}],
                    "ocr_snippet": "Vgs=2.9V",
                }
            ],
        },
    }


def test_summarize_record_extracts_agent_view_fields() -> None:
    row = aea.summarize_record(_record("dat-x-0001", correct=0.0))

    assert row["example_id"] == "dat-x-0001"
    assert row["question_family"] == "curve_axis_reading"
    assert row["final_verdict"]["next_action"] == "expand_context"
    assert row["final_verdict"]["target_packet_ids"] == ["pkt_000"]
    assert row["answer_history"][0]["answer"] == "Vgs=2.9V"
    assert row["packets"][0]["text"] == "Vgs=2.9V"
    assert row["packets"][0]["multi_scale_crops"][0]["scale"] == "tight"


def test_build_audit_rows_defaults_to_wrong_and_high_iou_first() -> None:
    records = [
        _record("dat-low-0001", correct=0.0, iou=0.2),
        _record("dat-high-0001", correct=0.0, iou=0.9),
        _record("dat-correct-0001", correct=1.0, iou=1.0),
    ]

    rows = aea.build_audit_rows(records)

    assert [r["example_id"] for r in rows] == ["dat-high-0001", "dat-low-0001"]


def test_render_index_links_example_viewer(tmp_path: Path) -> None:
    out = tmp_path / "index.html"
    aea.render_index([aea.summarize_record(_record("dat-x-0001", correct=0.0))], out)

    text = out.read_text()
    assert "Agent Eyes Audit" in text
    assert 'href="examples/dat-x-0001.html"' in text
    assert "crop is too small" in text


def test_load_prediction_records_uses_path_stem_when_missing_id(tmp_path: Path) -> None:
    spec = tmp_path / "spec"
    pred_dir = spec / "predictions"
    pred_dir.mkdir(parents=True)
    (pred_dir / "dat-x-0001.json").write_text(json.dumps({"answer_correct": 0.0}))

    records = aea.load_prediction_records(spec)

    assert records[0]["example_id"] == "dat-x-0001"
