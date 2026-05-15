# Project Changelog

## 2026-05-15

- Added an agent-eyes audit builder that renders wrong rows as inspectable HTML:
  page overlays, selected/candidate crops, packet text, multi-scale/context
  crop refs, answer history, verifier payloads, and trajectory steps. The
  builder now reads `per_example.jsonl` before `predictions/*.json` so duplicate
  example ids do not get dropped by filename collisions. The latest audit entry
  point is `results/agent_eyes/2026-05-15-answer-shape-normalizer-wrong/index.html`.
- Added a narrow answer-shape normalizer after reasoner parsing. It handles
  gold-free syntax repairs only: finance accounting negatives, compact
  variable/unit labels, and exact-match page references. It intentionally does
  not add broad semantic rewrites or force any extra tool calls.
- The answer-shape run crossed the sprint threshold:
  `results/hf/sprint-2026-05-15/answer-shape-normalizer-oai-run2/focusparse_focus_agentic_multi_page_8c5e328d.json`
  scored **89/148 = 60.14%** with cost/correct **$0.0243**, mean latency
  **4.26s**, page recall **0.892**, bbox IoU **0.870**, and lazy-answer rate
  **0.041**. Domain split from `per_example.jsonl`: datasheet **64/101**,
  finance **25/47**.

## 2026-05-14

- Inspector chart tooling now allows a dynamic fallback for chart-family questions:
  generic `picture` regions with `figure_class=other` or `figure_class=screenshot`
  can use chart context / `chart_to_table` only when reranker evidence marks the
  region as primary or high-relevance. Explicit chart classes keep the previous
  path; weak generic visuals and non-chart questions remain blocked.
- After the chart-fallback full run regressed to 80/148, the generic fallback
  was tightened further: ambiguous chart-like families such as
  `dual_axis_disambiguation` require planner `evidence_types=["chart", ...]`
  before a generic `other` visual gets chart-context or `chart_to_table`
  treatment. This avoids treating diagram/schematic rows as chart rows.
- The tightened fallback without `--chart-to-table` produced the new OAI-cheap
  best full run: 87/148 = 58.78%, with finance at 22/47 and datasheet at
  65/101. The remaining gap is two rows short of 60%, so answer-shape /
  verifier-aware selection is the next likely lever.
