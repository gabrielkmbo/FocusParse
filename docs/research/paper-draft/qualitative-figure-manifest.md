# FocusParse Qualitative Figure Manifest

Date: 2026-05-24

Status: final-run qualitative manifest for the paper draft. This file records
the local viewer bundle and the example-level figure plan tied to the matched
n=148 headline package, not the older May 15 checkpoint.

## Source Artifacts

Benchmark source:

```text
/Users/gabrielbo/.cache/focusparse/paper-3774c67f8b814392b6d04c939e904f749a3f52eb/benchmark.jsonl
```

Verified FocusParse run:

```text
results/hf/paper/2026-05-24-paper-headline-v1/headline/focusparse_focus_agentic_multi_page_0b139a04/per_example.jsonl
```

Local viewer bundle generated for this manifest:

```text
results/agent_eyes/paper-final-headline-qualitative-focus-full/index.html
results/agent_eyes/paper-final-headline-qualitative-focus-full/agent_eyes_audit.jsonl
results/agent_eyes/paper-final-headline-qualitative-focus-full/examples/
```

Command used:

```bash
uv run python scripts/build_agent_eyes_audit.py --spec-dir results/hf/paper/2026-05-24-paper-headline-v1/headline/focusparse_focus_agentic_multi_page_0b139a04 --output-dir results/agent_eyes/paper-final-headline-qualitative-focus-full --staging-root /Users/gabrielbo/.cache/focusparse/paper-3774c67f8b814392b6d04c939e904f749a3f52eb --include-correct --limit 0 --example-id fin-bis_qr_2025_mar-0050 --example-id dat-JESD204B-Survival-Guide-0029 --example-id dat-adrv9040-reference-manual-ug-2192-0032 --example-id dat-infineon-applicationnote-mosfet-fast-switching-motivation--implementation-and-precautions-applicationnotes-en-0052
```

Important durability note: `results/` is gitignored. The viewer bundle is
useful for local inspection and figure drafting, but submission assets should
be copied into an explicit artifact package or regenerated from the pinned run.
The current viewer bundle is 187M and contains four example HTML files.

Regenerated page/crop asset bundle and composed panel package:

```text
results/trace_viewer/paper-final-qualitative-assets/
results/paper/qualitative-figure-panels/
results/paper/qualitative-baseline-comparisons/
```

Panel-generation commands and figure-specific paths are recorded in
`docs/research/paper-draft/qualitative-figure-panels.md`. Same-revision
baseline answers for the main qualitative examples are recorded in
`docs/research/paper-draft/qualitative-baseline-comparisons.md`.

## Asset Readiness Summary

| Figure candidate | Current readiness | Verified local assets | Remaining gate |
| --- | --- | --- | --- |
| Latvia finance cross-region | Main-text candidate | Final-run viewer, composed PNG panel, and same-revision baseline table generated. | Final venue-template styling and decide where to place comparator strip. |
| JESD204B datasheet cross-page | Main-text candidate | Final-run viewer, composed PNG panel, and same-revision baseline table generated. | Final venue-template styling and decide where to place comparator strip. |
| Infineon Q1/Q2 near-miss | Appendix or analysis candidate | Final-run viewer generated for page 7. | Use only with the low-IoU interpretation preserved. |
| ADRV9040 datasheet compaction near-miss | Failure-analysis candidate | Final-run viewer generated for pages 10, 75, and 114. | Do not present as a clean positive result unless rerun recovers the size field. |

## Figure 1: Finance Cross-Region Evidence Binding

Example id:

```text
fin-bis_qr_2025_mar-0050
```

Gold and prediction: `Latvia`

Verified metrics from the final FocusParse +4 run:

| Metric | Value |
| --- | --- |
| Answer correct | `1` |
| Page recall | `1.0` |
| BBox IoU | `0.9999935073355983` |
| Lazy answer | `0` |
| Benchmark family | `cross_page_continuation` |
| Audit/planner family | `multi_chart_comparison` |
| Supporting pages | `[8, 108, 109]` |
| Evidence page spread | `101` |
| Tool sequence | `inspect_region`, `expand_context`, `expand_context` |

Recommended panels:

| Panel | Purpose |
| --- | --- |
| Page 8 | Country abbreviation table resolving `LV` to `Latvia`. |
| Page 108 | Panel A evidence for cumulative real GDP growth and direct cross-border share. |
| Page 109 | Panel B evidence for bank-credit-to-GDP change and direct plus indirect cross-border share. |
| Packet strip | Show the inspect crop plus expanded caption/footnote/table context. |

Useful local viewer:

```text
results/agent_eyes/paper-final-headline-qualitative-focus-full/examples/fin-bis_qr_2025_mar-0050.html
```

Draft caption:

> Cross-region finance example. The answer requires binding small plotted labels
> in two separate BIS chart panels to a country-abbreviation table. FocusParse
> inspects high-resolution visual regions, then expands selected packets with
> nearby captions, footnotes, and table context before answering `Latvia`.

Submission gate:

Add same-revision Base VLM and generic-agent predictions for this exact example
so the final figure can show the failure mode without mixing benchmark
revisions.

## Figure 2: Datasheet Cross-Page Timing Evidence

Example id:

```text
dat-JESD204B-Survival-Guide-0029
```

Gold and prediction: `6`

Verified metrics from the final FocusParse +4 run:

| Metric | Value |
| --- | --- |
| Answer correct | `1` |
| Page recall | `1.0` |
| BBox IoU | `0.9999916798927161` |
| Lazy answer | `0` |
| Benchmark family | `axis_value_interpolation` |
| Audit/planner family | `timing_diagram_reading` |
| Supporting pages | `[16, 73]` |
| Evidence page spread | `57` |
| Tool sequence | `inspect_region`, `expand_context` |

Recommended panels:

| Panel | Purpose |
| --- | --- |
| Page 16 timing diagram | Count the contiguous K28.5 symbols on LANE0 between point 2 and point 3. |
| Page 16 ADC block diagram | Corroborate the lane data path. |
| Page 73 functional block diagram | Confirm how the serialized JESD204B output is situated in the device path. |
| Packet strip | Show the compact packet set that preserves the count and cross-page corroboration. |

Useful local viewer:

```text
results/agent_eyes/paper-final-headline-qualitative-focus-full/examples/dat-JESD204B-Survival-Guide-0029.html
```

Draft caption:

> Cross-page datasheet example. The model must count a small sequence of K28.5
> symbols in a timing diagram and verify the lane/path interpretation against
> block diagrams 57 pages apart. FocusParse converts the dense manual into a
> small inspected-and-expanded packet set before the reasoner returns `6`.

Submission gate:

Compose this as the primary datasheet success figure. It replaces the ADRV9040
case as the clean positive datasheet example because the final-run prediction
exactly matches the gold answer.

## Figure 3: Datasheet Near-Miss Visual Disambiguation

Example id:

```text
dat-infineon-applicationnote-mosfet-fast-switching-motivation--implementation-and-precautions-applicationnotes-en-0052
```

Gold and prediction: `Q1 (HS)`

Verified metrics from the final FocusParse +4 run:

| Metric | Value |
| --- | --- |
| Answer correct | `1` |
| Page recall | `1.0` |
| BBox IoU | `0.2562950055117036` |
| Lazy answer | `0` |
| Benchmark family | `near_miss_distractor` |
| Audit/planner family | `package_mechanical_reading` |
| Supporting pages | `[7]` |
| Evidence page spread | `0` |
| Tool sequence | `inspect_region`, `expand_context`, `expand_context` |

Recommended panels:

| Panel | Purpose |
| --- | --- |
| Page 7 | PCB layout with `Q1 (HS)` and `Q2 (LS)` labels. |
| Packet strip | Show how localized visual packets and captions avoid the near-miss label confusion. |
| Error-analysis inset | Show that answer correctness outpaces exact box placement in this row. |

Useful local viewer:

```text
results/agent_eyes/paper-final-headline-qualitative-focus-full/examples/dat-infineon-applicationnote-mosfet-fast-switching-motivation--implementation-and-precautions-applicationnotes-en-0052.html
```

Draft caption:

> Near-miss visual disambiguation example. FocusParse answers `Q1 (HS)` by
> using localized visual packets and surrounding caption context, but the low
> BBox IoU shows that answer correctness can outpace exact box placement. This
> makes the example better suited for analysis or appendix material than as a
> primary positive mechanism figure.

Submission gate:

Preserve the low-IoU interpretation. Do not present this as a clean
localization win.

## Figure 4: Datasheet Compaction Near-Miss

Example id:

```text
dat-adrv9040-reference-manual-ug-2192-0032
```

Gold answer: `ADRV9040_FW.bin, 641 kb`

Final-run prediction: `ADRV9040_FW.bin`

Verified metrics from the final FocusParse +4 run:

| Metric | Value |
| --- | --- |
| Answer correct | `1` |
| Page recall | `0.3333333333333333` |
| BBox IoU | `0.9999863279145578` |
| Lazy answer | `0` |
| Benchmark family | `chart_table_cross_ref` |
| Audit/planner family | `distant_evidence_fusion` |
| Supporting pages | `[10, 75, 114]` |
| Evidence page spread | `104` |
| Tool sequence | `inspect_region`, `expand_context`, `expand_context` |

Useful local viewer:

```text
results/agent_eyes/paper-final-headline-qualitative-focus-full/examples/dat-adrv9040-reference-manual-ug-2192-0032.html
```

Interpretation:

The scorer marks this row correct, but the final answer omits the `641 kb` size
field. Use this as an analysis example for compaction or answer-shape failure,
not as a main-text positive result. Its value is precisely that it exposes a
paper-relevant gap: FocusParse localized a useful file-name region, but the
final answer did not preserve every requested field from the cross-page table.

## Final Figure Package Checklist

Before submission, create a durable figure asset directory containing:

1. The exact `per_example.jsonl` used for each qualitative figure.
2. The exact benchmark rows and HF revision used for the prompts and gold
   evidence.
3. Page images for each panel, copied or symlinked into a stable artifact
   package.
4. Crop images or embedded viewer exports for every displayed packet, with
   packet ids in filenames.
5. A one-line render command for regenerating the local viewer.
6. Same-revision baseline predictions for any comparative qualitative panel.
