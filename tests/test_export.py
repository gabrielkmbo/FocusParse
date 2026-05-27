"""Tests for trajectory JSONL export + schema v4."""

from __future__ import annotations

import json

from focusparse.traces.export import (
    SCHEMA_VERSION,
    export_eval_run_sft_jsonl,
    export_sft_jsonl,
    load_eval_run_traces,
    trace_to_sft_record,
)
from focusparse.traces.recorder import (
    EvidencePacketSummary,
    RunTrace,
    TraceArtifact,
    TraceDebugEvent,
    TrajectoryRecorder,
    TrajectoryStep,
)


def _make_trace(*, with_snapshot: bool = False) -> RunTrace:
    rec = TrajectoryRecorder(example_id="ex1", question="What?")
    rec.record(
        TrajectoryStep(
            step_index=0,
            stage="answer",
            tier="frontier",
            action="llm_call",
            obs_summary="42",
            confidence=0.9,
            tokens_in=10,
            tokens_out=2,
            usd=0.001,
        )
    )
    if with_snapshot:
        rec.set_evidence_snapshot(
            [
                EvidencePacketSummary(
                    packet_id="pkt_000",
                    page=1,
                    bbox_norm=(0.0, 0.0, 0.5, 0.5),
                    region_type="picture",
                    local_crop_ref="cache/crops/abc.png",
                    linked_crop_refs=["cache/crops/caption.png"],
                    linked_neighbor_types=["caption"],
                ),
            ]
        )
    rec.add_artifact(
        TraceArtifact(
            artifact_id="crop:pkt_000",
            kind="crop",
            path="cache/crops/abc.png",
            packet_id="pkt_000",
        )
    )
    rec.add_debug_event(
        TraceDebugEvent(
            event_id="inspect:0",
            stage="inspect",
            event_type="evidence_packets",
            payload={"packet_ids": ["pkt_000"]},
        )
    )
    return rec.finalize(
        answer="42",
        citations=[{"page": 1, "bbox": [0.0, 0.0, 0.5, 0.5]}],
        reward={"answer": 1.0, "coverage": 1.0, "iou": 0.8},
    )


def test_schema_version_is_4() -> None:
    assert SCHEMA_VERSION == "4"


def test_record_includes_schema_version_and_evidence_snapshot_field() -> None:
    rec = trace_to_sft_record(_make_trace(with_snapshot=False))
    assert rec["schema_version"] == "4"
    assert "evidence_snapshot" in rec
    assert rec["evidence_snapshot"] is None
    assert rec["artifacts"][0]["path"] == "cache/crops/abc.png"
    assert rec["debug_events"][0]["event_type"] == "evidence_packets"


def test_record_with_snapshot_round_trip() -> None:
    rec = trace_to_sft_record(_make_trace(with_snapshot=True))
    assert rec["evidence_snapshot"] is not None
    assert len(rec["evidence_snapshot"]) == 1
    assert rec["evidence_snapshot"][0]["packet_id"] == "pkt_000"
    assert rec["evidence_snapshot"][0]["local_crop_ref"] == "cache/crops/abc.png"
    assert rec["evidence_snapshot"][0]["linked_neighbor_types"] == ["caption"]


def test_export_sft_jsonl_writes_filtered_records(tmp_path) -> None:
    out = tmp_path / "traces.jsonl"
    n = export_sft_jsonl(
        [_make_trace(with_snapshot=True)],
        out,
        min_coverage=0.5,
        min_iou=0.3,
        require_correct=True,
    )
    assert n == 1
    line = out.read_text().strip()
    parsed = json.loads(line)
    assert parsed["schema_version"] == "4"
    assert parsed["evidence_snapshot"][0]["packet_id"] == "pkt_000"
    # SFT records carry references only; image bytes are HTML-renderer-only.
    assert "data:image" not in line


def test_export_sft_jsonl_filters_low_iou(tmp_path) -> None:
    rec = TrajectoryRecorder(example_id="ex2", question="Q?")
    trace = rec.finalize(
        answer="x",
        reward={"answer": 1.0, "coverage": 1.0, "iou": 0.1},  # below default 0.3
    )
    out = tmp_path / "traces.jsonl"
    n = export_sft_jsonl([trace], out)
    assert n == 0
    assert out.read_text() == ""


def test_step_obs_summary_and_confidence_persist_in_record() -> None:
    rec = trace_to_sft_record(_make_trace(with_snapshot=False))
    step = rec["trajectory"][0]
    assert step["obs_summary"] == "42"
    assert step["confidence"] == 0.9


def test_load_eval_run_traces_from_per_example_jsonl(tmp_path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    record = {
        "example_id": "ex3",
        "answer_pred": "42",
        "answer_correct": 1.0,
        "page_recall": 1.0,
        "bbox_iou": 0.75,
        "evidence_reward": 0.8,
        "citations": [{"page": 1}],
        "trace": {
            "steps": [
                {
                    "step_index": 0,
                    "stage": "answer",
                    "tier": "frontier",
                    "action": "llm_call",
                    "obs_summary": "42",
                }
            ],
            "evidence_snapshot": None,
            "artifacts": [],
            "debug_events": [],
        },
    }
    (run_dir / "per_example.jsonl").write_text(json.dumps(record) + "\n")

    traces = load_eval_run_traces(run_dir)

    assert len(traces) == 1
    assert traces[0].example_id == "ex3"
    assert traces[0].final_answer == "42"
    assert traces[0].reward == {"answer": 1.0, "coverage": 1.0, "iou": 0.75, "evidence": 0.8}


def test_export_eval_run_sft_jsonl(tmp_path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    record = {
        "example_id": "ex4",
        "answer_pred": "yes",
        "answer_correct": 1.0,
        "page_recall": 1.0,
        "bbox_iou": 0.9,
        "trace": {"steps": [], "artifacts": [], "debug_events": []},
    }
    (run_dir / "per_example.jsonl").write_text(json.dumps(record) + "\n")
    out = tmp_path / "sft.jsonl"

    n = export_eval_run_sft_jsonl(run_dir, out)

    assert n == 1
    assert json.loads(out.read_text())["example_id"] == "ex4"
