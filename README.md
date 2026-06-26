# FocusParse

FocusParse is a research harness for high-resolution document QA. It runs a
budget-aware, evidence-localization-first workflow over
[`parser-bench`](https://huggingface.co/datasets/gabrielbo/parser-bench) and
records answers, citations, traces, cost, latency, and grounding metrics.

The core claim is simple: on dense finance and datasheet documents, a staged
evidence harness beats a base VLM and generic tool-agent baselines under the
same benchmark protocol.

## Quickstart

```bash
git clone https://github.com/run-llama/focusparse.git FocusParse
cd FocusParse
git submodule update --init --recursive
uv sync --extra dev
cp .env.example .env
```

Fill `.env` with the keys needed for the path you plan to run. Local status,
lint, and unit tests do not require provider credentials. HF-backed evaluations
need `HF_TOKEN`, and FocusParse layout detection needs
`LAYOUT_EXTRACTION_V3_MODAL_TOKEN`.

Run local checks:

```bash
uv run focus status
uv run ruff check src/ tests/ scripts/
uv run ruff format --check src/ tests/ scripts/
uv run pytest
```

Run a small HF smoke:

```bash
uv run python scripts/run_hf_eval.py \
  --agent focus \
  --protocol agentic_multi_page \
  --tool-set full \
  --hf-revision 3774c67f8b814392b6d04c939e904f749a3f52eb \
  --example-ids-file docs/paper/smoke-example-ids.txt \
  --limit 3
```

Run the seven-method paper table:

```bash
uv run python scripts/run_headline_eval.py \
  --hf-revision 3774c67f8b814392b6d04c939e904f749a3f52eb \
  --max-parallel 2
```

Outputs go under `results/`, which is intentionally gitignored. Keep provider
logs, source PDFs, page images, crops, and trace payloads out of commits unless
a release checklist explicitly says otherwise.

## What To Read

| File | Purpose |
| --- | --- |
| `docs/EXPERIMENTS.md` | Reproducible setup, smoke, and full-run commands. |
| `docs/REPRODUCIBILITY.md` | Publication checklist for inputs, commands, and artifacts. |
| `docs/PAPER.md` | Current paper claim, result table, and caveats. |
| `docs/BRANCH_AUDIT.md` | What was checked from hanging branches before cleanup. |
| `scripts/README.md` | Script map for eval, reporting, diagnostics, and demos. |
| `configs/default.yaml` | Model tiers, dataset pin, endpoint settings, and budgets. |
| `CITATION.cff` | Citation metadata for research use. |

## Repo Map

| Path | Role |
| --- | --- |
| `src/focusparse/pipeline/` | Focus workflow stages and comparator agents. |
| `src/focusparse/tools/` | Small tool primitives: inspect, text layer, layout, chart, code zoom. |
| `src/focusparse/eval/` | Harness, metrics, scoring, table rendering support. |
| `src/focusparse/traces/` | Trajectory recording, export, and static viewers. |
| `scripts/` | Reproducible experiment and analysis entrypoints. |
| `tests/` | Unit and integration tests for harness contracts. |
| `third_party/parser-bench/` | Read-only benchmark submodule. |

## Result Snapshot

The current raw-verified matched paper run is the May 24 seven-method table on
148 parser-bench rows. FocusParse +4 reaches 61.5% overall accuracy, 66.3% on
datasheets, 51.1% on finance, and $0.0248 per correct answer. See
`docs/PAPER.md` for the table and caveats.

## License

Apache-2.0. See `LICENSE`.
