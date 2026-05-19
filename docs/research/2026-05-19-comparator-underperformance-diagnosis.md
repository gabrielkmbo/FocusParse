# Related-Work Comparator Underperformance Diagnosis

Date: 2026-05-19

This note explains why the related-work comparator rows underperform Basic VLM
and FocusParse in the current pinned `agentic_multi_page` table, what was fixed
in the isolated method branches, and which rows are citable as implemented
comparators versus paper-inspired proxies.

## Decision-Grade Baseline State

All decision-grade rows below use HF revision
`3774c67f8b814392b6d04c939e904f749a3f52eb` and the canonical `n=148`
validation subset.

| Method | Accuracy | Cost | Cost/correct | Latency | Page recall | BBox IoU | Lazy rate | Tool calls |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Basic VLM | 70/148 = 47.3% | $0.67 | $0.010 | 3.41s | 0.895 | 0.059 | 1.000 | 0.00 |
| LlamaIndex ReAct +2 | 18/148 = 12.2% | $6.36 | $0.353 | 29.92s | 0.544 | 0.172 | 0.426 | 3.65 |
| LlamaIndex ReAct +4 | 9/148 = 6.1% | $8.25 | $0.917 | 34.37s | 0.416 | 0.125 | 0.574 | 3.81 |
| Coding Agent +4 | 1/148 = 0.7% | $2.22 | $2.223 | 7.70s | 0.000 | 0.000 | 1.000 | 0.05 |
| DocLens-style | 24/148 = 16.2% | $3.74 | $0.156 | 21.70s | 0.934 | 0.673 | 0.000 | 3.88 |
| AgenticOCR-style | 27/148 = 18.2% | $2.13 | $0.079 | 10.21s | 0.744 | 0.205 | 0.203 | 2.12 |
| FocusParse +4 | 92/148 = 62.2% | $2.18 | $0.024 | 4.10s | 0.921 | 0.894 | 0.041 | 1.00 |

The key comparison is not "tools versus no tools." Basic VLM is strong because
it directly sees the full `agentic_multi_page` image bundle and usually gives a
short answer. The weak agent rows often spend calls on tool loops but fail one of
three contracts: selecting the right source, preserving visual crop evidence, or
returning a scorer-compatible concise final answer.

## Root-Cause Breakdown

| Method | Main failure mode | Evidence |
|---|---|---|
| Basic VLM | No evidence trace; answer-only baseline, but low adapter risk. | 47.3% accuracy with zero tool calls and 100% lazy rate. It wins many rows by directly reading the summary image and emitting concise answers. |
| LlamaIndex ReAct | Official ReAct loop, but the adapter was not yet a strong multimodal document agent. | The full-tool row had only 0.416 page recall, 0.125 IoU, 57.4% lazy/no-citation rows, and $0.917/correct. The previous tool wrapper also allowed page PNG paths to be cropped with source page numbers, causing page-out-of-range failures. |
| Coding Agent | The original full run was invalid as an agentic comparator. | Tool calls averaged only 0.047/example, page recall and IoU were both 0.0, and lazy rate was 1.0. The parser often saw concatenated action JSON plus final JSON and treated the whole turn as malformed prose instead of executing the first action. |
| DocLens-style | Localization is good; answer sampling/adjudication and evidence persistence are weak. | Page recall was 0.934 and IoU was 0.673, but accuracy was only 16.2%. That means the failure is mostly downstream of evidence localization. Finance also had missing PDF/tool-source failures in the full artifacts. |
| AgenticOCR-style | This is a zero-shot proxy, not the trained AgenticOCR policy. | Accuracy was 18.2%, IoU only 0.205, and finance collapsed to 4.3%. The implementation lacks the trained crop policy, hard-negative training, GRPO reward, semantic `text/table/equation` modes, and reliable PDF hydration used by the paper setup. |
| FocusParse | Best balance of localization and final-answer discipline. | It combines high page recall (0.921), much higher IoU (0.894), low lazy rate (0.041), and concise answer normalization. |

## Why Basic VLM Beats The Harnessed Comparators

Basic VLM is not "more agentic"; it is less exposed to tool-loop failure. On
this protocol it receives the contact-sheet/full-page visual context in one shot,
then answers directly. That avoids:

- action parser failures,
- page-image versus PDF page-number mismatches,
- OCR/crop summaries that lose visual details,
- final answers that include the right value but wrap it in scorer-hostile prose,
- adjudicator mistakes where one sample is correct but another is chosen.

This also explains the apparent contradiction in the table: Basic VLM has poor
evidence metrics but decent answer accuracy. It can answer without citations.
The harnessed comparators are judged by the same final answer scorer while also
being vulnerable to tool orchestration and citation contracts.

## Concrete Examples

- `dat-Arm_EE382N_4-0024`, gold `0x44`: Basic VLM returns the exact byte. The
  agent rows often inspect the correct page/region but answer with explanatory
  prose about little-endian memory, e.g. "after STR r0..." instead of the concise
  `0x44`. This is a final-answer contract miss after localization.
- `dat-adrv9040-reference-manual-ug-2192-0030`, gold `16`: DocLens-style
  produces prose containing the correct value, but the first numeric token in the
  answer is an unrelated `4`, so numeric scoring fails. This is an output-shape
  and scoring-contract trap, not a pure visual failure.
- `fin-jpm_gtm_us_daily-0018`, gold `Stephanie Aliaga`: the DocLens-style run had
  a sample containing the correct name, but the adjudicator selected a different
  candidate. This shows the paper's sampling-adjudication idea is relevant, but
  the current proxy needs stronger answer selection and more samples.
- Finance AgenticOCR failures such as `fin-bis_qr_2025_mar-0040` and
  `fin-boe_fsr_2024_nov-0056` were often `Unanswerable` because the proxy did
  not receive a usable source PDF. Those rows should not be interpreted as the
  trained AgenticOCR method failing.

## Fixes Applied In Worker Branches

`codex/exp-coding-agent`:

- Fixed ReAct-style JSON parsing to execute the first actionable JSON object
  when the model emits action JSON followed by speculative final-answer JSON.
- Added tests covering concatenated JSON and thought-only JSON before action.
- Let comparator tools crop rendered page images even when the model keeps the
  original source page number.
- Made `layout_detect` summaries include normalized bboxes so agents can chain
  layout output into `inspect_region`.

`codex/exp-llamaindex-react`:

- Kept the official LlamaIndex ReAct integration as the citable ReAct row.
- Applied the same page-image normalization and layout summary improvements.
- Added branch-local tests for chainable layout summaries and page-image tool
  input normalization.

`codex/exp-doclens-baseline`:

- Hardened JSON extraction so concatenated JSON no longer collapses to an empty
  parse.
- Added tests for concatenated JSON and text-prefix JSON responses.

`codex/exp-agenticocr-baseline`:

- Hardened policy parsing the same way as the coding agent.
- Added tests for concatenated action/final JSON and thought-only JSON before
  action.

## Smoke Verification After Fixes

These are `--limit 5` diagnostics only; they are not replacements for the
decision-grade `n=148` rows.

| Branch smoke | Accuracy | Cost/correct | Latency | Page recall | BBox IoU | Notes |
|---|---:|---:|---:|---:|---:|---|
| LlamaIndex ReAct +4, page-image/layout fix | 2/5 = 40% | $0.110 | 39.96s | 0.800 | 0.315 | Tool adapter fix makes the row plausible again on the first slice, but it is still slow and needs full rerun. |
| Coding Agent +4, parser/page-image/layout fix | 1/5 = 20% | $0.178 | 34.45s | 0.800 | 0.665 | Tool execution/localization recovered from the invalid 0-IoU full run, but final answers remain verbose or wrong. |
| DocLens-style, JSON parser fix | 3/5 = 60% | $0.040 | 21.63s | 1.000 | 0.799 | Confirms localization was not the main blocker on this slice. |
| AgenticOCR-style, JSON parser fix without PDFs | 0/5 = 0% | n/a | 0.00s | 0.000 | 0.000 | Reproduces missing-source abstention path. |
| AgenticOCR-style, JSON parser fix with PDFs | 2/5 = 40% | $0.026 | 9.42s | 0.900 | 0.126 | Source hydration matters; remaining weakness is crop precision and answer shape. |

## Citable Comparator Decision

- **ReAct**: use **LlamaIndex ReAct** as the main ReAct comparator. It is
  citable as an industry-standard implementation of the ReAct pattern, but the
  fixed branch must be rerun at `n=148` before replacing the current poor full
  row.
- **Coding Agent**: label as a Gemini-agentic-vision-style coding-loop proxy,
  not official Gemini Agentic Vision. The tool set is reasonable for comparison
  (`inspect_region`, `get_text_layer`, `layout_detect`, `run_python`), but the
  row is not decision-grade until the fixed parser branch gets a full rerun.
- **DocLens**: label current row as **DocLens-style proxy**. It mirrors page
  navigation, element localization, answer sampling, and adjudication, but it is
  not an official reproduction and currently uses fewer samples plus weaker
  evidence persistence than the paper.
- **AgenticOCR**: label current row as **AgenticOCR-style zero-shot proxy**. It
  should not be presented as the paper method because the paper's trained policy
  and reward shaping are load-bearing parts of the result.

## Thesis Implication

The current evidence strengthens the FocusParse thesis, but the wording must be
careful:

> FocusParse outperforms generic ReAct/coding loops and faithful-lite
> related-work proxies because it turns tool use into a constrained
> evidence-localization contract: high page recall, high crop IoU, low lazy rate,
> and concise answer normalization. The generic agents are not weak because tools
> are useless; they are weak because generic tool loops do not preserve the
> document-specific evidence contract without additional architecture or training.

For the paper table, keep the current pinned full rows as reproducible results,
but annotate the weak comparator rows as "pre-fix full run" until the fixed
branches complete `n=148` reruns. For the related-work section, cite LlamaIndex
ReAct as the main ReAct implementation and explicitly label DocLens/AgenticOCR
as proxies unless official code/model integration becomes available.

## External Sources To Cite

- LlamaIndex ReAct workflow docs:
  `https://docs.llamaindex.ai/en/stable/examples/workflow/react_agent/`
- ReAct paper:
  `https://arxiv.org/abs/2210.03629`
- DocLens paper:
  `https://arxiv.org/abs/2511.11552`
- AgenticOCR paper:
  `https://arxiv.org/abs/2602.24134`

