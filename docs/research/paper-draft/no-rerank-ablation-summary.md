# FocusParse No-Rerank Ablation Summary

Date: 2026-05-24

Status: completed n=148 pure mechanism ablation for query-conditioned rerank.
This run isolates the rerank stage by keeping the full tool belt and context
expansion available while skipping LLM reranking of localized regions.

## Source Artifacts

No-rerank run:

```text
results/hf/paper/ablation-no-rerank-v1/focusparse_focus_agentic_multi_page_0b139a04.json
results/hf/paper/ablation-no-rerank-v1/focusparse_focus_agentic_multi_page_0b139a04/run.json
results/hf/paper/ablation-no-rerank-v1/focusparse_focus_agentic_multi_page_0b139a04/per_example.jsonl
```

Paired analysis:

```text
results/paper/mechanism-ablation/no-rerank-v1/focusparse-no-rerank-ablation.md
results/paper/mechanism-ablation/no-rerank-v1/focusparse-no-rerank-ablation.json
results/paper/mechanism-ablation/no-rerank-v1/focusparse-no-rerank-ablation-flips.csv
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
| No rerank | 148 | 56.1% | 60.4% | 46.8% | 0.849 | 0.738 | `$0.0249` |
| Full +4 with rerank | 148 | 61.5% | 66.3% | 51.1% | 0.914 | 0.857 | `$0.0248` |

Paired flips:

| Slice | n | Full +4 delta | Recoveries | Regressions | Net correct | No-rerank IoU | Full +4 IoU |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Overall | 148 | +5.4 pp | 19 | 11 | +8 | 0.738 | 0.857 |
| Datasheet | 101 | +5.9 pp | 13 | 7 | +6 | 0.746 | 0.851 |
| Finance | 47 | +4.3 pp | 6 | 4 | +2 | 0.720 | 0.871 |

## Paper Interpretation

This is stronger mechanism evidence than the no-expand ablation for the
localization part of the thesis. Query-conditioned rerank improves both answer
accuracy and grounding quality: overall accuracy rises by 5.4 percentage
points, page recall rises from 0.849 to 0.914, and BBox IoU rises from 0.738 to
0.857.

The submission-safe statement is:

> On the matched n=148 paper slice, adding query-conditioned rerank to the full
> FocusParse harness improves accuracy from 56.1% to 61.5%, with gains in both
> datasheets (+6 correct paired rows) and finance (+2 correct paired rows), and
> substantially improves region grounding.

This supports the paper's claim that the harness gain is not only answer-side
reasoning. The evidence packet is better because the right localized regions are
selected and ordered before inspection and expansion.

## Notes

The run completed after several transient Anthropic timeouts recovered through
the configured provider retry path. Final artifacts have 148 rows and the
feature bits confirm `disable_rerank=true` and `disable_expand_context=false`.

## Command

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

Paired summary command:

```bash
uv run python scripts/build_paper_ablation_summary.py \
  --baseline-dir results/hf/paper/ablation-no-rerank-v1/focusparse_focus_agentic_multi_page_0b139a04 \
  --treatment-dir results/hf/paper/2026-05-24-paper-headline-v1/headline/focusparse_focus_agentic_multi_page_0b139a04 \
  --baseline-label "FocusParse full without rerank" \
  --treatment-label "FocusParse full + query-conditioned rerank" \
  --output-dir results/paper/mechanism-ablation/no-rerank-v1 \
  --output-stem focusparse-no-rerank-ablation \
  --title "FocusParse No-Rerank Mechanism Ablation" \
  --interpretation-note "This isolates query-conditioned region reranking: the baseline preserves full tool availability and context expansion but skips the rerank stage, while the treatment is the final matched FocusParse +4 paper row."
```
