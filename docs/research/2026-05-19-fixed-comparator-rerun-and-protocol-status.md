# Fixed Comparator Rerun And Protocol Status

Date: 2026-05-19

This is the corrective status note for the related-work comparison. The earlier
headline table was useful but incomplete: it did not constitute the full
protocol matrix, and some comparator rows were stale pre-fix runs. This note
separates what is decision-grade from what is implemented-but-unrun, then
summarizes the fixed full reruns for the harnessed comparators.

## Protocol Matrix Status

The current monitor matrix is pinned to:

- HF repo: `gabrielbo/parser-bench`
- split: `validation`
- revision: `3774c67f8b814392b6d04c939e904f749a3f52eb`
- expected canonical count: `n=148`
- expected unique example IDs: `147` because `dat-DS5091D-00-0016`
  appears twice in the pinned canonical slice

The matrix currently contains `43` cells:

| Status | Count | Meaning |
|---|---:|---|
| `verified` | 7 | Full pinned headline `agentic_multi_page` rows with the expected row count, revision, and duplicate-ID shape |
| `implemented` | 36 | Command/protocol wiring exists, but no full result artifact |

So the answer to "did we do the full protocol test for each method?" is **no**.
The only full decision-grade protocol completed for every headline method is
`agentic_multi_page`.

The 36 unrun appendix cells are:

- Methods: `basic_vlm`, `llamaindex_react_minimal`,
  `llamaindex_react_full`, `coding_agent`, `doclens`, `agentic_ocr`
- Protocols: `full_doc`, `oracle_page`, `oracle_crop`, `tiled_2up`,
  `tiled_4up`, `tiled_8up`

No `focusparse_reference` appendix protocol cells are present in the current
monitor matrix. Older local `simple` artifacts under
`/Users/gabrielbo/projects/FocusParse/results/hf/full-eval-v1/` are useful
historical sanity checks, but they are not decision-grade for this sweep because
they are not tied to the current pinned HF fingerprint/revision and only cover
the simple baseline.

## Fixed Full Rerun Results

All rows below are full `n=148` reruns on `agentic_multi_page` after applying
the method-branch fixes. They are ingested into the monitor's headline table
and copied into the tracked snapshot at
`docs/research/related-work-monitor/headline_table.md`.

| Method | Old full row | Fixed full rerun | Accuracy change | Page recall | BBox IoU | Cost/correct | Latency |
|---|---:|---:|---:|---:|---:|---:|---:|
| LlamaIndex ReAct +2 | 18/148 = 12.2% | 18/148 = 12.2% | +0.0 pp | 0.624 | 0.194 | $0.354 | 29.65s |
| LlamaIndex ReAct +4 | 9/148 = 6.1% | 15/148 = 10.1% | +4.1 pp | 0.616 | 0.369 | $0.520 | 30.13s |
| Coding Agent +4 | 1/148 = 0.7% | 38/148 = 25.7% | +25.0 pp | 0.756 | 0.466 | $0.143 | 18.17s |
| DocLens-style | 24/148 = 16.2% | 25/148 = 16.9% | +0.7 pp | 0.934 | 0.700 | $0.152 | 19.14s |
| AgenticOCR-style | 27/148 = 18.2% | 24/148 = 16.2% | -2.0 pp | 0.743 | 0.183 | $0.078 | 8.30s |

Reference anchors from the monitor table remain:

| Method | Accuracy | Page recall | BBox IoU | Cost/correct | Latency |
|---|---:|---:|---:|---:|---:|
| Basic VLM | 70/148 = 47.3% | 0.895 | 0.059 | $0.010 | 3.41s |
| FocusParse +4 headline checkpoint | 99/148 = 66.9% | 0.949 | 0.881 | $0.0232 | 3.70s |

The older `92/148 = 62.2%` FocusParse monitor reproduction remains preserved in
the run registry and protocol matrix; the headline table now uses the stronger
weekend `shape-normalizer-full-run1` checkpoint.

## Fixed Run Artifact Paths

- LlamaIndex ReAct +2:
  `/private/tmp/focusparse-exp-llamaindex-react/results/hf/related-work-fixed-full/llamaindex_react_minimal/focusparse_llamaindex_react_agentic_multi_page_0b139a04_tminimal.json`
- LlamaIndex ReAct +4:
  `/private/tmp/focusparse-exp-llamaindex-react/results/hf/related-work-fixed-full/llamaindex_react_full/focusparse_llamaindex_react_agentic_multi_page_0b139a04.json`
- Coding Agent +4:
  `/private/tmp/focusparse-exp-coding-agent/results/hf/related-work-fixed-full/coding_agent/focusparse_coding_agent_agentic_multi_page_0b139a04.json`
- DocLens-style:
  `/private/tmp/focusparse-exp-doclens-baseline/results/hf/related-work-fixed-full/doclens/focusparse_doclens_agentic_multi_page_0b139a04.json`
- AgenticOCR-style:
  `/private/tmp/focusparse-exp-agenticocr-baseline/results/hf/related-work-fixed-full/agentic_ocr/focusparse_agentic_ocr_agentic_multi_page_0b139a04.json`

Each wrapper has the corresponding `run.json` and `per_example.jsonl` under the
same run directory.

## What The Fixes Changed

The stale Coding Agent row was not a valid agentic comparator: it had
`0.7%` accuracy, `0.000` page recall, `0.000` bbox IoU, and a `1.000` lazy rate.
The root cause was action parsing and tool chaining. After fixing concatenated
JSON parsing plus page-image/layout tool adapters, Coding Agent rose to
`25.7%`, with `0.756` page recall and `0.466` IoU. This is still far below
Basic VLM and FocusParse, but it is no longer a broken harness row.

LlamaIndex ReAct +4 also improved after the tool-adapter fixes, from `6.1%` to
`10.1%`, with IoU rising from `0.125` to `0.369`. LlamaIndex ReAct +2 stayed at
`12.2%`, although page recall improved from the stale row. The remaining ReAct
weakness is therefore not just a wrapper bug: the official ReAct loop is doing
tool calls, but it still has weak document-specific answer discipline and often
narrows to partial or misleading snippets.

DocLens-style and AgenticOCR-style did not improve materially. That matters:
their poor rows are not primarily caused by the fixed JSON/tool plumbing. They
reflect proxy fidelity and task mismatch.

## Why Basic VLM Still Beats The Harnessed Rows

Basic VLM gets a broad visual bundle and answers directly. It has no evidence
trace and a `1.000` lazy rate, but it also has almost no tool-loop failure
surface: no action parser, no crop coordinate mismatch, no OCR-only snippet
bottleneck, and no adjudicator selecting a worse candidate.

The harnessed agents often lose after they have already found useful evidence.
This is visible in the fixed runs:

| Method | Fixed accuracy | Gap vs Basic | Gap vs FocusParse | Key residual failure |
|---|---:|---:|---:|---|
| LlamaIndex ReAct +2 | 12.2% | -35.1 pp | -54.7 pp | Many lazy/no-citation rows plus verbose answers |
| LlamaIndex ReAct +4 | 10.1% | -37.2 pp | -56.8 pp | Better IoU after fixes, but still poor final answers |
| Coding Agent +4 | 25.7% | -21.6 pp | -41.2 pp | Tool use recovered, but reasoning/output shape remains brittle |
| DocLens-style | 16.9% | -30.4 pp | -50.0 pp | Excellent page recall/localization, weak answer sampling/adjudication |
| AgenticOCR-style | 16.2% | -31.1 pp | -50.7 pp | Zero-shot crop policy under-explores and abstains on finance |

FocusParse is ahead because it does not treat tool use as a generic loop. It
couples page routing, evidence packet construction, crop expansion, verifier
diagnostics, and answer-shape normalization into one document-specific contract.

## Answer-Shape Counterfactual

A post-hoc diagnostic applied the existing FocusParse answer-shape normalizer to
the fixed comparator predictions before rescoring. This normalizer uses answer
type, domain, and question text, but not the gold answer. It should be treated as
a diagnostic, not a replacement headline row.

| Method | Raw fixed score | Post-hoc answer-shape score | Gain |
|---|---:|---:|---:|
| LlamaIndex ReAct +2 | 18/148 = 12.2% | 26/148 = 17.6% | +5.4 pp |
| LlamaIndex ReAct +4 | 15/148 = 10.1% | 25/148 = 16.9% | +6.8 pp |
| Coding Agent +4 | 38/148 = 25.7% | 53/148 = 35.8% | +10.1 pp |
| DocLens-style | 25/148 = 16.9% | 42/148 = 28.4% | +11.5 pp |
| AgenticOCR-style | 24/148 = 16.2% | 36/148 = 24.3% | +8.1 pp |

This is strong evidence that output contract accounts for a meaningful slice of
the gap. It is not enough to close the gap: even with the post-hoc normalizer,
the best fixed comparator is Coding Agent at `35.8%`, still below Basic VLM
at `47.3%` and far below FocusParse at `66.9%`.

## Concrete Failure Examples

- `llamaindex_react_full / fin-jpm_gtm_us_daily-0018`: gold
  `Stephanie Aliaga`; prediction contains the name but wraps it in a long
  explanation. Page recall is `1.0`; IoU is only `0.028`. This is both an
  output-shape problem and a crop precision problem.
- `llamaindex_react_full / dat-Arm_EE382N_4-0049`: gold
  `BLE; Signed integer comparison gave less than or equal`; prediction starts
  with `The branch instruction is BLE...`; page recall is `1.0`, IoU is `0.998`.
  This is a concise-answer contract failure after excellent localization.
- `coding_agent / dat-Arm_EE382N_4-0014`: gold `2`; prediction `1 outputs`;
  page recall is `1.0`, IoU is `0.994`. The agent localized the right visual
  region but miscounted the diagram.
- `coding_agent / dat-Arm_EE382N_4-0024`: gold `0x44`; prediction begins
  `r2 = 0x44...`; page recall is `1.0`, IoU is `0.726`. This is mostly answer
  shape, not localization.
- `doclens / dat-Arm_EE382N_4-0001`: gold `70%`; prediction `50%`; page recall
  is `1.0`, IoU is `0.0`. The page navigator found the page, but the element
  localizer selected a list/text region instead of the needed memory diagram.
- `doclens / dat-adrv9040-reference-manual-ug-2192-0052`: gold
  `LOGGING and MULTI-THREADING are tied at 7 functions each`; prediction says
  `LOGGING ... 6 functions`; page recall is `1.0`, IoU is `0.9996`. This is a
  downstream counting/tie-handling failure after near-perfect localization.
- `agentic_ocr / fin-jpm_gtm_us_daily-0018`: gold `Stephanie Aliaga`;
  prediction `Unanswerable`; no tool calls, page recall `0.0`, IoU `0.0`.
  This illustrates the finance abstention collapse.
- `agentic_ocr / dat-DS5091D-00-0016`: gold `Approximately 13 us`; prediction
  `Approximately 8 us`; page recall `1.0`, IoU `0.700`. The crop is relevant,
  but the zero-shot policy/reasoner misreads the chart scale.

## Paper-Facing Interpretation

The corrected claim should be:

> Generic ReAct and coding-agent loops can use tools, but without a
> document-specific evidence contract they frequently spend tool calls on
> partial crops, verbose answers, or weak adjudication. FocusParse wins because
> its harness makes evidence localization, verifier feedback, and answer shape
> first-class pipeline contracts rather than incidental outputs of a generic
> agent loop.

For the main table, use only `agentic_multi_page` rows until the 36 appendix
protocol cells are actually run. For the related-work section, label DocLens
and AgenticOCR rows as faithful proxies unless official code/model integration
is added.
