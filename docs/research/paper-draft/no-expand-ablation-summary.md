# FocusParse No-Expand Ablation Summary

Date: 2026-05-24

Status: first completed n=148 pure mechanism ablation for the paper. This run
isolates context expansion more directly than the coarse +2 versus +4 tool-set
comparison because the no-expand baseline keeps the full tool-belt shape except
that `expand_context` is disabled while `run_python` remains available.

## Source Artifacts

No-expand run:

```text
results/hf/paper/ablation-no-expand-v1/focusparse_focus_agentic_multi_page_0b139a04.json
results/hf/paper/ablation-no-expand-v1/focusparse_focus_agentic_multi_page_0b139a04/run.json
results/hf/paper/ablation-no-expand-v1/focusparse_focus_agentic_multi_page_0b139a04/per_example.jsonl
```

Paired analysis:

```text
results/paper/mechanism-ablation/no-expand-v1/focusparse-no-expand-ablation.md
results/paper/mechanism-ablation/no-expand-v1/focusparse-no-expand-ablation.json
results/paper/mechanism-ablation/no-expand-v1/focusparse-no-expand-ablation-flips.csv
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
| No `expand_context` | 148 | 59.5% | 62.4% | 53.2% | 0.917 | 0.847 | `$0.0279` |
| Full +4 with `expand_context` | 148 | 61.5% | 66.3% | 51.1% | 0.914 | 0.857 | `$0.0248` |

Paired flips:

| Slice | n | Full +4 delta | Recoveries | Regressions | Net correct | No-expand IoU | Full +4 IoU |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Overall | 148 | +2.0 pp | 14 | 11 | +3 | 0.847 | 0.857 |
| Datasheet | 101 | +4.0 pp | 11 | 7 | +4 | 0.856 | 0.851 |
| Finance | 47 | -2.1 pp | 3 | 4 | -1 | 0.828 | 0.871 |

## Paper Interpretation

This is the strongest current mechanism evidence for the inspect/expand thesis:
adding context expansion to the otherwise full harness gives a small overall
gain and a clearer datasheet gain. It also shows a tradeoff. Finance accuracy
falls by one net paired row even though finance BBox IoU improves, so the paper
should not claim expansion is uniformly beneficial across all dense-document
subdomains.

The submission-safe statement is:

> On the matched n=148 paper slice, restoring `expand_context` to the full
> FocusParse harness improves overall accuracy from 59.5% to 61.5%, with the
> net gain concentrated in datasheets (+4 correct paired rows) and a small
> finance tradeoff (-1 correct paired row).

Do not overstate this as proof that expansion alone explains the whole
FocusParse advantage. The effect is modest, scorer-sensitive in a few rows, and
should be presented alongside the failure taxonomy and qualitative evidence
assembly examples.

## Command

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

Paired summary command:

```bash
uv run python scripts/build_paper_ablation_summary.py \
  --baseline-dir results/hf/paper/ablation-no-expand-v1/focusparse_focus_agentic_multi_page_0b139a04 \
  --treatment-dir results/hf/paper/2026-05-24-paper-headline-v1/headline/focusparse_focus_agentic_multi_page_0b139a04 \
  --baseline-label "FocusParse full without expand_context" \
  --treatment-label "FocusParse full + expand_context" \
  --output-dir results/paper/mechanism-ablation/no-expand-v1 \
  --output-stem focusparse-no-expand-ablation \
  --title "FocusParse No-Expand Mechanism Ablation" \
  --interpretation-note "This isolates context expansion more directly than the +2/+4 tool-set ablation: both conditions keep the full tool belt shape except the baseline skips expand_context while preserving run_python availability. The treatment is the final matched FocusParse +4 paper row."
```
