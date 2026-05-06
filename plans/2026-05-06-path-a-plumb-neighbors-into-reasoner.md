# Path A — plumb expand_context neighbors into the reasoner

## Overview

Today's diagnosis (2026-05-05) revealed that `expand_context`'s neighbor
attachment is dead code for accuracy — `pipeline/reasoner.py` never reads
`packet.linked_crop_refs` or `packet.linked_neighbor_types`. The +6pp
+2-vs-+4 inversion observed in rebaseline-v2 was **upstream LLM variance**
(planner / router / reranker stochasticity), not expand_context.

This plan completes the original "more tools = good" architecture: plumb
the neighbor crops + types into the reasoner so the extra context the
expander already gathers actually informs the answer.

## Current State Analysis

**The dead-code path** (`pipeline/reasoner.py:146-174`):

```python
def _collect_packet_images(evidence: EvidenceEvent) -> list[Path]:
    seen: set[str] = set()
    images: list[Path] = []
    for p in evidence.packets:
        if p.multi_scale_crops:
            for scaled in p.multi_scale_crops:
                images.append(Path(scaled.ref))
            continue
        ref = p.local_crop_ref or p.page_thumbnail_ref
        if ref:
            images.append(Path(ref))
    return images
```

Only multi_scale_crops + local_crop_ref are passed to the model. The
linked_crop_refs (populated by `expand_context`, ~13 per example pre-B1,
~2 per example post-B1.5) never reach `backend_client.predict(images=)`.

**The descriptor path** (`pipeline/reasoner.py:121-143`):

```python
def _render_packet_line(packet) -> str:
    base = f"- {packet.packet_id}: page {packet.page}, bbox {packet.bbox_norm}"
    n_scales = len(packet.multi_scale_crops)
    if n_scales >= 2:
        base += f" — {n_scales} image scales (tight + context)"
    if packet.chart_csv:
        base += "\n  Chart extraction ..."
    return base
```

No mention of `linked_neighbor_types` or count of attached neighbors.

**Empirical evidence the path is dead**:

- `grep -n "linked\|neighbor\|expand" src/focusparse/pipeline/reasoner.py` returns **zero matches**.
- A focus +4 prediction with 3 linked_crop_refs on pkt_0 produces the same image-list shape (counted by `_collect_packet_images`) as a focus +2 prediction with 0 linked_crop_refs on pkt_0.
- The +6pp +2-vs-+4 difference is fully explained by different upstream
  region picks (different pages, different bboxes — see MEMORY.md
  2026-05-06 entry).

## Desired End State

After Path A:

1. Reasoner's `_collect_packet_images` enumerates linked_crop_refs after
   the primary crop — so the model sees focus + neighbors in the prompt's
   image list.
2. Reasoner's `_render_packet_line` annotates each packet's neighbor types
   ("Attached neighbors: caption, footnote") so the model knows which
   crops are context vs primary.
3. A/B at n=148 against rebaseline-v2 focus +4 (the existing baseline).
   Decision rule:
   - ≥+3pp Overall non-overlapping CIs → ship default-on; expand_context
     is now load-bearing.
   - 0 to +3pp → ship as opt-in flag, document what families benefit.
   - Negative → revert; expand_context's image-attachment shape is
     net-noisy and we should pivot to Path B (text-summary attachment).

## Implementation Approach

Single-commit-per-concern. Three commits + one A/B run.

### Commit 1: extend `_collect_packet_images` to walk `linked_crop_refs`

**File**: `src/focusparse/pipeline/reasoner.py`

```python
def _collect_packet_images(evidence: EvidenceEvent) -> list[Path]:
    seen: set[str] = set()
    images: list[Path] = []
    for p in evidence.packets:
        # Primary crop(s).
        if p.multi_scale_crops:
            for scaled in p.multi_scale_crops:
                ref = scaled.ref
                if ref and ref not in seen:
                    seen.add(ref)
                    images.append(Path(ref))
        else:
            ref = p.local_crop_ref or p.page_thumbnail_ref
            if ref and ref not in seen:
                seen.add(ref)
                images.append(Path(ref))
        # Sprint 2026-05-06 (Path A): linked neighbor crops from
        # expand_context. Today's data showed these were populated but
        # never reached the reasoner.
        for neighbor_ref in p.linked_crop_refs or []:
            if neighbor_ref and neighbor_ref not in seen:
                seen.add(neighbor_ref)
                images.append(Path(neighbor_ref))
    return images
```

Tests in `tests/test_reasoner.py`:

- `test_collect_packet_images_includes_linked_crop_refs`: a packet with
  2 linked_crop_refs → image list has primary + 2 neighbors in order.
- `test_collect_packet_images_dedupes_neighbors_across_packets`: same
  neighbor ref attached to two different packets → appears once.
- `test_collect_packet_images_skips_empty_neighbor_refs`: empty string
  refs filtered out.

### Commit 2: extend `_render_packet_line` to mention neighbor types

```python
def _render_packet_line(packet) -> str:
    base = f"- {packet.packet_id}: page {packet.page}, bbox {packet.bbox_norm}"
    n_scales = len(packet.multi_scale_crops)
    if n_scales >= 2:
        base += f" — {n_scales} image scales (tight + context)"
    # Sprint 2026-05-06 (Path A): if the expander attached neighbors,
    # tell the reasoner what they are so it knows which images are
    # primary focus vs context.
    if packet.linked_neighbor_types:
        types = ", ".join(packet.linked_neighbor_types)
        base += f"\n  Attached neighbors ({len(packet.linked_neighbor_types)}): {types}"
    if packet.chart_csv:
        # ... existing chart_csv block
    return base
```

Tests:

- `test_render_packet_line_lists_neighbor_types`
- `test_render_packet_line_omits_neighbors_when_empty`

### Commit 3: update reasoner system prompt to explain the layout

```python
_SYSTEM_PROMPT = (
    "You are answering a question about a document using the provided evidence packets. "
    "Each packet shows a page region with a packet_id (e.g. pkt_000). "
    "When a packet has 'Attached neighbors', the images that follow the "
    "primary crop are context (caption, footnote, section header, etc.). "
    "Use the primary crop for the answer; use the neighbors only when "
    "the answer requires reading the surrounding text. "
    "Return strict JSON with keys `answer`, `citations`, and `confidence`. "
    ...
)
```

Tests:

- `test_system_prompt_explains_neighbor_layout`

### A/B run

```bash
set -a && source .env && set +a && \
uv run python scripts/run_hf_eval.py \
  --agent focus --tool-set full \
  --protocol agentic_multi_page \
  --output-dir results/hf/sprint-2026-05-06/path-a-neighbors-as-images \
  --staging-dir ~/.cache/focusparse/hf_staging \
  --pdfs-root ~/.cache/focusparse/pdfs \
  --hf-revision 3774c67f8b814392b6d04c939e904f749a3f52eb
```

~$2 cost, ~10-15 min wall.

### Decision matrix

Compare against `results/hf/headline-v1-rebaseline-v2/focusparse_focus_agentic_multi_page_7d4b816d/run.json` (focus +4 baseline = 43.9% Overall).

| Result            | Action                                                                                      | Memory entry                                                                            |
| ----------------- | ------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| ≥+3pp non-overlap | Ship default-on. expand_context becomes load-bearing.                                       | "expand_context now reaches the reasoner; +Xpp lift on Y."                              |
| 0 to +3pp         | Ship as opt-in flag (`--show-neighbors`); investigate per-family wins.                      | "Marginal lift; helps {finance \| chart-questions} only."                               |
| Within ±2pp       | Treat as noise; expand_context's shape is wrong. Pivot to Path B (text-summary attachment). | "Image-attachment shape doesn't carry signal; trying text-summary next."                |
| Regression        | Revert plumbing; the original concern (more images = dilution) holds.                       | "Plumbing neighbors as images hurts; expand_context returns to advisory metadata only." |

## What we're NOT doing in Path A

- **Not changing expand_context.** B1+B1.5 already shipped query-aware
  selection; Path A just makes those selections actually reach the model.
  If Path A regresses, we revert THIS plumbing, not the B1/B1.5 expander
  fixes (those are still correct and useful for the trace viewer + future
  SFT data).
- **Not implementing Path B (text summaries).** That's a follow-up if
  Path A's image-attachment is net-noisy.
- **Not running the rebaseline again.** The 7-spec rebaseline-v2 stays
  the canonical baseline.
- **Not touching multi_scale_packets, chart_to_table, or auto_zoom.**
  Those are independent flags; this plan only changes how the reasoner
  consumes the EXPAND output, not the inspect output.

## References

- **Active sprint plan**: `plans/2026-05-04-harness-iteration-sprint.md`
- **Rebaseline data**: `results/hf/headline-v1-rebaseline-v2/`
- **Today's findings**: `.claude/memory/MEMORY.md` 2026-05-06 entry (to be written)
- **Today's commits**:
  - `e1737c2` Phase B1 (query-aware expand_context)
  - `5e42082` Phase B2 (query-aware auto_zoom + additive)
  - `6f11a58` Phase B3 (inspector ranker layers reranker signals)
  - `79c03dd` Phase B1.5 (tighter expand_context defaults)
- **B1 A/B (background)**: `results/hf/sprint-2026-05-05/phase-b1-query-aware-expand/` — focus +4 = 45.3% Overall (vs rebaseline-v2 43.9%; +1.4pp likely noise)
- **B1.5 A/B (in flight as of 2026-05-05 22:00 PDT)**: `results/hf/sprint-2026-05-05/phase-b1.5-tighter-expand/` — pending
