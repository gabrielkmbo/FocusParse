# Related-Work Experiment Branch

This branch is the reproducibility and presentation branch for the
FocusParse related-work sweep. It is intentionally not merged into `main`.
It exists so reviewers can inspect the thesis table, see the exact commands,
and rerun the comparator methods in isolated worktrees.

## Start Here

Read these in order:

1. `docs/research/2026-05-18-related-work-headline-results.md` — paper-facing
   table and thesis.
2. `docs/research/2026-05-19-comparator-underperformance-diagnosis.md` —
   why the generic agent/tool baselines lag the no-tool VLM and FocusParse.
3. `docs/research/2026-05-19-fixed-comparator-rerun-and-protocol-status.md` —
   what was rerun, what is decision-grade, and what remains appendix-only.
4. `docs/research/related-work-monitor/headline_table.md` — tracked snapshot
   of the generated machine table.

Raw run outputs stay under `results/`, which is gitignored. The small generated
snapshots under `docs/research/related-work-monitor/` are committed so GitHub
viewers can inspect the result table without rerunning expensive model calls.

## Headline Result

All rows use `gabrielbo/parser-bench` validation revision
`3774c67f8b814392b6d04c939e904f749a3f52eb` and the canonical FocusParse
post-filter slice of 148 rows.

| Method | Overall accuracy | Overall latency | Cost/correct |
| --- | ---: | ---: | ---: |
| Basic VLM | 47.3% | 3.41s | $0.0096 |
| LlamaIndex ReAct +2 | 12.2% | 29.65s | $0.3542 |
| LlamaIndex ReAct +4 | 10.1% | 30.13s | $0.5195 |
| Coding Agent +4 | 25.7% | 18.17s | $0.1425 |
| DocLens-style | 16.9% | 19.14s | $0.1516 |
| AgenticOCR-style | 16.2% | 8.30s | $0.0778 |
| FocusParse +4 | 66.9% | 3.70s | $0.0232 |

FocusParse's headline row is the weekend `shape-normalizer-full-run1`
checkpoint: `99/148 = 66.9%`, datasheet `71/101`, finance `28/47`,
cost/correct `$0.0232`, mean latency `3.70s`, page recall `0.949`,
bbox IoU `0.881`, and lazy-answer rate `0.020`.

The monitor also preserves the older current-branch reproduction:
`92/148 = 62.2%`. Keep those rows separate when writing up provenance.

## Branch Layout

The comparator implementations are intentionally split across branches so each
method can be worked on independently:

| Branch | Purpose |
| --- | --- |
| `codex/exp-related-work-monitor` | this coordination branch: manifests, tables, analysis, reproducibility docs |
| `codex/exp-basic-vlm-protocols` | no-tool VLM and appendix protocol matrix |
| `codex/exp-llamaindex-react` | official LlamaIndex ReAct +2/+4 comparator |
| `codex/exp-coding-agent` | Gemini-Agentic-Vision-style coding loop |
| `codex/exp-doclens-baseline` | DocLens-style page navigator/localizer/sampler/adjudicator proxy |
| `codex/exp-agenticocr-baseline` | AgenticOCR-style on-demand zoom/OCR proxy |

This branch does not vendor the worker branches. To rerun everything exactly,
check out the monitor plus the worker worktrees.

## Environment

Use Python 3.11+ and install the repo with:

```bash
uv sync --extra dev
```

Copy `.env.example` to `.env` and fill the model/data keys used by the evals:

```bash
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
GEMINI_API_KEY=...  # or GOOGLE_API_KEY
HF_TOKEN=...
LAYOUT_EXTRACTION_V3_MODAL_TOKEN=...
```

Full reruns are paid API experiments. Start with `--limit 5` smokes before
running a decision-grade row.

## Recreate Worktrees

From a clean clone, fetch the experiment branches and place them at the paths
expected by `scripts/related_work_monitor.py`:

```bash
git fetch origin
git worktree add /private/tmp/focusparse-exp-related-work-monitor origin/codex/exp-related-work-monitor
git worktree add /private/tmp/focusparse-exp-basic-vlm-protocols origin/codex/exp-basic-vlm-protocols
git worktree add /private/tmp/focusparse-exp-llamaindex-react origin/codex/exp-llamaindex-react
git worktree add /private/tmp/focusparse-exp-coding-agent origin/codex/exp-coding-agent
git worktree add /private/tmp/focusparse-exp-doclens-baseline origin/codex/exp-doclens-baseline
git worktree add /private/tmp/focusparse-exp-agenticocr-baseline origin/codex/exp-agenticocr-baseline
```

If you use different paths, pass `--result-root` to the monitor or adjust the
`WORKTREES` map in `scripts/related_work_monitor.py` for your local run.

## Rerun The Monitor

After worker runs finish, regenerate the gitignored live artifacts and the
tracked GitHub snapshot:

```bash
cd /private/tmp/focusparse-exp-related-work-monitor
uv run python scripts/related_work_monitor.py \
  --render \
  --snapshot-dir docs/research/related-work-monitor
```

This writes:

- `results/hf/related-work-monitor/run_registry.json`
- `results/hf/related-work-monitor/dataset_manifest.json`
- `results/hf/related-work-monitor/protocol_matrix.json`
- `results/hf/related-work-monitor/headline_table.{json,md,csv,html,jsonl}`
- `results/hf/related-work-monitor/related_work_thesis_note.md`
- matching tracked copies under `docs/research/related-work-monitor/`

## Rerun A Method

The monitor's `run_registry.json` is the source of truth for exact commands.
The common pattern is:

```bash
uv run python scripts/run_hf_eval.py \
  --agent <method-agent> \
  --protocol agentic_multi_page \
  --tool-set full \
  --hf-revision 3774c67f8b814392b6d04c939e904f749a3f52eb \
  --staging-dir ~/.cache/focusparse/hf_staging_related_work_full_<method> \
  --pdfs-root ~/.cache/focusparse/pdfs \
  --output-dir results/hf/related-work/<method> \
  --minimal-artifacts
```

For smokes, add `--limit 5` and write to a scratch output directory. Do not use
a smoke output as a thesis row.

## Verification

Before pushing this branch, run:

```bash
uv run python scripts/related_work_monitor.py --render --snapshot-dir docs/research/related-work-monitor
uv run pytest tests/test_related_work_monitor.py tests/test_render_headline_table.py tests/test_hf_eval_cli.py
uv run ruff check scripts/related_work_monitor.py scripts/render_headline_table.py scripts/run_hf_eval.py src/focusparse/eval/harness.py tests/test_related_work_monitor.py
```

The pinned canonical slice currently has 148 rows and 147 unique example IDs
because `dat-DS5091D-00-0016` appears twice. The monitor treats that as
expected and records the duplicate explicitly in the dataset manifest.
