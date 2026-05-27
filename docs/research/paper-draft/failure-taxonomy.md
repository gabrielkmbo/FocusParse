# FocusParse Failure Taxonomy

Date: 2026-05-24

Status: generated from the final matched FocusParse +4 `per_example.jsonl` in
`results/hf/paper/2026-05-24-paper-headline-v1/`.

Generated artifacts:

```text
results/paper/failure-taxonomy/failure-taxonomy.md
results/paper/failure-taxonomy/failure-taxonomy.csv
results/paper/failure-taxonomy/failure-taxonomy.json
```

Generation command:

```bash
uv run python scripts/build_paper_failure_taxonomy.py
```

## Summary

FocusParse +4 is correct on 91/148 examples (61.5%) and incorrect on 57/148
examples (38.5%). The taxonomy uses the same primary failure classifier as
`scripts/diagnose_predictions.py`.

| Bucket | Count | Datasheet | Finance | Error share | All-row share |
| --- | ---: | ---: | ---: | ---: | ---: |
| Verifier unsupported | 26 | 16 | 10 | 45.6% | 17.6% |
| Partial localization | 12 | 6 | 6 | 21.1% | 8.1% |
| Localization miss | 8 | 5 | 3 | 14.0% | 5.4% |
| Reasoning/extraction | 7 | 4 | 3 | 12.3% | 4.7% |
| Lazy/no bbox | 4 | 3 | 1 | 7.0% | 2.7% |

## Paper Interpretation

The dominant remaining failure is not generic tool laziness: only 4/57 errors
are lazy/no-bbox failures. The largest bucket is verifier-unsupported answers
after evidence collection, followed by incomplete or missed localization. This
supports the paper's analysis claim that the next lift is likely better
verification/evidence adjudication and better multi-region localization, not
simply giving the model more tools.

Representative examples are listed in the generated Markdown artifact. The
paper should use the short table above in the analysis section and keep the
example-level table for an appendix or reviewer artifact.
