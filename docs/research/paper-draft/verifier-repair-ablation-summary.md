# FocusParse Verifier-Repair Ablation Summary

Date: 2026-05-24

Status: completed n=148 mechanism ablation for bounded verifier-directed
repair. This run preserves the full FocusParse tool belt, query-conditioned
rerank, context expansion, and verifier scoring, but sets both repair budgets to
zero: `--max-retries 0 --max-evidence-retries 0`.

## Source Artifacts

Verifier-directed repair off:

```text
results/hf/paper/ablation-verifier-off-v1/focusparse_focus_agentic_multi_page_0b139a04.json
results/hf/paper/ablation-verifier-off-v1/focusparse_focus_agentic_multi_page_0b139a04/run.json
results/hf/paper/ablation-verifier-off-v1/focusparse_focus_agentic_multi_page_0b139a04/per_example.jsonl
```

Paired analysis:

```text
results/paper/mechanism-ablation/verifier-off-v1/focusparse-verifier-repair-ablation.md
results/paper/mechanism-ablation/verifier-off-v1/focusparse-verifier-repair-ablation.json
results/paper/mechanism-ablation/verifier-off-v1/focusparse-verifier-repair-ablation-flips.csv
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
| Verifier repair off | 148 | 62.8% | 68.3% | 51.1% | 0.920 | 0.898 | `$0.0282` |
| Full +4 with verifier repair | 148 | 61.5% | 66.3% | 51.1% | 0.914 | 0.857 | `$0.0248` |

Paired flips:

| Slice | n | Full +4 repair delta | Recoveries | Regressions | Net correct | Repair-off IoU | Full +4 IoU |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Overall | 148 | -1.4 pp | 9 | 11 | -2 | 0.898 | 0.857 |
| Datasheet | 101 | -2.0 pp | 6 | 8 | -2 | 0.884 | 0.851 |
| Finance | 47 | +0.0 pp | 3 | 3 | 0 | 0.927 | 0.871 |

Telemetry confirms `retries_used=0` and `evidence_retries_used=0` for all 148
rows in the repair-off run.

## Paper Interpretation

This is a negative or mixed mechanism result, not evidence that verifier repair
is the source of the final paper gain. On this exact matched run, the
repair-off condition is slightly more accurate than the final full +4 row:
93/148 versus 91/148. Full repair recovers 9 rows but regresses 11, with the
net loss concentrated in datasheets and no net finance change.

The submission-safe statement is:

> On the matched n=148 paper slice, disabling verifier-directed repair while
> preserving verifier scoring does not reduce accuracy: repair-off scores
> 62.8% versus 61.5% for the final full +4 row. This suggests the current paper
> gain is better attributed to evidence localization, reranking, inspection,
> and context expansion than to the bounded repair loop.

This result still helps the paper. It separates first-pass evidence
construction from post-answer repair and makes the mechanism claim more honest:
FocusParse should emphasize evidence packet construction, while treating
verifier-directed repair as a diagnostic/control loop that needs further tuning.

## Notes

The run completed after one transient Anthropic timeout recovered through the
configured provider retry path. Non-fatal MuPDF warnings appeared on annotated
PDFs, matching prior paper runs.

The label "verifier-off" in the output directory is historical shorthand. The
verifier is not removed from the pipeline; it still scores the first answer.
Only verifier-directed repair after that score is disabled.

## Command

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

Paired summary command:

```bash
uv run python scripts/build_paper_ablation_summary.py \
  --baseline-dir results/hf/paper/ablation-verifier-off-v1/focusparse_focus_agentic_multi_page_0b139a04 \
  --treatment-dir results/hf/paper/2026-05-24-paper-headline-v1/headline/focusparse_focus_agentic_multi_page_0b139a04 \
  --baseline-label "FocusParse full with verifier-directed repair off" \
  --treatment-label "FocusParse full + verifier-directed repair" \
  --output-dir results/paper/mechanism-ablation/verifier-off-v1 \
  --output-stem focusparse-verifier-repair-ablation \
  --title "FocusParse Verifier-Repair Mechanism Ablation" \
  --interpretation-note "This isolates bounded verifier-directed repair after first-pass evidence construction: the baseline preserves full tool availability, rerank, expansion, and verifier scoring, but sets both max_retries and max_evidence_retries to 0 so verifier feedback cannot trigger a repair pass. The treatment is the final matched FocusParse +4 paper row."
```
