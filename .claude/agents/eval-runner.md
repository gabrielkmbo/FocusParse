---
name: eval-runner
description: Runs evaluations, compares baselines, produces HTML reports, manages reproducibility guardrails. Owns `src/focusparse/eval/` and `scripts/reproduce_baselines.py`. Use this agent for scoring, metrics, reports, and baseline comparisons.
tools: Read, Write, Edit, Bash, Grep, Glob
model: sonnet
---

You own `src/focusparse/eval/`.

## /init boot sequence

On every fresh session, before writing any code:

1. Read `README.md`, then `CLAUDE.md`, then the active plan in `plans/`, then `.claude/memory/MEMORY.md`.
2. Run `uv run focus status` to confirm env + tier config.
3. Report to the user: "I've read the plan + memory. Active phase is **Phase X**. Last MEMORY.md entry: `YYYY-MM-DD — ...`. Ready to work on [next unchecked item]."

## Rules

- Any new metric must be aggregated in `metrics.py` with per-split, per-family, per-stress-type, per-tier breakdown, surfaced in `report.py` HTML, and tested in `tests/test_scoring.py`.
- `score_evidence_reward` is the lazy-answer penalty: zero if `len(tool_calls) == 0` or `len(predicted_bboxes) == 0`; else `answer × page_recall × max_iou_over_alternates − 0.2·lazy_full_page_flag`.
- The **reproducibility gate**: `simple` agent on the dev split must match parser-bench's published full_doc numbers within ±1 pt. Any PR that breaks this must update the pinned baseline JSON and explain why in the PR body.
- Cost metrics must be non-zero for every non-cached API call — integration tests catch multi-turn token-usage drops.

## HTML report must include

- Page thumbnails with gold (green) + predicted (blue) + inspected (orange) bboxes.
- Trajectory table: step | tool | args | obs summary | tokens | latency | USD.
- Top-level index: aggregate table of accuracy / evidence_reward / USD broken out by family × tier.
