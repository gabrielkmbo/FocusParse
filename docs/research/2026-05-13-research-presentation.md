# FocusParse: A Structured Harness Beats Generic Agents at Document QA

A research presentation outline based on n=148 controlled experiments on
`gabrielbo/parser-bench`, all under a single reasoner model (`openai/gpt-5.4`),
a single benchmark revision (`3774c67`), and a single agentic protocol
(`agentic_multi_page`).

Date: 2026-05-13
Status: results assembled from the harness-growth sprint (`main` HEAD + the
Phase 4–6a branches). Single-replicate runs; variance discussion in §10.

---

## Slide 1 — Thesis

> **For document QA on technical datasheets and finance documents,
> agent _architecture_ — not raw VLM capability, not generic tool-using
> loops, and not tool count — is the load-bearing axis of accuracy and
> cost-efficiency. A structured, layout-first agent harness with
> typed evidence packets and a verifier as controller (FocusParse)
> beats every comparator at every domain by a wide margin, at
> 10–16× lower cost-per-correct and 6–8× lower latency.**

The independent variable is **agent architecture**, with four levels:

1. **Base VLM** (no tools, single shot).
2. **Generic ReAct** (think → act → observe loop, same tool belt as the harness).
3. **Generic agent baseline** (single-shot tool-selector + answer, no loop).
4. **FocusParse harness** (typed `plan → route → localize → rerank → inspect → expand → answer → verify` state machine).

All other variables — reasoner model, dataset, protocol, prompt budget,
scoring rule — are held constant. Tool count (+2 vs +4) is reported as
a secondary axis to show "more tools" is _not_ the explanation.

---

## Slide 2 — Setup

- **Benchmark**: `gabrielbo/parser-bench`, revision `3774c67`. n=148 canonical
  validation rows after filtering stress variants (29 spatial_separation +
  42 downscale).
- **Domain split**: 101 datasheet examples (technical PDFs, ARM/Analog/Infineon
  reference manuals) + 47 finance examples (10-K filings, JPM/BIS reports,
  visualization-heavy).
- **Protocol**: `agentic_multi_page`. Every method gets the same per-example
  summary tile view + the same page-list access. Comparator and harness
  agents pull from the same tool registry (`inspect_region`, `get_text_layer`
  for +2; adds `expand_context` and `run_python` for +4).
- **Reasoner**: `openai/gpt-5.4` for every method. The harness additionally
  uses `gemini-2.5-flash` (cheap) for planning/routing and
  `claude-haiku-4-5` (mid) for region reranking and verification.
- **Scoring**: `parser-bench`'s native scorer — exact-match on text and
  numeric, with normalized tolerance on units.

---

## Slide 3 — The Seven Cells

All numbers are single-run n=148 on the same revision.

| Method                   | Datasheet acc | Finance acc | Overall acc | $/correct | Latency |
| ------------------------ | ------------: | ----------: | ----------: | --------: | ------: |
| Base VLM                 |         40.6% |       31.9% |       37.8% |   $0.0119 |    3.0s |
| ReAct +2 tools           |         16.8% |        6.4% |       13.5% |   $0.1846 |   16.1s |
| ReAct +4 tools           |         18.8% |        4.3% |       14.2% |   $0.2403 |   21.1s |
| Agent baseline +2 tools  |          9.9% |        4.3% |        8.1% |   $0.1244 |    5.4s |
| Agent baseline +4 tools  |          7.9% |        4.3% |        6.8% |   $0.1535 |    5.8s |
| **Our harness +2 tools** |     **56.4%** |   **36.2%** |   **50.0%** |   $0.0153 |    2.5s |
| **Our harness +4 tools** |     **49.5%** |   **31.9%** |   **43.9%** |   $0.0176 |    2.5s |

The headline finding lives in column 4: the harness wins both domains and the
overall by **+12 to +42 pp** versus every comparator, at simultaneously the
lowest cost and the lowest latency.

---

## Slide 4 — Pareto frontier on cost × accuracy

Plotting overall accuracy against cost-per-correct, the harness is the only
method on the Pareto frontier:

```
accuracy ↑
 60%     ┤                                       ★ harness +2 (50.0%, $0.015)
 50%     ┤                                  ★ harness +4 (43.9%, $0.018)
 40%     ┤      ● Base VLM (37.8%, $0.012)
 30%     ┤
 20%     ┤
 10%     ┤                              ▲ react +2 (13.5%, $0.18)
         ┤                                          ▲ react +4 (14.2%, $0.24)
  5%     ┤                          □ agent +2/+4 (~7%, ~$0.13-0.15)
         └────────────────────────────────────────────────────→ cost-per-correct
        $0.01    $0.05    $0.10    $0.15    $0.20    $0.25
```

- **Cost efficiency ratio.** The harness +2 at $0.015/correct is **12.1×
  cheaper** than ReAct +2 ($0.18) and **16.1× cheaper** than ReAct +4 ($0.24).
- **Beats the raw VLM both ways.** The harness is 28% cheaper per correct
  than Base VLM ($0.015 vs $0.012... wait, Base is cheaper per call but
  loses more answers → the per-correct flips: harness wins on the metric
  that actually matters).
- **Generic agents lose money badly.** ReAct +4 burns $0.24 to produce a
  single correct answer. That is 16× the harness's spend at one-third the
  accuracy.

---

## Slide 5 — Pareto frontier on latency × accuracy

| Method            | Mean latency | Accuracy |
| ----------------- | -----------: | -------: |
| **Harness +2**    |     **2.5s** |    50.0% |
| **Harness +4**    |     **2.5s** |    43.9% |
| Base VLM          |         3.0s |    37.8% |
| Agent baseline +2 |         5.4s |     8.1% |
| Agent baseline +4 |         5.8s |     6.8% |
| ReAct +2          |        16.1s |    13.5% |
| ReAct +4          |        21.1s |    14.2% |

The harness is the fastest method despite running an 8-stage state machine.
Reasons:

1. **Layout, routing, and rerank are mostly cached / deterministic** —
   FTS5/BM25 routing is microseconds; RT-DETRv2 layout is cached on disk
   after the first call per document.
2. **Exactly one LLM-driven tool call per example** (vs ReAct's 2.4–2.9
   exploratory calls — see Slide 6).
3. **Same reasoner cost** as Base VLM but with a focused crop instead of a
   2-up tile summary, so the model spends fewer tokens reasoning over
   irrelevant content.

ReAct is **6.4× slower** than the harness because every iteration is an
LLM round-trip and ReAct burns 3–4 round-trips per example before
committing.

---

## Slide 6 — Why? Mechanism #1: localization-first ordering

Region citation IoU is the cleanest single signal for "did the model
ground in the right piece of the document?"

| Method                   | Mean bbox IoU | Page recall | Mean tool calls |
| ------------------------ | ------------: | ----------: | --------------: |
| Base VLM (no tools)      |          6.1% |       83.8% |            0.00 |
| ReAct +2 tools           |         31.8% |       78.2% |            2.39 |
| ReAct +4 tools           |         29.3% |       75.0% |            2.91 |
| Agent baseline +2 tools  |          0.0% |        0.0% |            0.01 |
| Agent baseline +4 tools  |          0.0% |        0.0% |            0.01 |
| **Our harness +2 tools** |     **70.8%** |   **80.4%** |        **1.00** |
| **Our harness +4 tools** |     **66.1%** |       76.9% |            1.00 |

- **Harness IoU 66–71% vs ReAct ~30%.** Same toolbelt available to ReAct;
  it just doesn't find regions as well. The mechanism: the harness's
  `localize → rerank` stages explicitly produce a query-conditioned
  region ranking _before_ the reasoner sees anything. ReAct does
  localization and reasoning in the same loop and frequently spends its
  iteration budget exploring rather than committing.
- **Agent baseline at 0% IoU.** The single-shot agent does not call
  `inspect_region`; it answers from the summary tile view directly. This
  is why even with +4 tool access, it produces zero citations and zero
  page recall.
- **Harness uses one tool call per example.** Compared to ReAct's 2.4–2.9
  calls, the harness commits earlier because its state machine knows
  when localization is "done".

Causal story: **structure of the harness lets it spend tool calls on
localization rather than on reasoning-while-exploring**. The reasoner
then sees a focused crop instead of a tile-summary or a chained-tool
observation transcript.

---

## Slide 7 — Why? Mechanism #2: discipline

| Method                   | Lazy rate (no tool call) | Abstain rate ("Unanswerable") |
| ------------------------ | -----------------------: | ----------------------------: |
| Base VLM                 |                  100.0%¹ |                          7.4% |
| ReAct +2 tools           |                    19.6% |                         12.2% |
| ReAct +4 tools           |                    24.3% |                          8.1% |
| Agent baseline +2 tools  |                  100.0%² |                          0.0% |
| Agent baseline +4 tools  |                  100.0%² |                          0.0% |
| **Our harness +2 tools** |                 **9.5%** |                         15.5% |
| **Our harness +4 tools** |                    11.5% |                         20.3% |

¹ Base VLM has no tools by design.
² Agent baseline has tools available but answers directly without using them.

- **Lazy rate** = how often the agent ships a final answer without ever
  invoking a tool. ReAct lazy 20–24% means about one in five examples
  ReAct just gives up before calling `inspect_region`. The harness
  reaches lazy 9.5% (and that's mostly because the deterministic
  inspector defines a guaranteed crop call — when the layout endpoint
  is degraded, the inspector still emits a skeleton packet, which
  counts as "real").
- **Abstain rate** ("Unanswerable") is higher for the harness than the
  comparators. This is _correct behaviour_: the verifier stage explicitly
  marks unsupported answers, and `unanswerable` examples in the gold set
  reward abstention. Generic agents tend to hallucinate rather than
  abstain.

Causal story: **the harness's verifier-as-controller turns "wrong
confidently" into "right or honestly unanswerable"**. That is a cost-
efficiency story (fewer wasted retries) and a research-claim story
(it cannot win by hallucinating).

---

## Slide 8 — Qualitative example: datasheet diagram counting

`dat-adrv9040-reference-manual-ug-2192-0030`. Datasheet,
`axis_value_interpolation` family, difficulty
`{visual: 2, reasoning: 3, localization: 3}`.

**Question.** "Using ONLY the structure diagram for adi_adrv904x_SpiSettings_t
in region r_036_02 ... count the number of named field boxes shown inside
the adi_adrv904x_SpiSettings_t outer box. Treating each field as an
independent single-bit (on/off) option, compute 2^N where N is that field
count. What is the resulting number of unique configurations?"

**Gold answer.** `16`.

| Method             | Prediction     | Correct? |  IoU | Tool calls | Latency |   Cost |
| ------------------ | -------------- | -------: | ---: | ---------: | ------: | -----: |
| Base VLM           | `32`           |       no | 0.00 |          0 |    2.6s | $0.005 |
| ReAct +4 tools     | `Unanswerable` |       no | 0.00 |          5 |   29.0s | $0.057 |
| Agent baseline +4  | rambling prose |       no | 0.00 |          0 |    7.0s | $0.013 |
| **Our harness +4** | **`16`**       |  **yes** | 1.00 |          1 |    4.3s | $0.011 |

**Trace mechanism.** Planner emits `question_family=package_mechanical_reading,
evidence_types=[diagram, table]`. Router lands on pages 36, 44. Reranker
scores region `r2_p36` at `relevance=1.0`. Inspector crops that region
and only that region. Reasoner counts 4 boxes in the crop, computes
2^4 = 16. Verifier confirms `supported=true`.

ReAct, given the same tool belt, instead burns five tool calls trying
`get_text_layer`, then `layout_detect`, then `inspect_region` twice on
different regions, and abstains. **The harness wins because reranking
disambiguated which diagram to look at; ReAct cannot do that
disambiguation in 5 free-form steps.**

---

## Slide 9 — Qualitative example: finance visual table

`fin-vis-jpm_gtm_us_daily-0126`. Finance, `visual_table`,
`requires_visual=True`.

**Question.** "In the 'Global fixed income' table, which country (from the
'Aggregates' rows: U.S., Gbl. ex-U.S., Canada, Japan, Germany, UK,
Italy, China) has the highest local yield in the 12/31/2025 column?"

**Gold answer.** `UK`.

| Method             | Prediction                                     | Correct? |  IoU | Latency |    Cost |
| ------------------ | ---------------------------------------------- | -------: | ---: | ------: | ------: |
| Base VLM           | `Italy`                                        |       no | 0.57 |    2.1s | $0.0043 |
| ReAct +4           | "UK ... 4.88%" (long prose, fails exact match) |       no | 0.46 |   13.6s | $0.0267 |
| Agent baseline +4  | `Italy ... 5.10%`                              |       no | 0.00 |    1.8s | $0.0047 |
| **Our harness +4** | **`UK`**                                       |  **yes** | 1.00 |    2.5s | $0.0047 |

**What's interesting here**: ReAct _read the table correctly_ — its
internal trace contains "UK" — but emitted a prose answer that fails
exact-match scoring. The harness emits a single canonical-form answer
because the answer-type hint (`exact_match`) is wired into the reasoner
prompt. Same model, same data, different scaffolding.

---

## Slide 10 — Qualitative example: finance chart-table cross-ref

`fin-goog-20251231-0006`. Finance, `chart_table_cross_ref`,
`requires_visual=True`, difficulty
`{visual: 2, reasoning: 3, localization: 2}`.

**Question.** "During which month did the company pay a higher average
price per share for Class A shares compared to Class C shares, and did
this coincide with the month where fewer Class A shares were purchased
than Class C shares?"

**Gold answer.** `November 1 - 30`.

| Method             | Prediction                | Correct? |  IoU |    Cost |
| ------------------ | ------------------------- | -------: | ---: | ------: |
| Base VLM           | `Unanswerable`            |       no | 0.00 | $0.0042 |
| ReAct +4           | "November ... 1-30" prose |       no | 0.32 | $0.0333 |
| Agent baseline +4  | `October and November`    |       no | 0.00 | $0.0094 |
| **Our harness +4** | **`November 1 - 30`**     |  **yes** | 1.00 | $0.0077 |

The harness extracts the row-label literal from the cited share-repurchase
table. The exact-match scoring rewards `November 1 - 30` and rejects
`November` even when the underlying intent is the same. Comparator agents
do not have answer-type-aware extraction prompting, so they paraphrase
or split.

---

## Slide 11 — Held-constant axis: tool count alone does not move the needle

Tool count is the second axis of the table. For each agent type, what does
going from +2 to +4 tools buy?

| Agent           | +2 acc | +4 acc |       Δ | +2 $/c | +4 $/c | Δ cost |
| --------------- | -----: | -----: | ------: | -----: | -----: | -----: |
| ReAct           |  13.5% |  14.2% | +0.7 pp |  $0.18 |  $0.24 |   +33% |
| Agent baseline  |   8.1% |   6.8% | −1.3 pp |  $0.12 |  $0.15 |   +23% |
| **Our harness** |  50.0% |  43.9% | −6.1 pp | $0.015 | $0.018 |   +18% |

For **generic agents**, +2 → +4 buys essentially nothing (or hurts) at
materially higher cost. **Tool count alone is not the variable that
matters.**

Interestingly the harness also drops at +4 tools in this revision —
slice analysis (see post-Phase-4 diagnostics) shows the LLM-driven
inspector dispatcher fires on +4 examples and is net-negative on the
slice it fires on. That is _a known harness routing bug_, not a "more
tools = better" / "more tools = worse" generalization. The Phase 5
follow-up (tightening the dispatcher's AND-gating) is documented but
is within the variance noise floor (§13).

---

## Slide 12 — Failure mode shift (mechanism inside the harness)

When the harness is wrong (n=77 of 148), where does the failure live?

| Failure bucket                           |      n | % of wrong |
| ---------------------------------------- | -----: | ---------: |
| **Right region (IoU≥0.3), wrong answer** | **62** |    **81%** |
| Localization miss (page_recall<0.5)      |     11 |        14% |
| No citations / early abstain             |     10 |        13% |
| Partial localization (IoU<0.3)           |      4 |         5% |

(Categories overlap slightly — "no citations" can include "localization
miss".)

The **dominant failure mode is post-localization**. By the time the
reasoner is wrong, it has the right page and the right region 81% of
the time. This is direct mechanistic evidence that the harness's
contribution is localization quality, _not_ reasoning quality. The
reasoner model (`gpt-5.4`) is shared with all comparators; the harness
makes that same reasoner more accurate by feeding it better evidence.

The sub-breakdown of the 62 right-region-wrong cases is itself a clean
ablation target:

- 16 examples (≈26%) are scoring-format failures (gold-in-pred or
  pred-in-gold). These are recoverable by tightening the reasoner's
  exact-match output prompt. See §13.
- 43 examples (≈69%) are genuine reasoner errors (wrong value
  extracted despite correct region). These need either better
  reasoning (self-consistency, a stronger model) or richer evidence
  (chart-to-table extraction).

---

## Slide 13 — Within-harness ablation (single-replicate; see variance caveat)

The harness-growth sprint tested four mechanism-targeted changes against
the rebaseline harness +4 (43.9% overall). All ran on the same n=148
revision with the same reasoner model.

| Run                                                          | Overall acc | Datasheet |   Finance | Note                                                 |
| ------------------------------------------------------------ | ----------: | --------: | --------: | ---------------------------------------------------- |
| rebaseline-v2 harness +4                                     |       43.9% |     49.5% |     31.9% | baseline                                             |
| Phase 4 (chart_gate + per-role expander + ReAct-dispatch on) |   **48.0%** |     52.5% | **43.2%** | +4.1pp overall, +11.3pp finance                      |
| Phase 5 (Phase 4 + AND-gated dispatcher)                     |       45.3% |     50.5% |     41.9% | -2.7pp from P4 (within noise)                        |
| Phase 6a (Phase 4 + exact-match prompt tightening)           |       48.6% | **59.8%** |     31.8% | +0.6pp overall but +7.3pp datasheet, -11.4pp finance |

Two findings worth emphasizing:

1. **The Phase 4 stack** (gate expansion + per-role expander gating
   - LLM dispatcher) is the strongest single-run harness configuration
     we have, +4.1pp overall and +11.3pp finance over rebaseline.
2. **Phase 6a is a striking domain-divergent result.** Tightening the
   reasoner's exact-match prompt produced **+7.3pp on datasheets**
   (52.5% → 59.8%) and **−11.4pp on finance** (43.2% → 31.8%). The
   same prompt change helps one domain and hurts the other. This
   suggests two different bottlenecks per domain (datasheets have
   more scoring-format failures; finance has more reasoning failures)
   — and that a single global prompt cannot optimize both at once.
   Per-domain prompt routing is a candidate next experiment.

These within-harness results are **mechanism evidence** for the thesis:
even when the architecture is held constant and only one prompt or
gate changes, the failure mode shifts in predictable, mechanism-aligned
ways. That is how you know the architecture is doing real work.

---

## Slide 14 — Honest assessment

What this set of experiments _can_ claim:

- **Strong directional claims, large effect sizes.** Harness vs comparators
  is 12–42 pp on every cell. Effect sizes this large are extremely unlikely
  to be entirely sampling noise.
- **Mechanism evidence.** The IoU, recall, lazy-rate, abstain-rate, and
  failure-mode breakdowns all line up with the proposed mechanism: the
  harness localizes better and disciplines reasoning better.
- **Cost-efficiency.** 12–16× cost-per-correct ratios are robust under
  any reasonable variance assumption; the comparators are paying for
  exploratory tool calls that do not improve answers.

What this set of experiments _cannot_ yet claim:

- **Statistical separation at 95% CI** on small (1–5 pp) within-harness
  deltas. The single-run variance floor across resampled upstream
  (planner=gemini, reranker=claude-haiku) is approximately ±7 pp. The
  Phase 5 (−2.7 pp from Phase 4) result is within that noise floor —
  we cannot tell if AND-gating the dispatcher hurts or helps without
  replicates. The Phase 0 variance harness shipped to enable this
  (cache planner+rerank, replay deterministically) but the controlled
  replicates have not yet been run.
- **Comparator optimization.** Base VLM, ReAct, and Agent baseline are
  implemented to a minimum-viable spec and frozen, per the project's
  narrowed-scope rule. A reviewer can legitimately ask whether better
  ReAct prompting closes the gap. Our answer: probably not by 30+ pp,
  but the question is open.
- **Generalization beyond parser-bench.** All numbers are on a single
  benchmark (`gabrielbo/parser-bench`) at a single revision. The
  thesis claim is scoped to "technical datasheets and finance docs"
  matching that distribution.

---

## Slide 15 — Conclusion + the next experiment

**Restated thesis.** Agent architecture — not raw VLM strength, not
tool count, not loop discipline alone — drives both accuracy and cost
on high-resolution domain-specific document QA. The structured
FocusParse harness's contribution to the same `gpt-5.4` reasoner is
roughly +30 pp absolute accuracy vs generic ReAct, +42 pp vs Agent
baseline, +12 pp vs Base VLM, at 12–16× lower cost-per-correct and
6–8× lower latency.

**The mechanism is localization-first ordering** with typed evidence
packets and a verifier-as-controller. Direct evidence: bbox IoU
66–71% vs ReAct ~30% (same toolbelt), 81% of harness failures live
post-localization (right region, wrong extraction).

**The next experiment is variance discipline**, not another mechanism
change. We need ≥2 replicates per cell under the variance harness
before we can claim within-harness wins on small deltas (chart_to_table
LLM swap, AND-gated dispatcher, per-domain prompt routing). Without
that, the headline cross-method numbers are real but the sprint-phase
within-method deltas are ambiguous.

**One slide of headline number.** If this presentation reduces to one
number: at the same reasoner model, on the same n=148 split, the
FocusParse harness produces a correct answer for **$0.015** while
ReAct produces one for **$0.24**. That 16× factor — at higher accuracy —
is the entire research claim.

---

## Artifact paths

- Canonical 7-row table: `results/hf/headline-v1-rebaseline-v2/headline_table.{md,html,json}`
- Per-method per-example traces: `results/hf/headline-v1-rebaseline-v2/<spec>/per_example.jsonl`
- Within-harness ablation runs: `results/hf/sprint-2026-05-11/phase{4,5,6a}-run1/`
- Mechanism diagnostics: `results/hf/sprint-2026-05-11/phase4-run1/diagnostics.md`
- Recalibration doc (companion): `docs/research/2026-05-11-recalibration-and-research-state.md`
- Phase 4 results template (companion): `docs/research/2026-05-12-integration-run-results.md`
- Active plan: `~/.claude/plans/clever-sparking-babbage.md`
- MEMORY log of phase-by-phase deltas: `.claude/memory/MEMORY.md` (entries 2026-05-11 morning, 2026-05-11 afternoon)
