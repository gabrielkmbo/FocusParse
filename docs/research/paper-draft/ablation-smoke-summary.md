# FocusParse Pure-Ablation Smoke Summary

Date: 2026-05-24

Status: completed 3-row smoke checks for the pure-ablation switches. These
are not submission-strength ablation results; they verify that the harness flags
work on the pinned paper setup before the matched n=148 runs.

## Fixed Setup

All smoke runs used the same three datasheet examples:

```text
dat-Arm_EE382N_4-0001
dat-Arm_EE382N_4-0006
dat-Arm_EE382N_4-0014
```

Shared run settings:

- HF dataset revision: `3774c67f8b814392b6d04c939e904f749a3f52eb`
- staging directory:
  `/Users/gabrielbo/.cache/focusparse/paper-3774c67f8b814392b6d04c939e904f749a3f52eb`
- PDF root: `/Users/gabrielbo/.cache/focusparse/pdfs`
- agent/protocol/tool set: `focus`, `agentic_multi_page`, `full`
- artifact mode: `--minimal-artifacts`

The layout endpoint preflight passed for every run, and the HF loader reused the
local 148-row staging snapshot.

## Smoke Results

| Condition | Source | n | Accuracy | Page recall | BBox IoU | Evidence reward | Cost | Main observed flip |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Full FocusParse +4, smoke subset from final n=148 run | `results/hf/paper/2026-05-24-paper-headline-v1/headline/focusparse_focus_agentic_multi_page_0b139a04/` | 3 | 100.0% | 0.667 | 0.666 | 0.666 | `$0.024970` | All three were harness-scored correct after verifier-directed retries. |
| No expand context | `results/hf/paper/ablation-smoke-no-expand-v1/focusparse_focus_agentic_multi_page_0b139a04/` | 3 | 66.7% | 1.000 | 0.814 | 0.481 | `$0.017416` | `dat-Arm_EE382N_4-0014` regressed from `2 outputs` to `1 outputs`. |
| No rerank | `results/hf/paper/ablation-smoke-no-rerank-v1/focusparse_focus_agentic_multi_page_0b139a04/` | 3 | 66.7% | 1.000 | 0.814 | 0.667 | `$0.018449` | `dat-Arm_EE382N_4-0001` regressed from a tolerated `60%` answer to `50%`. |
| Retry off | `results/hf/paper/ablation-smoke-retry-off-v1/focusparse_focus_agentic_multi_page_0b139a04/` | 3 | 66.7% | 1.000 | 0.814 | 0.667 | `$0.027659` | `dat-Arm_EE382N_4-0001` regressed from a tolerated `60%` answer to `50%`. |
| Answer-shape repair off | `results/hf/paper/ablation-smoke-answer-shape-off-v1/focusparse_focus_agentic_multi_page_0b139a04/` | 3 | 100.0% | 1.000 | 0.814 | 0.814 | `$0.025040` | No answer flip on the smoke slice; feature bit and minimal-artifact policy verified. |

The `dat-Arm_EE382N_4-0001` row is a scorer-sensitive example: the final full
run predicted `60%` against gold text containing `70%`, yet the current harness
scored it correct. Treat that row as useful for flag smoke-testing and trace
inspection, not as a standalone semantic win.

## Per-Example Outcomes

| Example | Full +4 subset | No expand | No rerank | Retry off | Answer-shape off |
| --- | --- | --- | --- | --- | --- |
| `dat-Arm_EE382N_4-0001` | correct, `60%` | correct, `60%` | wrong, `50%` | wrong, `50%` | correct, `60%` |
| `dat-Arm_EE382N_4-0006` | correct, `0.9` | correct, `1.0` | correct, `1.0` | correct, `1.0` | correct, `1.0` |
| `dat-Arm_EE382N_4-0014` | correct, `2 outputs` | wrong, `1 outputs` | correct, `2 outputs` | correct, `2 outputs` | correct, `2 outputs` |

## Interpretation For The Paper

The smoke set supports spending budget on the full n=148 mechanism ablations:

- `--disable-expand-context` is wired correctly and can change final answers
  while preserving the rest of the full tool belt.
- `--disable-rerank` is wired correctly and can change final answers even when
  page recall remains perfect on the smoke slice.
- `--max-retries 0 --max-evidence-retries 0` is wired correctly and removes the
  verifier-directed retry/repair behavior.
- `--disable-answer-shape-repair` is wired correctly and removes
  answer-shape-specific retry hints while preserving non-shape verifier repair.

It does not prove the mechanism claim by itself. The workshop-safe claim now
uses the coarse +2 versus +4 result, failure taxonomy, and the completed matched
n=148 mechanism ablations with paired recoveries and regressions against the
final full +4 run.

## Commands Used

No expand:

```bash
uv run python scripts/run_hf_eval.py \
  --agent focus \
  --protocol agentic_multi_page \
  --tool-set full \
  --hf-revision 3774c67f8b814392b6d04c939e904f749a3f52eb \
  --staging-dir /Users/gabrielbo/.cache/focusparse/paper-3774c67f8b814392b6d04c939e904f749a3f52eb \
  --pdfs-root /Users/gabrielbo/.cache/focusparse/pdfs \
  --example-ids-file docs/research/paper-draft/smoke-example-ids.txt \
  --output-dir results/hf/paper/ablation-smoke-no-expand-v1 \
  --disable-expand-context \
  --minimal-artifacts \
  --no-resume
```

No rerank:

```bash
uv run python scripts/run_hf_eval.py \
  --agent focus \
  --protocol agentic_multi_page \
  --tool-set full \
  --hf-revision 3774c67f8b814392b6d04c939e904f749a3f52eb \
  --staging-dir /Users/gabrielbo/.cache/focusparse/paper-3774c67f8b814392b6d04c939e904f749a3f52eb \
  --pdfs-root /Users/gabrielbo/.cache/focusparse/pdfs \
  --example-ids-file docs/research/paper-draft/smoke-example-ids.txt \
  --output-dir results/hf/paper/ablation-smoke-no-rerank-v1 \
  --disable-rerank \
  --minimal-artifacts \
  --no-resume
```

Retry off:

```bash
uv run python scripts/run_hf_eval.py \
  --agent focus \
  --protocol agentic_multi_page \
  --tool-set full \
  --hf-revision 3774c67f8b814392b6d04c939e904f749a3f52eb \
  --staging-dir /Users/gabrielbo/.cache/focusparse/paper-3774c67f8b814392b6d04c939e904f749a3f52eb \
  --pdfs-root /Users/gabrielbo/.cache/focusparse/pdfs \
  --example-ids-file docs/research/paper-draft/smoke-example-ids.txt \
  --output-dir results/hf/paper/ablation-smoke-retry-off-v1 \
  --max-retries 0 \
  --max-evidence-retries 0 \
  --minimal-artifacts \
  --no-resume
```

Answer-shape repair off:

```bash
uv run python scripts/run_hf_eval.py \
  --agent focus \
  --protocol agentic_multi_page \
  --tool-set full \
  --hf-revision 3774c67f8b814392b6d04c939e904f749a3f52eb \
  --staging-dir /Users/gabrielbo/.cache/focusparse/paper-3774c67f8b814392b6d04c939e904f749a3f52eb \
  --pdfs-root /Users/gabrielbo/.cache/focusparse/pdfs \
  --example-ids-file docs/research/paper-draft/smoke-example-ids.txt \
  --output-dir results/hf/paper/ablation-smoke-answer-shape-off-v1 \
  --disable-answer-shape-repair \
  --minimal-artifacts \
  --no-resume
```
