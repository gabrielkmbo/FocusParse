# Project Changelog

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
