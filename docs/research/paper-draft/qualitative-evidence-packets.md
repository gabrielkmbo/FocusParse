# FocusParse Qualitative Evidence Packets

Date: 2026-05-24

Status: candidate qualitative examples for the paper draft, refreshed against
the final matched n=148 headline package at
`results/hf/paper/2026-05-24-paper-headline-v1/`. Figure asset status is
tracked in `docs/research/paper-draft/qualitative-figure-manifest.md`; use that
manifest, not this prose packet file, to decide whether an example has verified
page or crop assets ready for a submission figure.

## Source Discipline

Benchmark source:

```text
/Users/gabrielbo/.cache/focusparse/paper-3774c67f8b814392b6d04c939e904f749a3f52eb/benchmark.jsonl
```

Verified FocusParse run source:

```text
results/hf/paper/2026-05-24-paper-headline-v1/headline/focusparse_focus_agentic_multi_page_0b139a04/per_example.jsonl
```

Local qualitative viewer:

```text
results/agent_eyes/paper-final-headline-qualitative-focus-full/index.html
```

Do not mix older May 15 qualitative traces into final paper claims without
explicitly labeling them as historical. The examples below are from the same
pinned dataset revision and code/config package as the final headline table.

## Example 1: Finance Cross-Region Evidence Binding

Example id:

```text
fin-bis_qr_2025_mar-0050
```

Prompt:

```text
Based on the graphs and footnotes, identify the country that experienced both a
large negative cumulative real GDP growth (below -12%) with a direct
cross-border share above 10% in panel A, and also a positive change in the
ratio of bank credit to GDP above 12% with a change in direct plus indirect
cross-border share above 30% in panel B. What is the name of this country?
```

Gold answer: `Latvia`

Benchmark metadata:

| Field | Value |
| --- | --- |
| Domain | finance |
| Question family | `cross_page_continuation` |
| Supporting pages | `[8, 108, 109]` |
| Evidence page spread | `101` |
| Multi-region required | `true` |
| Requires visual evidence | `true` |

Verified FocusParse result:

| Metric | Value |
| --- | --- |
| Prediction | `Latvia` |
| Correct | `1` |
| Page recall | `1.0` |
| BBox IoU | `0.9999935073355983` |
| Lazy answer | `0` |
| Tool calls | `1` |
| Tool sequence | `inspect_region`, `expand_context`, `expand_context` |

Mechanism note:

The benchmark reasoning chain requires binding a country abbreviation table to
two separate visual panels and footnotes across pages 8, 108, and 109. The
FocusParse trace constructs evidence packets for the relevant figures and the
country table, then expands selected regions with nearby captions, footnotes,
and table context. This is the cleanest finance example for the paper's
inspect/expand thesis: the answer depends less on seeing a page and more on
collecting the right visual regions plus the symbol table needed to decode
them.

Paper-ready use:

Use this as the primary qualitative figure for finance. The figure should show
the two panel crops, the country-table crop mapping `LV` to `Latvia`, and a
small trace strip with the inspect/expand sequence.

## Example 2: Datasheet Cross-Page Timing Evidence

Example id:

```text
dat-JESD204B-Survival-Guide-0029
```

Prompt:

```text
Using the timing diagram in region r_016_13 and corroborating the lane data path
with the ADC processing block diagram in region r_016_10 and the functional
block diagram in region r_073_05, count the number of K28.5 symbols shown on
LANE0 between point 2 and point 3 (i.e., the contiguous sequence of K28.5s
after SYNC deasserts at point 2 and before the dashed/elided segment that ends
at point 3). Report the integer count.
```

Gold answer: `6`

Benchmark metadata:

| Field | Value |
| --- | --- |
| Domain | datasheet |
| Question family | `axis_value_interpolation` |
| Supporting pages | `[16, 73]` |
| Evidence page spread | `57` |
| Multi-region required | `true` |
| Requires visual evidence | `true` |

Verified FocusParse result:

| Metric | Value |
| --- | --- |
| Prediction | `6` |
| Correct | `1` |
| Page recall | `1.0` |
| BBox IoU | `0.9999916798927161` |
| Lazy answer | `0` |
| Tool calls | `1` |
| Tool sequence | `inspect_region`, `expand_context` |

Mechanism note:

The row asks for a count in a dense timing diagram, but the prompt also requires
cross-page corroboration from the ADC processing and functional block diagrams.
The evidence page spread is 57 pages, and the final trace solves it with a
small inspect/expand sequence instead of asking the reasoner to absorb the full
manual. This is now the cleanest datasheet success figure because the final
prediction exactly matches the gold answer.

Paper-ready use:

Use this as the primary datasheet success figure. The figure should show the
timing diagram region with the K28.5 sequence, a compact view of the
corroborating diagrams, and a packet strip that makes the evidence compaction
visible.

## Example 3: Datasheet Near-Miss Visual Disambiguation

Example id:

```text
dat-infineon-applicationnote-mosfet-fast-switching-motivation--implementation-and-precautions-applicationnotes-en-0052
```

Prompt:

```text
In subfigure (b) (the PCB layout photograph), one MOSFET is annotated 'Q1 (HS)'
and the other 'Q2 (LS)'. Which of the two MOSFETs (Q1 or Q2) is positioned at
the top of the package layout, immediately adjacent to the row of V_in
decoupling capacitors C15-C18?
```

Gold answer: `Q1 (HS)`

Benchmark metadata:

| Field | Value |
| --- | --- |
| Domain | datasheet |
| Question family | `near_miss_distractor` |
| Supporting pages | `[7]` |
| Evidence page spread | `0` |
| Multi-region required | `false` |
| Requires visual evidence | `true` |

Verified FocusParse result:

| Metric | Value |
| --- | --- |
| Prediction | `Q1 (HS)` |
| Correct | `1` |
| Page recall | `1.0` |
| BBox IoU | `0.2562950055117036` |
| Lazy answer | `0` |
| Tool calls | `1` |
| Tool sequence | `inspect_region`, `expand_context`, `expand_context` |

Mechanism note:

This is useful as a secondary example, not the strongest localization example.
The answer is correct, and the trace uses inspect/expand around the target page
and captions, but the BBox IoU is much lower than in the finance and JESD
success cases. It supports the paper's visual near-miss narrative while also
showing that answer correctness can outpace localization quality.

Paper-ready use:

Use this either as an appendix example or as an honest analysis case: FocusParse
can use contextual expansion to avoid the `Q1` versus `Q2` confusion, but the
final crop metric shows that precise box localization remains a failure mode.

## Example 4: Datasheet Compaction Near-Miss

Example id:

```text
dat-adrv9040-reference-manual-ug-2192-0032
```

Prompt:

```text
According to the initialization process described, which firmware file must be
loaded first to enable the ARM processor to handle JESD204B/204C interface
timing as depicted in the chart, and what is the listed size of this firmware
file? Explain how the initialization sequence and the table support your answer.
```

Gold answer: `ADRV9040_FW.bin, 641 kb`

Benchmark metadata:

| Field | Value |
| --- | --- |
| Domain | datasheet |
| Question family | `chart_table_cross_ref` |
| Supporting pages | `[10, 75, 114]` |
| Evidence page spread | `104` |
| Multi-region required | `true` |
| Requires visual evidence | `true` |

Verified FocusParse result:

| Metric | Value |
| --- | --- |
| Prediction | `ADRV9040_FW.bin` |
| Correct | `1` |
| Page recall | `0.3333333333333333` |
| BBox IoU | `0.9999863279145578` |
| Lazy answer | `0` |
| Tool calls | `1` |
| Tool sequence | `inspect_region`, `expand_context`, `expand_context` |

Mechanism note:

This row should no longer be used as the primary positive datasheet figure. It
is still paper-useful because it exposes a specific failure mode: the trace
localizes a useful file-name region, and the scorer marks the row correct, but
the final answer omits the requested `641 kb` size. The gap belongs in analysis
or limitations, not in the main success narrative.

Paper-ready use:

Use this as a compaction or answer-shape near-miss if the paper needs a
failure-analysis panel. Do not cite it as evidence that the final run preserves
both the firmware file and size fields.

## Submission Follow-Ups

Before camera-ready or arXiv submission:

1. Export final page images and crop overlays into a durable artifact package.
2. Regenerate Base VLM, ReAct, generic agent, and FocusParse predictions for
   the main qualitative example ids if comparative panels are included.
3. Record the code commit, dataset revision, and run directory beside every
   qualitative figure.
4. Keep the headline table tied to the verified 61.5% matched run unless the
   documented 66.9% checkpoint is recovered/rerun with raw artifacts.
