# Reproducible Experiments

This is the public runbook for the FocusParse paper table.

## Install

```bash
git submodule update --init --recursive
uv sync --extra dev
cp .env.example .env
```

Fill `.env` with:

```text
HF_TOKEN
LAYOUT_EXTRACTION_V3_MODAL_TOKEN
OPENAI_API_KEY or ANTHROPIC_API_KEY or GEMINI_API_KEY
```

## Pinned Inputs

```text
HF dataset: gabrielbo/parser-bench
HF revision: 3774c67f8b814392b6d04c939e904f749a3f52eb
Protocol: agentic_multi_page
Canonical rows: 148
Smoke IDs: docs/paper/smoke-example-ids.txt
```

Outputs are written under `results/` and are not committed.

## Smoke

```bash
uv run python scripts/run_hf_eval.py \
  --agent focus \
  --protocol agentic_multi_page \
  --tool-set full \
  --hf-revision 3774c67f8b814392b6d04c939e904f749a3f52eb \
  --example-ids-file docs/paper/smoke-example-ids.txt \
  --output-dir results/hf/smoke-focus-full \
  --no-resume
```

## Headline Table

```bash
uv run python scripts/run_headline_eval.py \
  --hf-revision 3774c67f8b814392b6d04c939e904f749a3f52eb \
  --output-dir results/hf/headline \
  --max-parallel 2
```

This runs:

- Base VLM
- ReAct +2 tools
- ReAct +4 tools
- Agent baseline +2 tools
- Agent baseline +4 tools
- FocusParse +2 tools
- FocusParse +4 tools

Render the table:

```bash
uv run python scripts/render_headline_table.py \
  results/hf/headline/headline_table.json \
  --output-md results/hf/headline/headline_table.md \
  --output-html results/hf/headline/headline_table.html
```

## Mechanism Ablations

FocusParse ablation switches live on `scripts/run_hf_eval.py`:

```bash
--disable-rerank
--disable-expand-context
--disable-answer-shape-repair
--max-retries 0
```

Run each into its own `results/` directory and compare paired rows with the
analysis scripts in `scripts/README.md`.

## Verification

Use these before publishing a result:

```bash
uv run ruff check src/ tests/ scripts/
uv run ruff format --check src/ tests/ scripts/
uv run pytest
```

For a faster harness-focused pass:

```bash
uv run pytest tests/test_hf_eval_cli.py tests/test_workflow.py tests/test_scoring.py
```
