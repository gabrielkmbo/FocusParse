# FocusParse Ablation Summary

Date: 2026-05-24

Status: first concrete ablation artifact for the paper package. This summary is
generated from the final matched n=148 paper run, not from a new API call.

## Tool-Set Ablation: FocusParse +2 To FocusParse +4

Source rows:

```text
results/hf/paper/2026-05-24-paper-headline-v1/headline/focusparse_focus_agentic_multi_page_0b139a04_tminimal/per_example.jsonl
results/hf/paper/2026-05-24-paper-headline-v1/headline/focusparse_focus_agentic_multi_page_0b139a04/per_example.jsonl
```

Generated artifacts:

```text
results/paper/ablation-summary/focusparse-toolset-ablation.md
results/paper/ablation-summary/focusparse-toolset-ablation.json
results/paper/ablation-summary/focusparse-toolset-ablation-flips.csv
```

The paired comparison preserves duplicate example IDs by pairing on
`(example_id, occurrence)` rather than plain `example_id`.

| Slice | n | +2 accuracy | +4 accuracy | Delta | Recoveries | Regressions | +2 BBox IoU | +4 BBox IoU |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Overall | 148 | 60.1% | 61.5% | +1.4 pp | 9 | 7 | 0.897 | 0.857 |
| Datasheet | 101 | 64.4% | 66.3% | +2.0 pp | 5 | 3 | 0.902 | 0.851 |
| Finance | 47 | 51.1% | 51.1% | +0.0 pp | 4 | 4 | 0.887 | 0.871 |

Cost per correct improves from `$0.0282` to `$0.0248` overall because the +4 run
gets two additional correct rows with a comparable total spend profile. Page
recall and BBox IoU are slightly lower in the +4 condition, so this result
should be interpreted carefully: it supports the full harness as the current
submission-safe best row, but it does not prove that `expand_context` alone is
the causal lever.

## Paper Interpretation

This is a coarse mechanism row, not a pure component ablation:

- +2 tools: `inspect_region`, `get_text_layer`
- +4 tools: `inspect_region`, `get_text_layer`, `expand_context`, `run_python`

The result supports a conservative workshop claim:

> The full evidence-construction harness gives a small but real answer-accuracy
> lift over inspect/text-only FocusParse on the matched paper slice, with the
> gain concentrated in datasheets.

This result is now complemented by pure n=148 no-expand, no-rerank,
verifier-repair, and answer-shape-repair ablations in
`no-expand-ablation-summary.md`, `no-rerank-ablation-summary.md`,
`verifier-repair-ablation-summary.md`, and
`answer-shape-repair-ablation-summary.md`. The pure ablations give narrower
mechanism claims: restoring `expand_context` improves overall accuracy from
59.5% to 61.5%, restoring rerank improves overall accuracy from 56.1% to 61.5%
and substantially improves localization, while restoring verifier-directed
repair moves 62.8% to 61.5% and restoring answer-shape repair moves 64.2% to
61.5%. The repair rows should be treated as mixed/negative controls rather than
sources of the paper gain.
