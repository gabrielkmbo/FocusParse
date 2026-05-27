# FocusParse External Source Audit

Date: 2026-05-24

Status: live-source audit for the paper draft. This file records what was
verified from external services and what still needs a final archival citation
or local Zotero export before submission.

## Source Routes Used

| Source | Route | Result |
| --- | --- | --- |
| Hugging Face | Hugging Face connector, repo details; public dataset page checks | Verified public dataset pages for `gabrielbo/parser-bench` and `llamaindex/ParseBench`. |
| GitHub | GitHub connector repo metadata; prior README fetch | Verified repo availability for `gabrielkmbo/FocusParse`, `gabrielkmbo/parse-bench`, and `run-llama/ParseBench`; use local checkout/submodule for implementation details. |
| arXiv | Browser search/open | Verified metadata for `arXiv:2604.08538`, `arXiv:2605.22100`, `arXiv:2602.24134`, and `arXiv:2511.11552`. |
| Zotero | Local Zotero helper + macOS launch check | Blocked: helper works, the local API at `127.0.0.1:23119` refuses connections, and `open -a Zotero` cannot find a Zotero app. |

## Project And Dataset Sources

### FocusParse GitHub Repository

Repository:

```text
https://github.com/gabrielkmbo/FocusParse
```

Verified from the public README on `main`:

- FocusParse is described as an agentic, budget-aware evidence-localization
  pipeline for high-resolution financial charts and technical datasheets.
- It consumes `gabrielbo/parser-bench`.
- It emits citation-grounded answers, trajectory traces, and cost/latency
  telemetry.
- The public README lists the pipeline as:

```text
PLAN -> ROUTE_PAGES -> PROPOSE_REGIONS -> INSPECT -> EXPAND_CONTEXT -> ANSWER -> VERIFY
```

Paper action:

Use the local checkout as the authoritative implementation for methods, because
it contains the current stage names and paper-draft docs. Use the GitHub
repository as a public artifact citation only after choosing a commit or archive
DOI.

Current public pin:

```text
main: 1af7f2f413a7a228deb5644ddca67888d367a8f5
```

### Gabriel Parser-Bench GitHub Repository

Repository:

```text
https://github.com/gabrielkmbo/parse-bench
```

Verified from the public README on `main`:

- Parser-bench is a citation-required visual QA benchmark over full-resolution
  financial reports and technical datasheets.
- Every question requires localization of an evidence region, reasoning over
  that region, and citation of the supporting page and bounding box.
- The generation pipeline is:

```text
preprocess -> layout detect -> evidence graph -> teacher/verifier QA -> filter -> stress variants -> export
```

- Runtime protocols include `tiled_2up`, `tiled_4up`, `tiled_8up`,
  `oracle_page`, and `oracle_crop`.

Paper action:

Use this source to support the dataset-method description, but make clear that
FocusParse evaluates a post-filter 148-row slice rather than the entire public
dataset surface.

Current public pin:

```text
main: 7685c36526b26bf3326a776c11f14354d506ebaa
```

### Gabriel Parser-Bench Hugging Face Dataset

Dataset:

```text
https://huggingface.co/datasets/gabrielbo/parser-bench
```

Verified from the Hugging Face connector and public dataset page:

| Field | Value at inspection time |
| --- | --- |
| Author | `gabrielbo` |
| Downloads | `656` from the Hugging Face connector; the public page also reports `59` downloads last month |
| Updated | `2026-05-04` |
| Revision pinned for paper package | `3774c67f8b814392b6d04c939e904f749a3f52eb` |
| Last modified from HF API | `2026-05-04 21:16:56+00:00` |
| Public viewer surface at 2026-05-24 web refresh | `default` subset, 1.54k rows: train 298, validation 574, test 666 |
| Size tag | Public page shows `1K - 10K` rows |
| Formats | `parquet`, `optimized-parquet` |
| Modalities | `image`, `text` |

Paper action:

The dataset page is citation-worthy, but it is broader than the paper's pinned
148-row materialized slice. The final dataset table should cite the public HF
dataset while reporting the exact paper materialization and revision used for
the seven-method result package.

## External ParseBench Distinction

External benchmark paper:

```text
arXiv:2604.08538
https://github.com/run-llama/ParseBench
https://huggingface.co/datasets/llamaindex/ParseBench
```

Verified from arXiv:

- Title: `ParseBench: A Document Parsing Benchmark for AI Agents`
- arXiv version: submitted 2026-04-09, last revised 2026-04-13 as v3.
- Domain: cs.CV.
- The abstract frames document parsing for agents around semantic correctness,
  including table structure, chart data, semantic formatting, and visual
  grounding.
- The benchmark covers about 2,000 human-verified enterprise pages across
  insurance, finance, and government.
- The paper reports LlamaParse Agentic as the top overall method at 84.9%.

Verified from the RunLlama GitHub README and Hugging Face card:

| Field | Value |
| --- | --- |
| Dataset | `llamaindex/ParseBench` |
| Updated | `2026-04-19` on Hugging Face |
| License | Apache-2.0 |
| Connector downloads / likes | `60.0K` / `84` |
| Top README leaderboard row | LlamaParse Agentic, overall `84.88` |
| Unique pages in README table | `2,078` |
| Capability dimensions | tables, charts, content faithfulness, semantic formatting, visual grounding |

Paper action:

Do not conflate external `ParseBench` with Gabriel's `parser-bench`.
External ParseBench evaluates parsing tools that convert PDFs into structured
outputs for agents. Gabriel's parser-bench evaluates citation-required visual QA
where a system must answer and ground the answer in supporting pages/boxes.
This distinction should remain explicit anywhere both names appear.

## Current Source Refresh

Latest connector and browser refresh on 2026-05-24:

- Hugging Face resolves `gabrielbo/parser-bench` as a public dataset by
  `gabrielbo`, updated 2026-05-04, tagged for image and text modalities, with
  the pinned paper revision still recorded in the local manifest.
- Hugging Face resolves `llamaindex/ParseBench` as an Apache-2.0 document
  parsing benchmark linked to `arXiv:2604.08538`, with tags for document,
  image, text, tables, charts, OCR, layout detection, and evaluation.
- GitHub resolves `gabrielkmbo/FocusParse` and `gabrielkmbo/parse-bench` as
  private repositories on `main`; use local files and the exact package manifest
  for code/protocol claims, not moving private-repo metadata.
- GitHub resolves `run-llama/ParseBench` as a public repository on `main`; use
  the arXiv paper and HF card for stable paper-facing claims.

## Closest Agentic Related Work

### MPDocBench-Parse

Verified from arXiv:

- `arXiv:2605.22100`, submitted 2026-05-21.
- The paper argues that existing document parsing benchmarks are often
  single-page, text-centric, or task-specific.
- It introduces 433 manually annotated multi-page documents with 3,246 pages
  across 15 English and Chinese document types.
- Its protocol evaluates content fidelity and logical structure, including
  text, tables, formulas, truncated text/table merging, figure extraction,
  reading order, and heading hierarchy.

Paper action:

Use MPDocBench-Parse as current related-work evidence that document parsing is
moving toward practical multi-page structure and semantic continuity. The
FocusParse contrast remains query-conditioned QA evidence construction:
selecting, inspecting, expanding, compacting, and citing the answer-supporting
regions rather than producing a full parsed document.

### AgenticOCR

Verified from arXiv:

- `arXiv:2602.24134`, submitted 2026-02-27.
- The paper argues that page-level chunking introduces excess context and
  dilutes salient evidence.
- It reframes OCR as query-driven, on-demand extraction over regions of
  interest.
- It describes on-demand decompression of visual tokens at the needed location.

Paper action:

Use AgenticOCR as the closest "parse only what is needed" citation. The
FocusParse contrast is evidence-packet construction: tight region plus linked
neighbor roles plus verifier-directed repair on a citation-required benchmark.

### DocLens

Verified from arXiv:

- `arXiv:2511.11552`, submitted 2025-11-14.
- The abstract identifies evidence localization as a fundamental failure mode
  for long visual document understanding.
- DocLens navigates from full documents to relevant pages and visual elements,
  then uses sampling/adjudication for answer generation.
- It reports strong results on MMLongBench-Doc and FinRAGBench-V.

Paper action:

Use DocLens as the closest long-visual-document agent comparison. The
FocusParse contrast is controlled stage boundaries and explicit packet-level
evidence representation rather than a broad multi-agent adjudication frame.

## Zotero Status

Command:

```bash
python3 /Users/gabrielbo/.codex/plugins/cache/openai-curated/zotero/6188456f/skills/zotero/scripts/zotero.py status --json
```

Result:

```text
api_running: false
api_error: <urlopen error [Errno 61] Connection refused>
connector_running: false
connector_error: <urlopen error [Errno 61] Connection refused>
base_url: http://127.0.0.1:23119
```

Desktop launch check:

```bash
open -a Zotero
```

Result:

```text
Unable to find application named 'Zotero'
```

Paper action:

The bibliography should remain primary-source based for now. Once Zotero
Desktop is installed or available on this profile with its local API enabled,
export a library-backed BibTeX file and compare it against
`docs/research/paper-draft/references.bib`.

## Submission Follow-Ups

Before submission:

1. Pin the FocusParse commit or archive DOI.
2. Pin the parser-bench HF dataset revision used for evaluation.
3. Replace moving GitHub/HF URLs in the bibliography with archival references
   where possible.
4. Re-run Zotero export once Zotero Desktop/local API is available.
5. Keep the external `ParseBench` and local `parser-bench` names visibly
   distinct in the draft, tables, and captions.
