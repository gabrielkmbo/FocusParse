# Related-Work Experiment Monitor

Generated: 2026-05-19T20:02:46.905006+00:00

## Thesis Target

FocusParse should be compared against a trusted LlamaIndex ReAct agent, a coding-agent loop, DocLens-style hierarchical evidence extraction, AgenticOCR-style on-demand crop/OCR, and a no-tool VLM. The main claim is architecture plus evidence localization, not just tool availability.

## Status Counts

- `implemented`: 36
- `verified`: 7

## Headline Rows

- **Basic VLM**: `verified` (simple, `full`, `agentic_multi_page`)
- **LlamaIndex ReAct +2**: `verified` (llamaindex_react, `minimal`, `agentic_multi_page`)
- **LlamaIndex ReAct +4**: `verified` (llamaindex_react, `full`, `agentic_multi_page`)
- **Coding Agent +4**: `verified` (coding_agent, `full`, `agentic_multi_page`)
- **DocLens-style**: `verified` (doclens, `full`, `agentic_multi_page`)
- **AgenticOCR-style**: `verified` (agentic_ocr, `full`, `agentic_multi_page`)
- **FocusParse +4**: `verified` (focus, `full`, `agentic_multi_page`)

## Gates

- Decision-grade rows must use `3774c67f8b814392b6d04c939e904f749a3f52eb` and `n=148`.
- FocusParse headline row uses the 99/148 = 66.9% `shape-normalizer-full-run1 weekend Gemini-key checkpoint`; provenance note is linked at `docs/research/2026-05-15-harness-65plus-post-evidence-iteration.md`. The older 92/148 = 62.2% monitor reproduction remains preserved in the run registry/protocol matrix.
- Canonical rows currently contain `148` rows and `147` unique example IDs because `dat-DS5091D-00-0016` appears twice in the pinned slice.
- Results under `results/` are gitignored; tracked files should contain commands, manifests, and analysis.
