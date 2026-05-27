# FocusParse Qualitative Baseline Comparisons

Date: 2026-05-24

Status: same-revision qualitative comparator artifact for the two main composed
figure panels. This closes the first pass of the "what do baselines miss?"
gate for the qualitative section.

## Source

Final matched headline directory:

```text
results/hf/paper/2026-05-24-paper-headline-v1/headline/
```

Command:

```bash
uv run python scripts/build_qualitative_baseline_comparison.py --headline-dir results/hf/paper/2026-05-24-paper-headline-v1/headline --output-dir results/paper/qualitative-baseline-comparisons
```

Generated files:

```text
results/paper/qualitative-baseline-comparisons/qualitative-baseline-comparison.md
results/paper/qualitative-baseline-comparisons/qualitative-baseline-comparison.csv
```

The generator reads all seven `per_example.jsonl` files from the final
same-revision run: Base VLM, ReAct +2/+4, Agent baseline +2/+4, and
FocusParse +2/+4.

## Latvia Finance Example

Example id:

```text
fin-bis_qr_2025_mar-0050
```

Core comparison:

| Method | Prediction | Grounding result |
| --- | --- | --- |
| Base VLM | `Unanswerable` | No citations, page recall 0. |
| ReAct +2 tools | `Latvia` | Correct answer, but weak region grounding: BBox IoU 0.464. |
| ReAct +4 tools | Raw tool transcript ending in `Unanswerable` | Invalid final answer, no citations. |
| Agent baseline +2 tools | Raw action/final transcript choosing Estonia | Invalid final transcript, no citations. |
| Agent baseline +4 tools | Estonia | Wrong answer, no grounded citations. |
| FocusParse +2 tools | `Latvia` | Correct, but incomplete page recall: 0.667. |
| FocusParse +4 tools | `Latvia` | Grounded correct: page recall 1.0, BBox IoU 0.99999, three citations. |

Paper use:

This is the best qualitative failure contrast for the inspect/expand thesis.
The generic agents are willing to answer from a plausible reading of the
charts, but the grounded evidence object matters because the answer turns on
linking chart labels to the country-code table.

## JESD204B Datasheet Example

Example id:

```text
dat-JESD204B-Survival-Guide-0029
```

Core comparison:

| Method | Prediction | Grounding result |
| --- | --- | --- |
| Base VLM | `4` | Scorer accepts the non-exact numeric answer, but grounding is weak: page recall 0.5, BBox IoU 0. |
| ReAct +2 tools | Raw tool transcript containing an apparent `6` | Invalid final answer, no parsed citations. |
| ReAct +4 tools | `6` | Correct answer, but incomplete grounding: page recall 0.5, BBox IoU 0.435. |
| Agent baseline +2 tools | Explanatory sentence beginning with `6` | Correct answer without grounded evidence. |
| Agent baseline +4 tools | `6` | Correct answer without grounded evidence. |
| FocusParse +2 tools | `6` | Grounded correct: page recall 1.0, BBox IoU 0.99999, three citations. |
| FocusParse +4 tools | `6` | Grounded correct: page recall 1.0, BBox IoU 0.99999, three citations. |

Paper use:

This is the best qualitative grounding contrast for the datasheet section.
Some baselines can state the integer answer, but the paper's claim is not just
answer string accuracy. FocusParse is the method that preserves the timing
diagram and cross-page block-diagram evidence as a compact, citable packet set.

## Current Limitation

The comparison is currently a table/handoff artifact rather than an integrated
visual panel. The final submission can either:

1. Keep the comparison as an appendix table next to the two composed panels.
2. Add a small comparator strip to each final figure caption or figure body.
3. Use it as qualitative prose in the Results/Analysis section.
