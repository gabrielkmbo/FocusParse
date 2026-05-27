# Reproducibility Checklist

Use this checklist before publishing or comparing a FocusParse result.

## Inputs

- Parser-bench submodule initialized with `git submodule update --init --recursive`.
- HF dataset revision pinned:
  `3774c67f8b814392b6d04c939e904f749a3f52eb`.
- Smoke IDs read from `docs/paper/smoke-example-ids.txt`.
- Model tiers read from `configs/default.yaml`.
- Environment variables copied from `.env.example`.

## Local Verification

```bash
uv run focus status --short
uv run ruff check src/ tests/ scripts/
uv run ruff format --check src/ tests/ scripts/
uv run pytest
```

## Experiment Verification

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

Run the full seven-method table with `scripts/run_headline_eval.py` as described
in `docs/EXPERIMENTS.md`.

## Artifact Rules

- Commit source, tests, configs, docs, and small manifests.
- Do not commit raw `results/`, caches, source PDFs, crops, local credentials,
  or provider logs.
- Record any new headline claim in `docs/PAPER.md` and keep the command in
  `docs/EXPERIMENTS.md` reproducible.
