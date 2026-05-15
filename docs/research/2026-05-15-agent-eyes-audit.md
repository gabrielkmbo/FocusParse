# 2026-05-15 Agent Eyes Audit

Purpose: make accuracy failures inspectable through the same visual scope the
agent saw. Aggregate scores tell us whether a run improved; this audit is for
answering why a specific example failed.

## Artifacts

Generated from the complete context-only best run:

`results/hf/sprint-2026-05-15/chart-fallback-context-only-oai-run1/focusparse_focus_agentic_multi_page_8c5e328d`

Command:

```bash
uv run python scripts/build_agent_eyes_audit.py \
  --spec-dir results/hf/sprint-2026-05-15/chart-fallback-context-only-oai-run1/focusparse_focus_agentic_multi_page_8c5e328d \
  --output-dir results/agent_eyes/2026-05-15-context-only-wrong \
  --staging-root /Users/gabrielbo/.cache/focusparse/hf_staging_full_2026-05-13 \
  --limit 30
```

Entry point:

`results/agent_eyes/2026-05-15-context-only-wrong/index.html`

Machine-readable summaries:

`results/agent_eyes/2026-05-15-context-only-wrong/agent_eyes_audit.jsonl`

Each example page renders the page overlays, candidate/selected boxes, final
evidence packets, tight crops, context crops, linked neighbor crops, OCR/text
snippets, answer attempts, verifier payloads, and trajectory steps.

Regenerated after the 60.14% answer-shape run:

`results/hf/sprint-2026-05-15/answer-shape-normalizer-oai-run2/focusparse_focus_agentic_multi_page_8c5e328d`

Entry point:

`results/agent_eyes/2026-05-15-answer-shape-normalizer-wrong/index.html`

Important implementation detail: the audit builder now prefers
`per_example.jsonl` over `predictions/*.json`. The latter has one filename
collision for duplicated `example_id` values, while `per_example.jsonl`
preserves all 148 scored rows.

## First-Pass Findings

The 30 rendered rows are intentionally sorted by high page recall and high
bbox IoU first. These are the failures where the pipeline often saw the right
area but still failed.

Top question-family counts:

| Family | Count |
| --- | ---: |
| `confusable_label` | 7 |
| `chart_caption_fusion` | 5 |
| `direct_label_reading` | 3 |
| `schematic_value_lookup` | 3 |

Final verifier state among these 30:

| Verifier state | Count | Interpretation |
| --- | ---: | --- |
| `supported=true, accept` | 16 | Verifier false-accept or scorer-shape blind spot. |
| `supported=false, expand_context` | 8 | Evidence/readability issue detected, but repair did not resolve it. |
| `supported=false, escalate_reasoner` | 5 | Answer-shape or reasoning issue detected, but default controller usually does not spend a broad reasoner retry. |
| `supported=false, retry_localization` | 1 | Localization retry wanted but off by default. |

## Concrete Miss Patterns

1. **Right crop, answer too short for multi-clause question.**

   `dat-AN040_EN-0008` has page recall 1.0 and IoU ~1.0. The packet text
   includes the circuit, `Iwireless`, `VoutT=5V`, and the adapter/wireless
   priority note. The answer was only `Iwireless`; the gold expects both the
   label and the visual condition explaining wireless versus adapter supply.
   The verifier correctly flagged this as incomplete.

2. **Right crop, answer-shape mismatch.**

   `dat-infineon-...-0019` and `dat-infineon-...-0022` both answered
   `Vgs=2.9V` while gold is `Vgs = 2.9 V`. The crop and OCR are correct; this
   is a formatting/scorer compatibility failure, not a localization failure.
   The answer normalizer experiment targets this class.

3. **Correct evidence, partial table-cell answer.**

   `dat-DS8237AB-06-0017` sees the table row with `0.697 | 0.704 | 0.711` but
   returns only `0.704`. The question asks which min/typ/max value and the
   corresponding voltage. The verifier catches the incompleteness.

4. **Verifier false-accept on semantically wrong label.**

   `dat-infineon-power-mosfet-...-0047` accepts
   `Single Pulse Avalanche Energy (Thermally Limited)` even though the gold is
   `315 mJ`. The evidence includes the relevant avalanche table and explanatory
   text, but the verifier validates the row label instead of the requested
   value.

5. **Wrong sub-row / wrong part selection inside a table.**

   `dat-SG017_2022-0054` is a high-IoU table case where the model picks
   `RT9187C; SOT-23-5`, but the gold is `RTQ2510-QA, VDFN3x3-8`. This points
   to row-level comparison logic, not broad region detection.

## Engineering Implications

- The harness is no longer primarily failing by not cropping anything useful.
  Many top wrong rows have high page recall and high IoU.
- The 60.14% run confirms that narrow answer-shape normalization can recover
  scorer-compatible cases without forcing extra tool use.
- We need a stronger final-answer layer for three narrow classes:
  scorer-compatible formatting, multi-field/table-row completion, and
  multi-clause answer completeness.
- Verifier improvements should focus on comparing the answer against the exact
  question shape. A generic `accept` verdict is too permissive for
  `confusable_label`, `direct_label_reading`, and chart-caption fusion rows.
- More first-pass tools are unlikely to fix these rows unless the tool output
  changes answer selection. The next repairs should be verifier-directed and
  answer-shape-aware, not broad chart/tool overuse.
