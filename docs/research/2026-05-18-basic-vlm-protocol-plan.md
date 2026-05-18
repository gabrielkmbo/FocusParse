# Basic VLM Protocol Sweep Plan

Date: 2026-05-18
Branch: `codex/exp-basic-vlm-protocols`
Worktree: `/private/tmp/focusparse-exp-basic-vlm-protocols`

## Purpose

This branch makes the related-work protocol sweep reproducible and
monitor-ingestable without changing model or pipeline behavior. The execution
primitive remains `scripts/run_hf_eval.py`; the new wrapper only defines exact
commands and writes a run registry.

## Pinned Dataset

All registry entries pin `gabrielbo/parser-bench` validation to:

`3774c67f8b814392b6d04c939e904f749a3f52eb`

That keeps the Basic VLM protocol sweep aligned with the canonical FocusParse
148-row validation subset produced by the HF materializer.

## Registry Generator

Generate the manifest and JSONL registry without model calls:

```bash
uv run python scripts/run_related_work_protocols.py \
  --output-dir results/hf/related-work-protocols \
  --print-commands
```

Outputs:

- `results/hf/related-work-protocols/related_work_protocol_manifest.json`
- `results/hf/related-work-protocols/related_work_protocol_registry.jsonl`

Each run entry includes:

- `method_label`
- `agent`
- `protocol`
- `tool_set`
- exact `command`
- per-run `output_dir`
- `expected_config_key`
- artifact-derived `status`

Status is `pending`, `partial`, or `complete` based on the standard
FocusParse artifacts:

- `<output_root>/<expected_config_key>.json`
- `<output_root>/<expected_config_key>/run.json`
- `<output_root>/<expected_config_key>/per_example.jsonl`

## Basic VLM Protocol Commands

The Basic VLM sweep emits seven `simple` rows:

`tool_set=full` is included in the command and manifest because
`run_hf_eval.py` uses that default to keep the historical config-key shape. The
`simple` agent still uses no tools.

```bash
uv run python scripts/run_hf_eval.py --agent simple --protocol full_doc --tool-set full --hf-repo gabrielbo/parser-bench --hf-split validation --hf-revision 3774c67f8b814392b6d04c939e904f749a3f52eb --output-dir results/hf/related-work-protocols --staging-dir ~/.cache/focusparse/hf_staging --resume
uv run python scripts/run_hf_eval.py --agent simple --protocol oracle_page --tool-set full --hf-repo gabrielbo/parser-bench --hf-split validation --hf-revision 3774c67f8b814392b6d04c939e904f749a3f52eb --output-dir results/hf/related-work-protocols --staging-dir ~/.cache/focusparse/hf_staging --resume
uv run python scripts/run_hf_eval.py --agent simple --protocol oracle_crop --tool-set full --hf-repo gabrielbo/parser-bench --hf-split validation --hf-revision 3774c67f8b814392b6d04c939e904f749a3f52eb --output-dir results/hf/related-work-protocols --staging-dir ~/.cache/focusparse/hf_staging --resume
uv run python scripts/run_hf_eval.py --agent simple --protocol tiled_2up --tool-set full --hf-repo gabrielbo/parser-bench --hf-split validation --hf-revision 3774c67f8b814392b6d04c939e904f749a3f52eb --output-dir results/hf/related-work-protocols --staging-dir ~/.cache/focusparse/hf_staging --resume
uv run python scripts/run_hf_eval.py --agent simple --protocol tiled_4up --tool-set full --hf-repo gabrielbo/parser-bench --hf-split validation --hf-revision 3774c67f8b814392b6d04c939e904f749a3f52eb --output-dir results/hf/related-work-protocols --staging-dir ~/.cache/focusparse/hf_staging --resume
uv run python scripts/run_hf_eval.py --agent simple --protocol tiled_8up --tool-set full --hf-repo gabrielbo/parser-bench --hf-split validation --hf-revision 3774c67f8b814392b6d04c939e904f749a3f52eb --output-dir results/hf/related-work-protocols --staging-dir ~/.cache/focusparse/hf_staging --resume
uv run python scripts/run_hf_eval.py --agent simple --protocol agentic_multi_page --tool-set full --hf-repo gabrielbo/parser-bench --hf-split validation --hf-revision 3774c67f8b814392b6d04c939e904f749a3f52eb --output-dir results/hf/related-work-protocols --staging-dir ~/.cache/focusparse/hf_staging --resume
```

The generator prints the same commands with the absolute default staging path
for this machine.

## Appendix Comparator Commands

The appendix comparator registry emits four `agentic_multi_page` rows:

- ReAct +2 tools: `agent=react`, `tool_set=minimal`
- ReAct +4 tools: `agent=react`, `tool_set=full`
- Agent baseline +2 tools: `agent=agent_baseline`, `tool_set=minimal`
- Agent baseline +4 tools: `agent=agent_baseline`, `tool_set=full`

Filter to only these rows:

```bash
uv run python scripts/run_related_work_protocols.py \
  --suite appendix-comparators \
  --output-dir results/hf/related-work-appendix-comparators \
  --print-commands
```

## Smoke And Full Runs

A cheap smoke should use a separate output directory so limit runs do not share
the full-sweep cache namespace:

```bash
uv run python scripts/run_related_work_protocols.py \
  --suite basic-vlm \
  --protocol full_doc \
  --limit 1 \
  --output-dir results/hf/related-work-protocols-smoke \
  --run
```

Full sweeps are intentionally guarded:

```bash
uv run python scripts/run_related_work_protocols.py \
  --suite basic-vlm \
  --output-dir results/hf/related-work-protocols \
  --allow-full-sweep \
  --run
```

The script refuses `--run` without `--limit` unless `--allow-full-sweep` is
present. It also checks `HF_TOKEN` and the resolved reasoner provider key before
live execution unless `--skip-env-check` is passed.
