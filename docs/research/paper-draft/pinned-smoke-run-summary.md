# FocusParse Pinned Smoke Run Summary

Date: 2026-05-23

Status: 3-row smoke result for the pinned parser-bench paper package. This
checks that the layout endpoint, model credentials, source-PDF cache, and
FocusParse +4 harness path can run end to end. It is not a paper accuracy
claim.

## Smoke Result

| Field | Value |
| --- | ---: |
| HF revision | `3774c67f8b814392b6d04c939e904f749a3f52eb` |
| Agent | `focus` |
| Protocol | `agentic_multi_page` |
| Tool set | `full` |
| Tier SHA | `0b139a04` |
| Rows | 3 |
| Accuracy | 100.0% |
| Page recall mean | 0.667 |
| BBox IoU mean | 0.666 |
| Lazy-answer rate | 0.000 |
| Tool calls mean | 1.000 |
| Total cost | `$0.01872625` |
| Cost/correct | `$0.00624208` |
| Mean latency | 2.055s |

Artifacts:

```text
results/hf/paper/2026-05-23-revision-pin/smoke-focus-full/focusparse_focus_agentic_multi_page_0b139a04/run.json
results/hf/paper/2026-05-23-revision-pin/smoke-focus-full/focusparse_focus_agentic_multi_page_0b139a04/per_example.jsonl
results/hf/paper/2026-05-23-revision-pin/smoke-focus-full/focusparse_focus_agentic_multi_page_0b139a04.json
```

Example rows:

| Example ID | Correct | Page recall | BBox IoU | Cost |
| --- | ---: | ---: | ---: | ---: |
| `dat-Arm_EE382N_4-0001` | 1.0 | 1.0 | 0.9965 | `$0.00790625` |
| `dat-Arm_EE382N_4-0006` | 1.0 | 0.0 | 0.0000 | `$0.00649750` |
| `dat-Arm_EE382N_4-0014` | 1.0 | 1.0 | 1.0000 | `$0.00432250` |

Runtime notes:

- Layout endpoint preflight succeeded with 14 boxes on the first staged page.
- The run called Gemini, Anthropic, and OpenAI successfully.
- One Anthropic call timed out once and was recovered by the configured retry
  wrapper: `Retrying anthropic model call after transient TimeoutError (1/2)`.
- Environment snapshot in `run.json` shows OpenAI, Anthropic, Gemini, and HF
  tokens present.

## Staging Caveat

This smoke was run with `--limit 3`, which temporarily rewrote the shared
staging `benchmark.jsonl` down to three rows. The full pinned staging was
immediately restored after the smoke:

```text
/Users/gabrielbo/.cache/focusparse/paper-3774c67f8b814392b6d04c939e904f749a3f52eb/benchmark.jsonl
```

Post-restore validation:

```text
148 /Users/gabrielbo/.cache/focusparse/paper-3774c67f8b814392b6d04c939e904f749a3f52eb/benchmark.jsonl
```

Future smokes should use `--example-ids-file` instead of `--limit` when sharing
the final `PAPER_STAGING` root. This preserves the full 148-row materialization
while evaluating only the chosen smoke examples.

Recommended smoke IDs:

```text
dat-Arm_EE382N_4-0001
dat-Arm_EE382N_4-0006
dat-Arm_EE382N_4-0014
```

## Paper Use

Use this smoke only as readiness evidence:

- credentials are available;
- layout preflight works;
- source PDFs are usable via `--pdfs-root`;
- FocusParse +4 can write `run.json`, `per_example.jsonl`, predictions, and
  tiles under the pinned result package.

Do not cite the 100% smoke accuracy as a benchmark result.
