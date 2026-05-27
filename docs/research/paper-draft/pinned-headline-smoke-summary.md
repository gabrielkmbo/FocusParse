# FocusParse Pinned Headline Smoke Summary

Date: 2026-05-24

Status: seven-method orchestration smoke for the pinned parser-bench paper
package. This verifies that the headline runner can execute and render every
method row against a pinned example-id file without shrinking the shared
148-row staging directory. It is not a benchmark result.

## Command

```bash
set -a; source .env; set +a
uv run python scripts/run_headline_eval.py \
  --output-dir results/hf/paper/2026-05-23-revision-pin/headline-smoke \
  --staging-dir /Users/gabrielbo/.cache/focusparse/paper-3774c67f8b814392b6d04c939e904f749a3f52eb \
  --pdfs-root /Users/gabrielbo/.cache/focusparse/pdfs \
  --hf-revision 3774c67f8b814392b6d04c939e904f749a3f52eb \
  --example-ids-file docs/research/paper-draft/smoke-example-ids.txt \
  --max-parallel 2 \
  --no-resume \
  --render
```

The runner now forwards `--example-ids-file` to each `run_hf_eval.py`
subprocess. This avoids the staging rewrite caused by `--limit` while still
restricting each method to the same smoke rows.

## Artifacts

```text
results/hf/paper/2026-05-23-revision-pin/headline-smoke/headline_table.json
results/hf/paper/2026-05-23-revision-pin/headline-smoke/headline_table.md
results/hf/paper/2026-05-23-revision-pin/headline-smoke/headline_table.csv
results/hf/paper/2026-05-23-revision-pin/headline-smoke/headline_table.jsonl
results/hf/paper/2026-05-23-revision-pin/headline-smoke/headline_table.html
results/hf/paper/2026-05-23-revision-pin/headline-smoke/diagnostics/headline-smoke-diagnosis.md
results/hf/paper/2026-05-23-revision-pin/headline-smoke/diagnostics/headline-smoke-diagnosis.json
```

Each of the seven method directories contains `run.json` and
`per_example.jsonl` with 3 rows.

## Smoke Rows

```text
dat-Arm_EE382N_4-0001
dat-Arm_EE382N_4-0006
dat-Arm_EE382N_4-0014
```

All three smoke rows are datasheet examples. This is enough to validate the
orchestration path, but it does not validate finance-row behavior or support a
domain-balanced claim.

## Headline Smoke Table

| Method | n | Accuracy | Cost/correct | Mean latency |
| --- | ---: | ---: | ---: | ---: |
| Base VLM | 3 | 66.7% | `$0.0052` | 2.66s |
| ReAct +2 tools | 3 | 33.3% | `$0.0488` | 9.01s |
| ReAct +4 tools | 3 | 0.0% | n/a | 15.88s |
| Agent baseline +2 tools | 3 | 33.3% | `$0.0226` | 3.20s |
| Agent baseline +4 tools | 3 | 0.0% | n/a | 2.89s |
| Our harness +2 tools | 3 | 66.7% | `$0.0117` | 1.76s |
| Our harness +4 tools | 3 | 66.7% | `$0.0153` | 2.06s |

The merged `headline_table.json` has 7 rows matching the 7 configured specs,
tier SHA `0b139a04`, and `example_ids_file` set to
`docs/research/paper-draft/smoke-example-ids.txt`.

## Diagnostics Snapshot

The diagnostic report analyzed all 7 specs.

Notable smoke-only observations:

- Agent baseline +4 had `lazy_answer_rate = 100%` and `empty_cite_rate = 100%`.
- Agent baseline +2 had `lazy_answer_rate = 100%` and `empty_cite_rate = 100%`.
- ReAct +4 had `lazy_answer_rate = 66.7%` and one loop exhaustion fallback.
- FocusParse +4 had `lazy_answer_rate = 0%`, `expand_context called = 100%`,
  and 24 evidence packets across the three examples.
- FocusParse +2 also had `lazy_answer_rate = 0%`, but context coverage was 0%
  because the minimal tool set excludes `expand_context`.

These observations are useful for mechanism debugging, but the sample is too
small and too datasheet-heavy to cite as a result.

## Validation

Post-run checks:

```text
148 /Users/gabrielbo/.cache/focusparse/paper-3774c67f8b814392b6d04c939e904f749a3f52eb/benchmark.jsonl
3 rows in every method per_example.jsonl
7 rows in headline_table.json
7 configured specs represented
```

## Paper Use

Use this file as readiness evidence for the full headline sweep:

- all seven method wrappers execute under one pinned HF revision;
- the full staged benchmark remains intact at 148 rows;
- `headline_table.{json,md,csv,jsonl,html}` rendering works;
- diagnostics can be generated from the result directory.

Do not cite the smoke table as the final paper result.
