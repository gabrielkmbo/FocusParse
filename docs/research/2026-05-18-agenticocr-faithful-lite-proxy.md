# AgenticOCR-Style Faithful-Lite Proxy

Worker 4 added `--agent agentic_ocr` as a related-work comparator. This is not
the official trained AgenticOCR code or model. It is a faithful-lite proxy for
the method identity: query-conditioned on-demand zoom/OCR over small crops.

## Method

- Action vocabulary is fixed to `image`, `element`, and `region`, each mapped
  to the existing `inspect_region` modes.
- `get_text_layer` is used only for bounded page hints before the crop policy
  runs. Final answers are grounded in inspected crop evidence.
- Near-full-page crop requests (`area > 0.60`) are rejected and counted.
- Duplicate same-page overlapping crop requests (`IoU > 0.70`) are rejected
  and counted.
- The final `WorkflowResult` includes normal citations plus `evidence_ref`
  keys that point to trace evidence packets such as `agenticocr_pkt_000`.

## Metadata

Per-example records expose the proxy metadata in:

- `telemetry.agentic_ocr`
- `agentic_ocr_meta`
- `trace.evidence_snapshot`
- `trace.artifacts`

Useful fields include `inspected_crop_count`, `lazy_crop_count`,
`duplicate_crop_count`, `rejected_crop_count`, `largest_crop_area_ratio`,
`near_full_page_crop_rate`, and `duplicate_crop_rate`.

## Verification

Focused tests cover lazy-crop rejection, duplicate suppression, page-hint use,
missing-PDF abstention, and CLI result wrapping:

```bash
uv run --extra dev python -m pytest tests/test_agentic_ocr_agent.py -v
uv run --extra dev python -m pytest tests/test_hf_eval_cli.py -q
```
