# Contributing

FocusParse is a research repo first: changes should make the benchmark harness
clearer, easier to reproduce, or easier to inspect.

## Development Setup

```bash
git submodule update --init --recursive
uv sync --extra dev
uv run focus status --short
```

Real evaluations also need the environment variables described in
`.env.example`.

## Before Opening A PR

Run the same checks as CI:

```bash
uv run focus status --short
uv run ruff check src/ tests/ scripts/
uv run ruff format --check src/ tests/ scripts/
uv run pytest
```

For experiment changes, also update the relevant runbook or summary under
`docs/`, and keep raw run outputs under `results/`.

## Repo Boundaries

- Do not commit `.env`, `results/`, `cache/`, or generated page/crop assets.
- Do not modify `third_party/parser-bench/` from this repo.
- Keep new scripts documented in `scripts/README.md`.
- Keep public claims in `docs/PAPER.md` tied to reproducible commands in
  `docs/EXPERIMENTS.md`.
