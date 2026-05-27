# FocusParse Answer-Shape Repair Ablation Summary

Date: 2026-05-24

Status: completed n=148 mechanism control for answer-shape-specific repair.
This run preserves the full FocusParse tool belt, query-conditioned rerank,
context expansion, verifier scoring, and the non-shape verifier repair loop,
but disables answer-shape-specific retry hints and accepted-retry selection
guards with `--disable-answer-shape-repair`.

## Source Artifacts

Answer-shape repair off:

```text
results/hf/paper/ablation-answer-shape-off-v1/focusparse_focus_agentic_multi_page_0b139a04.json
results/hf/paper/ablation-answer-shape-off-v1/focusparse_focus_agentic_multi_page_0b139a04/run.json
results/hf/paper/ablation-answer-shape-off-v1/focusparse_focus_agentic_multi_page_0b139a04/per_example.jsonl
```

Paired analysis:

```text
results/paper/mechanism-ablation/answer-shape-off-v1/focusparse-answer-shape-repair-ablation.md
results/paper/mechanism-ablation/answer-shape-off-v1/focusparse-answer-shape-repair-ablation.json
results/paper/mechanism-ablation/answer-shape-off-v1/focusparse-answer-shape-repair-ablation-flips.csv
```

Final full +4 comparison row:

```text
results/hf/paper/2026-05-24-paper-headline-v1/headline/focusparse_focus_agentic_multi_page_0b139a04/
```

Both runs use HF revision `3774c67f8b814392b6d04c939e904f749a3f52eb`, tier SHA
`0b139a04`, `agentic_multi_page`, `tool_set=full`, and 148 paired rows. Pairing
preserves the intentional duplicate ID by matching on `(example_id, occurrence)`.

## Result

| Condition | n | Overall | Datasheet | Finance | Page recall | BBox IoU | Cost / correct |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Answer-shape repair off | 148 | 64.2% | 70.3% | 51.1% | 0.945 | 0.896 | `$0.0224` |
| Full +4 with answer-shape repair | 148 | 61.5% | 66.3% | 51.1% | 0.914 | 0.857 | `$0.0248` |

Paired flips:

| Slice | n | Full +4 repair delta | Recoveries | Regressions | Net correct | Repair-off IoU | Full +4 IoU |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Overall | 148 | -2.7 pp | 9 | 13 | -4 | 0.896 | 0.857 |
| Datasheet | 101 | -4.0 pp | 5 | 9 | -4 | 0.893 | 0.851 |
| Finance | 47 | +0.0 pp | 4 | 4 | 0 | 0.902 | 0.871 |

Telemetry confirms the switch did not disable the whole repair loop:
`retries_used=1` and `evidence_retries_used=1` on 64/148 rows. It specifically
disabled answer-shape retry hints and answer-shape accepted-retry preservation:
`accepted_retry_preserved_initial=false` for all 148 rows.

## Paper Interpretation

This is a negative mechanism control. On this exact matched run, disabling the
answer-shape-specific repair behavior improves accuracy: 95/148 versus 91/148.
Full answer-shape repair recovers 9 rows but regresses 13, with the net loss
concentrated in datasheets and no net finance change.

The submission-safe statement is:

> On the matched n=148 paper slice, answer-shape-specific repair is not carrying
> the FocusParse gain: disabling it while preserving full evidence construction
> and non-shape verifier repair scores 64.2% versus 61.5% for the final full +4
> row. This strengthens the attribution to evidence localization, reranking,
> inspection, and context expansion, while identifying answer-shape repair as an
> over-correction risk that needs tuning before it should be claimed as a
> positive mechanism.

This result is useful because it answers the reviewer concern that the paper's
gain might be mostly scorer-shape normalization. In the current code, the
answer-shape-specific guards are not the positive source of the verified
headline row. They are better framed as an analysis/control component and a
future method-improvement target.

## Notes

The full run completed with one transient Anthropic timeout recovered through
the configured provider retry path. Non-fatal MuPDF structure warnings appeared
on annotated PDFs, matching prior paper runs.

The smoke run under
`results/hf/paper/ablation-smoke-answer-shape-off-v1/` completed 3/3 and
confirmed the feature bit before the full n=148 run.

## Command

```bash
uv run python scripts/run_hf_eval.py \
  --agent focus \
  --protocol agentic_multi_page \
  --tool-set full \
  --hf-revision 3774c67f8b814392b6d04c939e904f749a3f52eb \
  --staging-dir /Users/gabrielbo/.cache/focusparse/paper-3774c67f8b814392b6d04c939e904f749a3f52eb \
  --pdfs-root /Users/gabrielbo/.cache/focusparse/pdfs \
  --output-dir results/hf/paper/ablation-answer-shape-off-v1 \
  --disable-answer-shape-repair \
  --minimal-artifacts \
  --no-resume
```

Paired summary command:

```bash
uv run python scripts/build_paper_ablation_summary.py \
  --baseline-dir results/hf/paper/ablation-answer-shape-off-v1/focusparse_focus_agentic_multi_page_0b139a04 \
  --treatment-dir results/hf/paper/2026-05-24-paper-headline-v1/headline/focusparse_focus_agentic_multi_page_0b139a04 \
  --baseline-label "FocusParse full with answer-shape repair off" \
  --treatment-label "FocusParse full + answer-shape repair" \
  --output-dir results/paper/mechanism-ablation/answer-shape-off-v1 \
  --output-stem focusparse-answer-shape-repair-ablation \
  --title "FocusParse Answer-Shape Repair Mechanism Ablation" \
  --interpretation-note "This isolates answer-shape-specific retry and selection behavior: the baseline preserves verifier scoring, full tool availability, rerank, expansion, and non-shape verifier repair, but disables answer-shape-specific retry hints and selection guards. The treatment is the final matched FocusParse +4 paper row."
```
