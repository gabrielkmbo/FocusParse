"""INSPECT stage — ReActAgent loop over the tool belt.

Phase 2 skeleton: package each region into an `EvidencePacket` using the raw
page image as both thumbnail and local-crop ref. No tool calls yet — this is
the stub that lets the reasoner see structured evidence end-to-end.

Phase 3 strategy:
  - Wrap tools/*.py as FunctionTool instances.
  - Use llama_index.core.agent.workflow.ReActAgent.
  - Bind TokenCountingHandler with a token budget (raises BudgetExceeded).
  - Record each tool call as a TrajectoryStep.

The inspector decides when to stop based on:
  - Budget exhausted (max_tool_calls, max_crops, token budget).
  - Answer confidence > threshold.
  - Explicit abstain signal from the verifier loop.
"""

from __future__ import annotations

from pathlib import Path

from focusparse.evidence.packet import EvidencePacket, PacketProvenance
from focusparse.pipeline.events import (
    EvidenceEvent,
    PlanEvent,
    QuestionEvent,
    RegionsEvent,
)


async def inspect_regions(
    question: QuestionEvent,
    plan: PlanEvent,
    regions: RegionsEvent,
    *,
    images_by_page: dict[int, Path],
) -> EvidenceEvent:
    """Skeleton: one packet per region, ref'ing the page image directly.

    `images_by_page` maps 1-indexed page number -> local PNG path. Skeleton
    does no cropping; both `page_thumbnail_ref` and `local_crop_ref` point at
    the raw page image so the reasoner can still see the content.
    """
    del question, plan  # unused in skeleton
    packets: list[EvidencePacket] = []
    for idx, region in enumerate(regions.candidates):
        image_path = images_by_page.get(region.page)
        image_ref = str(image_path) if image_path is not None else ""
        packets.append(
            EvidencePacket(
                packet_id=f"pkt_{idx:03d}",
                page=region.page,
                bbox_norm=region.bbox_norm,
                region_type=region.region_type,
                page_thumbnail_ref=image_ref,
                local_crop_ref=image_ref,
                provenance=PacketProvenance(
                    tool="skeleton_inspector",
                    mode="full_page",
                    args_hash="",
                ),
                confidence=region.score,
            )
        )
    return EvidenceEvent(packets=packets)
