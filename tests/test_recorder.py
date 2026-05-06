"""Tests for the trajectory recorder + RunTrace schema v3."""

from __future__ import annotations

from focusparse.traces.recorder import (
    EvidencePacketSummary,
    RunTrace,
    TraceArtifact,
    TraceDebugEvent,
    TrajectoryRecorder,
    TrajectoryStep,
)


def test_recorder_starts_empty() -> None:
    rec = TrajectoryRecorder(example_id="ex1", question="What?")
    trace = rec.finalize(answer=None)
    assert trace.example_id == "ex1"
    assert trace.steps == []
    assert trace.final_answer is None
    assert trace.evidence_snapshot is None
    assert trace.artifacts == []
    assert trace.debug_events == []


def test_recorder_records_steps_in_order() -> None:
    rec = TrajectoryRecorder(example_id="ex1", question="Q?")
    rec.record(TrajectoryStep(step_index=0, stage="plan", tier="cheap", action="llm_call"))
    rec.record(TrajectoryStep(step_index=1, stage="answer", tier="frontier", action="llm_call"))
    trace = rec.finalize(answer="42", citations=[{"page": 1, "bbox": [0.0, 0.0, 1.0, 1.0]}])
    assert [s.step_index for s in trace.steps] == [0, 1]
    assert trace.final_answer == "42"
    assert trace.final_citations[0]["page"] == 1


def test_evidence_snapshot_default_none() -> None:
    """Legacy v1 traces (no snapshot set) serialize evidence_snapshot=None."""
    rec = TrajectoryRecorder(example_id="ex1", question="Q?")
    trace = rec.finalize(answer="x")
    dumped = trace.model_dump(mode="json")
    assert dumped["evidence_snapshot"] is None


def test_evidence_snapshot_round_trip() -> None:
    """v2 snapshot survives model_dump → model_validate."""
    rec = TrajectoryRecorder(example_id="ex1", question="Q?")
    snap = [
        EvidencePacketSummary(
            packet_id="pkt_000",
            page=3,
            bbox_norm=(0.1, 0.2, 0.5, 0.6),
            region_type="picture",
            local_crop_ref="cache/crops/abc123.png",
            linked_crop_refs=["cache/crops/def456.png"],
            text_layer_snippet="hello",
            ocr_snippet=None,
            confidence=0.87,
            provenance_tool="deterministic_inspector",
        )
    ]
    rec.set_evidence_snapshot(snap)
    trace = rec.finalize(answer="ok")

    dumped = trace.model_dump(mode="json")
    assert dumped["evidence_snapshot"] is not None
    assert dumped["evidence_snapshot"][0]["packet_id"] == "pkt_000"
    assert dumped["evidence_snapshot"][0]["bbox_norm"] == [0.1, 0.2, 0.5, 0.6]

    rehydrated = RunTrace.model_validate(dumped)
    assert rehydrated.evidence_snapshot is not None
    assert len(rehydrated.evidence_snapshot) == 1
    assert rehydrated.evidence_snapshot[0].confidence == 0.87


def test_set_evidence_snapshot_copies_list() -> None:
    """Mutating the original list after set should not change the trace."""
    rec = TrajectoryRecorder(example_id="ex1", question="Q?")
    snap = [
        EvidencePacketSummary(packet_id="a", page=1, bbox_norm=(0.0, 0.0, 1.0, 1.0)),
    ]
    rec.set_evidence_snapshot(snap)
    snap.append(EvidencePacketSummary(packet_id="b", page=2, bbox_norm=(0.0, 0.0, 1.0, 1.0)))
    trace = rec.finalize(answer="x")
    assert trace.evidence_snapshot is not None
    assert len(trace.evidence_snapshot) == 1
    assert trace.evidence_snapshot[0].packet_id == "a"


def test_evidence_packet_summary_defaults() -> None:
    """Comparator-style minimal summary (no crops, no text)."""
    s = EvidencePacketSummary(packet_id="x", page=1, bbox_norm=(0.0, 0.0, 0.5, 0.5))
    assert s.region_type is None
    assert s.local_crop_ref is None
    assert s.linked_crop_refs == []
    assert s.text_layer_snippet is None
    assert s.confidence == 1.0


def test_trace_artifact_and_debug_event_round_trip() -> None:
    rec = TrajectoryRecorder(example_id="ex1", question="Q?")
    rec.add_artifact(
        TraceArtifact(
            artifact_id="crop:pkt_000",
            kind="crop",
            path="/cache/crops/abc.png",
            page=2,
            bbox_norm=(0.1, 0.2, 0.3, 0.4),
            packet_id="pkt_000",
            stage="inspect",
            label="tight crop",
        )
    )
    rec.add_debug_event(
        TraceDebugEvent(
            event_id="inspect:0",
            stage="inspect",
            event_type="evidence_packets",
            step_index=4,
            payload={"packet_ids": ["pkt_000"]},
        )
    )
    trace = rec.finalize(answer="x")

    dumped = trace.model_dump(mode="json")
    assert dumped["artifacts"][0]["artifact_id"] == "crop:pkt_000"
    assert dumped["artifacts"][0]["bbox_norm"] == [0.1, 0.2, 0.3, 0.4]
    assert dumped["debug_events"][0]["event_type"] == "evidence_packets"

    rehydrated = RunTrace.model_validate(dumped)
    assert rehydrated.artifacts[0].kind == "crop"
    assert rehydrated.debug_events[0].payload["packet_ids"] == ["pkt_000"]


def test_v2_style_trace_defaults_v3_fields() -> None:
    trace = RunTrace.model_validate({"example_id": "ex1", "question": "Q?"})
    assert trace.artifacts == []
    assert trace.debug_events == []


def test_step_obs_summary_and_confidence_persist() -> None:
    """A1 (2026-05-04): obs_summary + confidence must round-trip on the step."""
    rec = TrajectoryRecorder(example_id="ex1", question="Q?")
    rec.record(
        TrajectoryStep(
            step_index=0,
            stage="answer",
            tier="frontier",
            action="llm_call",
            obs_summary="model said: foo bar",
            confidence=0.42,
        )
    )
    trace = rec.finalize(answer="x")
    dumped = trace.model_dump(mode="json")
    assert dumped["steps"][0]["obs_summary"] == "model said: foo bar"
    assert dumped["steps"][0]["confidence"] == 0.42
