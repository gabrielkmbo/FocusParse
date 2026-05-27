# FocusParse Paper Ablation Plan

Date: 2026-05-24

Status: record of the mechanism table plan and completed ablations. The current
paper claim is supported by a matched seven-method result, 3-row smoke checks
for the pure-ablation switches, and completed n=148 no-expand/no-rerank/
verifier-repair/answer-shape-repair ablations.

Latest harness support:

- `scripts/run_hf_eval.py --disable-rerank` skips the query-conditioned rerank
  stage while preserving the original localizer order.
- `scripts/run_hf_eval.py --disable-expand-context` skips only the
  `expand_context` stage while keeping `run_python` available under
  `--tool-set full`.
- `--max-retries 0 --max-evidence-retries 0` disables verifier-directed repair
  loops for a pre-loop baseline.
- `scripts/run_hf_eval.py --disable-answer-shape-repair` disables only
  answer-shape-specific retry hints and accepted-retry selection guards while
  preserving the non-shape verifier repair loop.
- `docs/research/paper-draft/ablation-smoke-summary.md` records completed
  3-row smoke checks for all three switches.
- `docs/research/paper-draft/no-expand-ablation-summary.md` records the full
  n=148 no-expand ablation and paired flip analysis.
- `docs/research/paper-draft/no-rerank-ablation-summary.md` records the full
  n=148 no-rerank ablation and paired flip analysis.
- `docs/research/paper-draft/verifier-repair-ablation-summary.md` records the
  full n=148 verifier-directed repair ablation and paired flip analysis.
- `docs/research/paper-draft/answer-shape-repair-ablation-summary.md` records
  the full n=148 answer-shape repair ablation and paired flip analysis.

## What Exists Today

The final matched headline table already gives a coarse tool-count ablation:

| Row | Tool set | Interpretation | Limitation |
| --- | --- | --- | --- |
| FocusParse +2 | `inspect_region`, `get_text_layer` | Evidence can be inspected/read, but FocusParse-specific `expand_context` and `run_python` are unavailable. | This mixes "no expand" with "no run_python"; it is not a pure expand ablation. |
| FocusParse +4 | `inspect_region`, `get_text_layer`, `expand_context`, `run_python` | Full current harness; paired summary now exists in `ablation-summary.md`. | Does not isolate which +4 component caused gains. |

This is enough for a workshop draft if the paper is honest, but not enough for a
strong main-conference mechanism claim.

## Minimum Workshop Ablations

Run these first because they directly test the slide-deck thesis.

| Ablation | Question answered | Current support | Required artifact |
| --- | --- | --- | --- |
| FocusParse +2 versus +4 | Does adding context expansion / computation tools help over inspect+text alone? | Complete: `results/paper/ablation-summary/focusparse-toolset-ablation.md` reports 148 paired rows, 9 recoveries, 7 regressions, and +2 net correct. | Use as the coarse tool-set ablation; still run pure no-expand to isolate expansion. |
| Full FocusParse with verifier loop disabled | Does bounded repair matter beyond first-pass packet construction? | Complete: `results/hf/paper/ablation-verifier-off-v1/` scored 62.8% versus 61.5% for full +4, with 9 recoveries, 11 regressions, and -2 net correct when repair is restored. | Use `verifier-repair-ablation-summary.md` as a mixed/negative mechanism row. |
| Full FocusParse with rerank disabled | Does query-conditioned region ordering matter after localization? | Complete: `results/hf/paper/ablation-no-rerank-v1/` scored 56.1% versus 61.5% for full +4, with 19 recoveries, 11 regressions, and +8 net correct when rerank is restored. | Use `no-rerank-ablation-summary.md` as the localization mechanism row. |
| Full FocusParse with expand disabled | Does role-labeled context expansion matter apart from `run_python` availability? | Complete: `results/hf/paper/ablation-no-expand-v1/` scored 59.5% versus 61.5% for full +4, with 14 recoveries, 11 regressions, and +3 net correct when expansion is restored. | Use `no-expand-ablation-summary.md` as the first pure mechanism row. |
| Full FocusParse with answer-shape repair disabled | Does the paper gain come from scorer-shape normalization? | Complete: `results/hf/paper/ablation-answer-shape-off-v1/` scored 64.2% versus 61.5% for full +4, with 9 recoveries, 13 regressions, and -4 net correct when answer-shape repair is restored. | Use `answer-shape-repair-ablation-summary.md` as a negative mechanism control. |
| Full FocusParse with optional enhancement flags off | Does the current default result depend on non-default sprint features? | Final paper result already uses defaults for optional flags. | Record feature flags from `run.json` in the ablation table. |
| Failure taxonomy by final-answer status | What fails when the harness still misses? | `failure-taxonomy.md` exists. | Use as analysis table or appendix. |

Recommended verifier-off command shape:

```bash
uv run python scripts/run_hf_eval.py \
  --agent focus \
  --protocol agentic_multi_page \
  --tool-set full \
  --hf-revision 3774c67f8b814392b6d04c939e904f749a3f52eb \
  --staging-dir /Users/gabrielbo/.cache/focusparse/paper-3774c67f8b814392b6d04c939e904f749a3f52eb \
  --pdfs-root /Users/gabrielbo/.cache/focusparse/pdfs \
  --output-dir results/hf/paper/ablation-verifier-off-v1 \
  --max-retries 0 \
  --max-evidence-retries 0 \
  --no-resume
```

Use a 3-row smoke with `--example-ids-file docs/research/paper-draft/smoke-example-ids.txt`
before the full run.

Recommended no-rerank command shape:

```bash
uv run python scripts/run_hf_eval.py \
  --agent focus \
  --protocol agentic_multi_page \
  --tool-set full \
  --hf-revision 3774c67f8b814392b6d04c939e904f749a3f52eb \
  --staging-dir /Users/gabrielbo/.cache/focusparse/paper-3774c67f8b814392b6d04c939e904f749a3f52eb \
  --pdfs-root /Users/gabrielbo/.cache/focusparse/pdfs \
  --output-dir results/hf/paper/ablation-no-rerank-v1 \
  --disable-rerank \
  --no-resume
```

Recommended no-expand command shape:

```bash
uv run python scripts/run_hf_eval.py \
  --agent focus \
  --protocol agentic_multi_page \
  --tool-set full \
  --hf-revision 3774c67f8b814392b6d04c939e904f749a3f52eb \
  --staging-dir /Users/gabrielbo/.cache/focusparse/paper-3774c67f8b814392b6d04c939e904f749a3f52eb \
  --pdfs-root /Users/gabrielbo/.cache/focusparse/pdfs \
  --output-dir results/hf/paper/ablation-no-expand-v1 \
  --disable-expand-context \
  --no-resume
```

## Stronger Conference Ablations

These require either new CLI switches or carefully controlled config changes.

| Ablation | Why it matters | Current implementation status |
| --- | --- | --- |
| No rerank | Tests whether query-conditioned region ordering matters after page routing. | Complete at n=148; see `no-rerank-ablation-summary.md`. |
| Inspect-only with full tool belt except expand disabled | Purely isolates context expansion. | CLI flag exists: `--disable-expand-context`; unlike `tool_set=minimal`, it keeps `run_python` available. |
| Expand without verifier-directed evidence retry | Separates first-pass expansion from verifier-controlled expansion. | Complete as part of the repair-off run: telemetry shows `retries_used=0` and `evidence_retries_used=0` for all 148 rows. |
| Answer-shape repair off | Tests whether the paper gain is evidence construction or output normalization. | Complete at n=148; see `answer-shape-repair-ablation-summary.md`. |
| Chart/table extraction on/off | Tests whether finance gains come from structured chart/table extraction rather than packet construction. | CLI has `--chart-to-table`; default final table has it off. Run only if claiming chart extraction as a contribution. |

## Paired Flip Analysis

For each ablation pair, report:

- total accuracy and bootstrap CI;
- datasheet and finance accuracy;
- cost per correct;
- page recall and BBox IoU;
- lazy-answer rate;
- paired recoveries/regressions against full FocusParse +4;
- examples where answer accuracy improved but BBox IoU regressed, and vice
  versa.

The paired flip table is more convincing than aggregate accuracy alone because
the thesis is mechanistic: inspect/expand should move localization and evidence
quality, not only final answers.

## Stop Rule

Do not spend full-run budget on every possible flag. For the first workshop
paper, the minimum defensible ablation set is:

1. existing +2 versus +4;
2. full +4 versus verifier/retry disabled;
3. failure taxonomy over the final +4 errors;
4. two qualitative examples showing multi-piece evidence assembly.

The minimum mechanism set is now complete. Remaining experiment work should be
targeted to the chosen venue's page budget: variance-controlled replication,
chart/table extraction controls only if claimed, and any stronger-result rerun
needed to supersede the verified 61.5% headline.
