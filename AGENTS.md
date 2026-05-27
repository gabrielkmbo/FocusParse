# AGENTS.md

Operational card for agents working in this repo. Keep this file short; put
research-facing guidance in `docs/`.

## What This Repo Does

FocusParse runs a hierarchical, budget-aware document QA workflow over
`gabrielbo/parser-bench`. The product surface is the FocusParse harness and its
reproducible experiment scripts. The benchmark submodule at
`third_party/parser-bench/` is read-only.

## Daily Commands

```bash
uv sync --extra dev
uv run focus status
uv run ruff check src/ tests/ scripts/
uv run ruff format --check src/ tests/ scripts/
uv run pytest
```

Focused checks:

```bash
uv run pytest tests/test_scoring.py::test_score_evidence_reward -v
uv run pytest tests/test_hf_eval_cli.py tests/test_workflow.py
```

Python >= 3.11. Ruff line length is 100 in `pyproject.toml`.

## Environment

Copy `.env.example` to `.env`.

Required for real evals:

- `HF_TOKEN`
- `LAYOUT_EXTRACTION_V3_MODAL_TOKEN`
- At least one provider key among `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, and
  `GEMINI_API_KEY`

Optional:

- `FOCUSPARSE_DATASET_REVISION`
- `FOCUSPARSE_LAYOUT_ENDPOINT_URL`
- `FOCUSPARSE_TIER_*`
- `FOCUSPARSE_MODEL_TIMEOUT_S`
- `FOCUSPARSE_MODEL_RETRY_ATTEMPTS`
- `FOCUSPARSE_MODEL_RETRY_SLEEP_S`
- `LLAMA_CLOUD_API_KEY`

## Reproducible Runs

Use `docs/EXPERIMENTS.md` as the public runbook. The current paper pin is:

```text
HF revision: 3774c67f8b814392b6d04c939e904f749a3f52eb
Protocol: agentic_multi_page
Smoke IDs: docs/paper/smoke-example-ids.txt
```

## Load-Bearing Contracts

- `src/focusparse/evidence/packet.py::EvidencePacket`: reasoner input is
  packeted evidence, never raw pages.
- `src/focusparse/eval/scoring.py::score_evidence_reward`: lazy-answer penalty
  is part of the research claim.
- `src/focusparse/traces/export.py::SCHEMA_VERSION`: bump on schema changes.
- `src/focusparse/tools/inspect_region.py`: exactly three modes:
  `image`, `element`, `region`.
- `third_party/parser-bench/`: read-only submodule.

## Write-Only Sinks

- `results/`
- `cache/`
- `logs/`
- `outputs/`
- `node_modules/`

These should not be committed.

## Common Failure Modes

| Symptom | Likely cause |
| --- | --- |
| Whole-page crops only | Layout endpoint stub or bad Modal token. |
| `Generated 0 candidate examples` | Dataset/schema mismatch with parser-bench. |
| Empty Gemini response | `thinking_budget` too low. |
| GPT-5.x `max_tokens` error | Use `max_completion_tokens`. |
| Multi-turn agent reports 0 tokens | Token usage propagation broke. |

## Changelog

Use `CHANGELOG.md` for public project changes. Skip trivial formatting-only
edits.
