# Harness-Growth-Sprint Integration Run Results

Date: 2026-05-12 (template; values get filled in once experiments are fired)
Scope: Phase 4 of `~/.claude/plans/clever-sparking-babbage.md`. Code-ship for
Phases 0-3 documented in `.claude/memory/MEMORY.md` 2026-05-11 entry.
Branch: `harness-growth-sprint` off `origin/main`.

## Status

- [ ] Phase 0 ship-gate (variance harness): two cached n=148 replicates within ±0.5pp
- [ ] Phase 1 A/B (chart_to_table expansion vs Phase 0 rebaseline)
- [ ] Phase 2 A/B (LLM-driven inspector hard-case vs Phase 1 result)
- [ ] Phase 3 A/B (expander per-role gating vs Phase 2 result)
- [ ] Phase 4 integration: 3 replicates with all four levers on
- [ ] `configs/default.yaml` defaults flipped for phases that won ≥+3pp non-overlap

## Baseline (rebaseline-v2 canonical n=148, agentic_multi_page)

For reference; numbers from `results/hf/headline-v1-rebaseline-v2/headline_table.json`:

| Method                   | Datasheets acc | Finance acc | Overall acc | Overall $/correct | Mean latency |
| ------------------------ | -------------: | ----------: | ----------: | ----------------: | -----------: |
| Base VLM                 |          40.6% |       31.9% |       37.8% |           $0.0119 |         3.0s |
| ReAct +2                 |          16.8% |        6.4% |       13.5% |           $0.1846 |        16.1s |
| ReAct +4                 |          18.8% |        4.3% |       14.2% |           $0.2403 |        21.1s |
| Agent baseline +2        |           9.9% |        4.3% |        8.1% |           $0.1244 |         5.4s |
| Agent baseline +4        |           7.9% |        4.3% |        6.8% |           $0.1535 |         5.8s |
| **Our harness +2 tools** |      **56.4%** |   **36.2%** |   **50.0%** |       **$0.0153** |     **2.5s** |
| **Our harness +4 tools** |      **49.5%** |   **31.9%** |   **43.9%** |       **$0.0176** |     **2.5s** |

## Run plan

Run all commands with `.env` sourced:

```bash
set -a && source .env && set +a
```

The variance harness pins upstream LLM outputs so per-phase A/Bs aren't
dominated by ~7pp run-to-run sampling noise. Phase 0's run1 _records_ the
cache; every subsequent run _replays_ against the same dir.

### Phase 0 — variance harness ship-gate

```bash
# Run 1 — records the cache
uv run python scripts/run_hf_eval.py --agent focus --tool-set full \
  --protocol agentic_multi_page \
  --llm-cache-dir cache/llm_responses/sprint-phase0/run1 \
  --llm-cache-mode record-or-replay \
  --output-dir results/hf/sprint-2026-05-11/phase0-run1 \
  --staging-dir ~/.cache/focusparse/hf_staging \
  --pdfs-root ~/.cache/focusparse/pdfs

# Run 2 — replays under the same cache
uv run python scripts/run_hf_eval.py --agent focus --tool-set full \
  --protocol agentic_multi_page \
  --llm-cache-dir cache/llm_responses/sprint-phase0/run1 \
  --llm-cache-mode replay \
  --output-dir results/hf/sprint-2026-05-11/phase0-run2 \
  --staging-dir ~/.cache/focusparse/hf_staging \
  --pdfs-root ~/.cache/focusparse/pdfs
```

Acceptance: run1 vs run2 overall accuracy delta ≤ 0.5pp.

### Phase 1 — chart_to_table gate expansion

```bash
for i in 1 2; do
  uv run python scripts/run_hf_eval.py --agent focus --tool-set full \
    --protocol agentic_multi_page \
    --chart-to-table \
    --llm-cache-dir cache/llm_responses/sprint-phase0/run1 \
    --llm-cache-mode replay \
    --output-dir results/hf/sprint-2026-05-11/phase1-run$i \
    --staging-dir ~/.cache/focusparse/hf_staging \
    --pdfs-root ~/.cache/focusparse/pdfs
done
```

Decision: ship default-on (`chart_to_table_enabled: true` in
`configs/default.yaml`) if finance accuracy moves ≥+3pp non-overlap vs Phase 0.

### Phase 2 — LLM-driven inspector hard-case dispatch

```bash
for i in 1 2; do
  uv run python scripts/run_hf_eval.py --agent focus --tool-set full \
    --protocol agentic_multi_page \
    --chart-to-table --react-inspector \
    --llm-cache-dir cache/llm_responses/sprint-phase0/run1 \
    --llm-cache-mode replay \
    --output-dir results/hf/sprint-2026-05-11/phase2-run$i \
    --staging-dir ~/.cache/focusparse/hf_staging \
    --pdfs-root ~/.cache/focusparse/pdfs
done
```

Decision: ship default-on if (a) overall accuracy moves ≥+3pp non-overlap
**and** (b) hard-case slice accuracy ≥+10pp over the deterministic floor on
that same slice **and** (c) `verifier_unsupported_rate` on hard-case slice
falls ≥10pp. If (b)/(c) hold but (a) doesn't, the trigger is over-broad —
tighten and re-run.

### Phase 3 — expander per-role gating

Phase 3 is always on once Phase 2 is in — there's no separate flag (the new
thresholds + weights replace the uniform 0.5). The Phase 2 result above
already incorporates Phase 3 if Phase 2 was rerun on this branch. The
explicit A/B compares the current `harness-growth-sprint` HEAD to the same
sprint without the Phase 3 commit (`5a42c33`); if needed, the cleanest A/B
is to run on `5a42c33^` for the baseline.

Mechanism gate: ship if (a) overall accuracy ≥+1pp non-overlap **or** (b)
`mean_irrelevant_tool_call_count < mean_useful_tool_call_count` in the
diagnostics.

### Phase 4 — integration, 3 replicates

```bash
for i in 1 2 3; do
  uv run python scripts/run_hf_eval.py --agent focus --tool-set full \
    --protocol agentic_multi_page \
    --chart-to-table --react-inspector \
    --llm-cache-dir cache/llm_responses/sprint-phase0/run1 \
    --llm-cache-mode replay \
    --output-dir results/hf/sprint-2026-05-11/integration-run$i \
    --staging-dir ~/.cache/focusparse/hf_staging \
    --pdfs-root ~/.cache/focusparse/pdfs
done

# Roll up + compare against rebaseline-v2
uv run python scripts/render_headline_table.py \
  --runs results/hf/sprint-2026-05-11/integration-run1 \
         results/hf/sprint-2026-05-11/integration-run2 \
         results/hf/sprint-2026-05-11/integration-run3 \
  --output results/hf/sprint-2026-05-11/integration-rollup

uv run python scripts/compare_headline_tables.py \
  --baseline results/hf/headline-v1-rebaseline-v2/headline_table.json \
  --candidate results/hf/sprint-2026-05-11/integration-rollup/headline_table.json
```

Acceptance: std-dev across 3 replicates < 1.5pp; per-cell deltas reported
with 95% bootstrap CIs.

## Cost / time budget

Empirical from rebaseline-v2 (n=148, harness +4, single replicate):

- Cost: $1.14 total run
- Latency: 2.5 s mean × 148 = ~6 min wall-clock (sequential)
- Layout-endpoint cached → no extra HF-endpoint spend across replicates

Expected sprint totals:

- Phase 0: 2 runs × $1.14 = $2.30
- Phase 1: 2 runs × $1.50 (chart_to_table adds modest LLM-free OCR cost) = $3.00
- Phase 2: 2 runs × $1.50 (react inspector adds ~$0.005 × ~30% of examples ≈ $0.20) = $3.40
- Phase 3: covered by Phase 2 reruns
- Phase 4 integration: 3 runs × $1.70 = $5.10
- **Total: ~$13.80** (plus ~60-90 min wall-clock if sequential)

## Results

### Phase 0 ship-gate

| Run                  | Overall acc | Datasheet acc | Finance acc | $/correct | Mean latency |
| -------------------- | ----------: | ------------: | ----------: | --------: | -----------: |
| phase0-run1 (record) |           — |             — |           — |         — |            — |
| phase0-run2 (replay) |           — |             — |           — |         — |            — |
| Δ                    |           — |             — |           — |         — |            — |

Ship gate: |Δ overall| ≤ 0.5pp → variance harness deterministic upstream working.

Diagnostics check (must be identical across the two runs):

- `top_loop` counts
- `top_failure` distribution
- `top_verifier_action` distribution

### Phase 1 — chart_to_table expansion

| Run                 | Overall acc | Datasheet acc | Finance acc | $/correct | Mean latency |
| ------------------- | ----------: | ------------: | ----------: | --------: | -----------: |
| phase1-run1         |           — |             — |           — |         — |            — |
| phase1-run2         |           — |             — |           — |         — |            — |
| Mean                |           — |             — |           — |         — |            — |
| Δ vs Phase 0 (run1) |           — |             — |           — |         — |            — |

Mechanism check:

- `chart_to_table_attempt_rate` (finance): — (must rise ≥20pp from 0%)
- `cited_packet_chart_rate` (finance): — (must rise ≥10pp from 0%)

Decision: [ ] ship default-on / [ ] opt-in flag / [ ] revert

### Phase 2 — hard-case dispatch

| Run               | Overall acc | Datasheet acc | Finance acc | $/correct | Mean latency |
| ----------------- | ----------: | ------------: | ----------: | --------: | -----------: |
| phase2-run1       |           — |             — |           — |         — |            — |
| phase2-run2       |           — |             — |           — |         — |            — |
| Mean              |           — |             — |           — |         — |            — |
| Δ vs Phase 1 mean |           — |             — |           — |         — |            — |

Mechanism check:

- `inspector_path == "react_hard_case"` rate: — (target ~20-30%)
- Hard-case slice accuracy: — vs deterministic floor on same slice — (target Δ ≥+10pp)
- Hard-case slice `verifier_unsupported_rate`: — (target Δ ≤ -10pp)

Decision: [ ] ship default-on / [ ] opt-in flag / [ ] tighten trigger / [ ] revert

### Phase 3 — expander per-role gating

| Run                                                   | Overall acc | Datasheet acc | Finance acc | $/correct | Mean latency |
| ----------------------------------------------------- | ----------: | ------------: | ----------: | --------: | -----------: |
| Phase 3 already in Phase 2 (current HEAD) — see above |             |               |             |           |              |

Mechanism check:

- `mean_useful_tool_call_count` vs `mean_irrelevant_tool_call_count`: — / — (target former > latter)
- Per-role attachment shifts (caption, axis_label, table_cell_lookup): —

Decision: [ ] ship default-on / [ ] opt-in flag / [ ] revert

### Phase 4 — integration (3 replicates, all flags on)

| Run                                 | Overall acc | Datasheet acc | Finance acc | $/correct | Mean latency |
| ----------------------------------- | ----------: | ------------: | ----------: | --------: | -----------: |
| integration-run1                    |           — |             — |           — |         — |            — |
| integration-run2                    |           — |             — |           — |         — |            — |
| integration-run3                    |           — |             — |           — |         — |            — |
| Mean                                |           — |             — |           — |         — |            — |
| Std-dev                             |           — |             — |           — |         — |            — |
| Δ vs rebaseline-v2 (focus +4 43.9%) |           — |             — |           — |         — |            — |

Acceptance: std-dev < 1.5pp; mean ≥ 55% overall with non-overlap CIs vs Base VLM.

## Qualitative examples (post-integration)

After Phase 4 ships, fill in 2-3 examples where the integrated stack newly
wins where it lost in rebaseline-v2. The picks should illustrate which
specific Phase (1 / 2 / 3) carried the win.

### Example 1 — chart_to_table win (Phase 1)

- Example ID: —
- Family: —
- Question: —
- Gold: —
- Rebaseline-v2 prediction: —
- Integration prediction: —
- Mechanism: chart_csv populated; reasoner cited the CSV row directly.

### Example 2 — hard-case dispatch win (Phase 2)

- Example ID: —
- Family: —
- Question: —
- Gold: —
- Rebaseline-v2 prediction: —
- Integration prediction: —
- Mechanism: `inspector_path == "react_hard_case"`; the deterministic top-N
  picked the wrong region, the ReAct dispatcher picked the right one.

### Example 3 — per-role expander win (Phase 3)

- Example ID: —
- Family: —
- Question: —
- Gold: —
- Rebaseline-v2 prediction: —
- Integration prediction: —
- Mechanism: caption neighbor at rel 0.35 attached (would have been dropped
  under uniform 0.5 threshold); reasoner cited the caption text.

## Config diff to apply post-Phase-4

Once decisions are recorded above, apply these to `configs/default.yaml`
(or set as defaults in `FocusWorkflow.__init__`):

```yaml
# Flip to `true` for any phase that won ≥+3pp non-overlap CIs:
chart_to_table_enabled: <decision>
use_react_inspector: <decision>
# Phase 3 (per-role gating) is unconditionally on — it replaced the
# uniform threshold in expander.py.
```

## Pointer to plan + recalibration doc

- Sprint plan: `~/.claude/plans/clever-sparking-babbage.md`
- Research recalibration: `docs/research/2026-05-11-recalibration-and-research-state.md`
- Sprint changelog entry: `.claude/memory/MEMORY.md` 2026-05-11
- Branch: `harness-growth-sprint` (6 commits ahead of `origin/main`)
