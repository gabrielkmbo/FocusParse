# Paper Status

FocusParse studies whether a structured evidence-localization harness can beat
base VLM and generic tool-agent baselines on dense finance and datasheet QA.

## Current Paper-Safe Claim

On the pinned 148-row parser-bench paper slice, FocusParse +4 reaches 61.5%
overall accuracy, 66.3% on datasheets, and 51.1% on finance. It outperforms the
base VLM by 17.6 points overall and generic tool-agent comparators by 43-55
points overall under the same `agentic_multi_page` protocol.

## Current Table

| Method | Overall acc | Datasheet acc | Finance acc | $/correct | BBox IoU | Page recall | Latency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Base VLM | 43.9% | 47.5% | 36.2% | $0.0102 | 0.000 | 0.848 | 2.52s |
| ReAct +2 tools | 18.2% | 22.8% | 8.5% | $0.1341 | 0.336 | 0.819 | 14.00s |
| ReAct +4 tools | 16.2% | 20.8% | 6.4% | $0.1946 | 0.309 | 0.727 | 14.40s |
| Agent baseline +2 tools | 8.1% | 10.9% | 2.1% | $0.1324 | 0.000 | 0.000 | 5.21s |
| Agent baseline +4 tools | 6.1% | 7.9% | 2.1% | $0.1811 | 0.000 | 0.000 | 5.25s |
| FocusParse +2 tools | 60.1% | 64.4% | 51.1% | $0.0282 | 0.897 | 0.929 | 3.30s |
| FocusParse +4 tools | 61.5% | 66.3% | 51.1% | $0.0248 | 0.857 | 0.914 | 3.20s |

Source: May 24 matched seven-method run, HF revision
`3774c67f8b814392b6d04c939e904f749a3f52eb`, tier SHA `0b139a04`.

## Paper Source

- `docs/paper/focusparse-paper.md`: submission-facing Markdown draft.
- `docs/paper/main.tex`: standalone LaTeX draft.
- `docs/paper/references.bib`: bibliography.

## Caveats

- The stronger historical 66.9% checkpoint is documented but not raw-verified
  in the current checkout, so it is not the headline claim.
- Raw run directories and qualitative asset bundles are local `results/`
  artifacts, not committed source files.
- Source PDFs and derived page/crop assets need a separate release-clearance
  pass before any public artifact package includes images.
