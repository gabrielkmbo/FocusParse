# FocusParse Qualitative Figure Panels

Date: 2026-05-24

Status: first composed paper-figure panels generated from the final matched
FocusParse +4 run. These are draft panels, but they are concrete PNG assets
rather than prose-only figure plans.

## Source Bundle

Regenerated trace asset bundle:

```text
results/trace_viewer/paper-final-qualitative-assets/
```

Command:

```bash
uv run python scripts/build_pipeline_demo.py --spec-dir results/hf/paper/2026-05-24-paper-headline-v1/headline/focusparse_focus_agentic_multi_page_0b139a04 --benchmark-jsonl /Users/gabrielbo/.cache/focusparse/paper-3774c67f8b814392b6d04c939e904f749a3f52eb/benchmark.jsonl --staging-root /Users/gabrielbo/.cache/focusparse/paper-3774c67f8b814392b6d04c939e904f749a3f52eb --output-dir results/trace_viewer/paper-final-qualitative-assets --example-id fin-bis_qr_2025_mar-0050 --example-id dat-JESD204B-Survival-Guide-0029 --example-id dat-infineon-applicationnote-mosfet-fast-switching-motivation--implementation-and-precautions-applicationnotes-en-0052 --example-id dat-adrv9040-reference-manual-ug-2192-0032
```

Output summary:

```text
Wrote 4 example(s) and 144 asset(s) to results/trace_viewer/paper-final-qualitative-assets
```

## Composed Panel Package

Panel package:

```text
results/paper/qualitative-figure-panels/
```

Command:

```bash
uv run python scripts/build_paper_qualitative_panels.py --bundle-dir results/trace_viewer/paper-final-qualitative-assets --output-dir results/paper/qualitative-figure-panels
```

Output summary:

```text
Wrote 2 figure panel(s) to results/paper/qualitative-figure-panels
```

Generated files:

| File | Purpose |
| --- | --- |
| `figure3-finance-latvia-evidence-binding.png` | Main-text finance mechanism figure: two chart regions plus `LV -> Latvia` table-row zoom. |
| `figure4-datasheet-jesd204b-evidence-binding.png` | Main-text datasheet mechanism figure: timing count plus cross-page path corroboration. |
| `asset-inventory.csv` | Concrete panel/crop/tile inventory with absolute and relative paths. |
| `presentation-visuals.md` | Slide-friendly handoff with grouped panel and crop paths. |

The composed PNGs are `2400 x 1600` and are meant as draft figure boards. They
still need venue-specific typography and final caption treatment before
submission, but the evidence shown comes from the final FocusParse +4 trace.

Same-revision baseline predictions for these two examples are generated under:

```text
results/paper/qualitative-baseline-comparisons/
```

Use `docs/research/paper-draft/qualitative-baseline-comparisons.md` to decide
whether the baseline contrast belongs in the figure body, caption, appendix, or
Results prose.

## Panel 1: Latvia Finance Evidence Binding

Panel path:

```text
results/paper/qualitative-figure-panels/figure3-finance-latvia-evidence-binding.png
```

Example id:

```text
fin-bis_qr_2025_mar-0050
```

What it shows:

- page 109 chart crop for the panel-B condition;
- page 108 chart crop for the panel-A condition;
- page 8 table-row zoom showing `LV -> Latvia`;
- the inspect/expand/answer/verify evidence-construction path.

Metrics from the final run:

| Metric | Value |
| --- | ---: |
| Prediction | `Latvia` |
| Page recall | `1.0` |
| BBox IoU | `0.9999935073355983` |

## Panel 2: JESD204B Datasheet Evidence Compaction

Panel path:

```text
results/paper/qualitative-figure-panels/figure4-datasheet-jesd204b-evidence-binding.png
```

Example id:

```text
dat-JESD204B-Survival-Guide-0029
```

What it shows:

- page 16 timing-diagram crop containing the K28.5 sequence;
- page 16 ADC/JESD lane-diagram crop;
- page 73 functional block diagram crop;
- the inspect/expand/answer/verify evidence-construction path.

Metrics from the final run:

| Metric | Value |
| --- | ---: |
| Prediction | `6` |
| Page recall | `1.0` |
| BBox IoU | `0.9999916798927161` |

## Current Limitations

- These are local `results/` assets and must be copied into a submission
  archive or regenerated from the commands above.
- The figures currently show FocusParse only. Same-revision baseline
  predictions now exist as a table artifact, but the final venue figures still
  need to decide whether to integrate that comparison visually or in captions.
- The panels are good enough for draft review and slide discussion; final
  camera-ready figures should be recreated in the venue template's style.
