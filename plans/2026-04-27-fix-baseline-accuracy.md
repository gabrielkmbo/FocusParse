# Fix Baseline Accuracy — Diagnose and Repair the 0% Wall

## Overview

The 6-protocol matrix run on `Arm_EE382N_4` (7 examples) produced **0.0% accuracy across every protocol**, with `bbox_iou=0.00` and `page_recall ≤ 0.29`. Parser-bench's published numbers for the same baseline class (single-shot VLM) are **GPT-5.4 full_doc 48.6% / oracle_crop 59.4%**. The 50pp gap is the bug, not the model.

This plan fixes a stack of independently-introduced defects in the scoring + harness layer that masks real model output behind broken pattern checks. After Phase 1 alone the cached predictions re-score from 0.0% → **28.6% (full_doc) / 42.9% (oracle_page) / 57.1% (tiled_4up)** without re-running the model.

## Current State Analysis

### Diagnosis 1 (CRITICAL) — `score_answer` answer-type checks never match

`src/focusparse/eval/scoring.py:31-44` routes scoring by:

```python
if answer_type.endswith("unanswerable"): ...
if answer_type.endswith("boolean"): ...
if answer_type.endswith("multiple_choice"): ...
if answer_type.endswith("numeric"): ...
return 1.0 if pred.casefold() == gold.casefold() else 0.0  # fall-through
```

`example.answer_type` is the parser-bench `AnswerType` enum (`third_party/parser-bench/src/utils/schema.py:20`). Its `__str__` returns `"AnswerType.NUMERIC"` (uppercase enum-name form), not `"numeric"`. So **every branch is dead code** — every example falls through to strict casefold exact-match.

Verified empirically (`tests/test_scoring.py` would have caught this if it covered enum-typed inputs):

```
dat-Arm_EE382N_4-0001  type=AnswerType.NUMERIC      branches_fired=[]  → falls_through=yes
dat-Arm_EE382N_4-0024  type=AnswerType.EXACT_MATCH  branches_fired=[]  → falls_through=yes
... (all 7 examples fall through)
```

### Diagnosis 2 (CRITICAL) — numeric tolerance is RELATIVE, parser-bench is ABSOLUTE

`src/focusparse/eval/scoring.py:64-72` uses:

```python
return 1.0 if abs(p - g) / max(abs(g), 1e-9) <= tol else 0.0
```

Parser-bench (`third_party/parser-bench/src/eval/scoring.py:56-62`) uses:

```python
if tolerance is not None:
    return abs(pred_val - gold_val) <= tolerance  # absolute
```

Example: gold=`40%`, pred=`50%`, `tolerance=10.0`. Parser-bench: `|50-40|=10 ≤ 10` → correct. FocusParse: `|50-40|/40=0.25 ≤ 10.0` → correct (only because tol is huge). For gold=`1.0`, pred=`1.1`, `tolerance=0.1`: parser-bench `|0.1| ≤ 0.1` → correct; FocusParse `0.1/1.0=0.1 ≤ 0.1` → also correct here. The semantics differ; with realistic tolerances they disagree.

### Diagnosis 3 (HIGH) — simple agent emits page=1, gold is page=50

`SimpleBaselineAgent.run` (`src/focusparse/pipeline/workflow.py:856-897`) shows the model 1–N images and asks for citations with `page` keys. The prompt does not say what page numbers correspond to which image. The model defaults to 1-indexed positional ("page": 1 for the first image).

The HF validation split stages **only the gold supporting pages** (e.g. `Arm_EE382N_4_page_0050_300dpi.png` is the only image staged for example 0001). So:

- Predicted: `page=1, bbox=[0.0, 0.081, 0.256, 0.997]`
- Gold: `page=50, bbox=[1649, 531, 2842, 1478]` (pixel-space)
- `_bbox_iou` returns 0 immediately (page mismatch); `page_recall` = 0%.

For `tiled_*` protocols, the model sees a contact sheet — even less able to know source pages.

The harness has a working solution for the focus pipeline: `_images_by_page` (`harness.py:361`) parses `_page_NNNN_` from filenames into a real-page map. The simple agent path doesn't use it.

### Diagnosis 4 (HIGH) — simple-agent IoU compared in wrong coord space

`run_simple_eval` calls `_score_and_record(example, result, protocol=protocol)` (`harness.py:110`) without `image_dims_by_page`. Predicted bboxes are normalized [0,1] (the prompt asks for that). Gold bboxes are pixel-space (parser-bench convention). Without the dim map, `_to_unit_interval_bbox` returns the gold unchanged (`max_coord > 1` but `image_dims_by_page is None` → no-op fallback). Result: every IoU is 0 even when the model would have cited the right region.

`run_focus_eval` does the right thing (`harness.py:234-237`). The simple path was missed.

### Diagnosis 5 (MEDIUM) — exact_match is strict casefold; model emits long sentences

Even if Diagnoses 1–4 are fixed, exact_match scoring (`scoring.py:44`) is `pred.casefold() == gold.casefold()`. Real model outputs:

```
gold="0x44"
pred="On a little-endian ARM architecture, after `STR r0, [r1]` with r0=0x11223344, ... r2=0x44."
```

The pred CONTAINS the gold but exact-match fails. Parser-bench's scorer (`third_party/parser-bench/src/eval/scoring.py:178`) is also strict, so this is partially intentional. But because the model is given no answer-format hint (Diagnosis 6), it always emits prose — the system is unfair to itself. Either tighten the prompt or relax scoring (substring containment with normalization), but pick one.

### Diagnosis 6 (MEDIUM) — simple agent prompt is too generic

`_SIMPLE_SYSTEM_PROMPT` (`workflow.py:832-839`) does not mention:

- Domain (datasheet vs finance vs schematic)
- Question family (axis_value_interpolation, confusable_label, ...)
- Answer format ("be brief / numeric / exact label")
- Source page numbers (Diagnosis 3 also covers this)

Parser-bench's baseline runner (`third_party/parser-bench/src/eval/runner.py`) presumably includes more guidance — should mirror it for fair comparison.

### Cached re-score validates Diagnoses 1+2

A bug-fixed scorer applied to the **already-cached** Phase A matrix predictions (no model re-runs) yields:

```
full_doc      0.0% → 28.6%
oracle_page   0.0% → 42.9%
oracle_crop   0.0% → 28.6%
tiled_2up     0.0% → 28.6%
tiled_4up     0.0% → 57.1%
tiled_8up     0.0% → 42.9%
```

Closing most of the 50pp gap to parser-bench's published numbers without touching the model. The residual 20pp gap is what Diagnoses 3–6 are after.

## Desired End State

`uv run python scripts/run_hf_matrix.py --phase a --limit 7 --staging-dir ~/.cache/focusparse/hf_staging --pdfs-root ~/.cache/focusparse/pdfs` reports per-protocol accuracies **within ±5pp of a re-implemented parser-bench scorer applied to the same predictions**. Stretch: simple-baseline accuracy on a 30-example slice is within ±5pp of parser-bench's published GPT-5.4 numbers (full_doc 48.6%, oracle_crop 59.4%).

`tests/test_scoring.py` has explicit cases pinning enum-typed `AnswerType` and parser-bench's absolute-tolerance semantics — the original bug cannot regress.

`tests/test_harness.py` covers the simple-agent page-mapping path so a future change can't silently re-introduce page=1 collapse.

## What We're NOT Doing

- **Not modifying parser-bench**. All fixes land in FocusParse code.
- **Not improving the focus pipeline's accuracy** in this plan — the focus stack has its own optimization path (Phase 3+ items in `plans/2026-04-27-phase2-sota-leverage.md`). This plan only fixes the **measurement layer** so those optimizations have a real signal to hill-climb.
- **Not changing the model or tier defaults**. The reasoner stays GPT-5.4 frontier.
- **Not relaxing scoring beyond what parser-bench does**. Substring containment for `exact_match` is the most we'd consider, and only if parser-bench's own scorer does it.
- **Not tackling cross-document validation** here — single-doc smoke (Arm) is the gate; broader runs are a follow-up.

## Implementation Approach

Land each Diagnosis as its own commit so we can A/B per fix and revert one without unwinding the rest. Phase ordering reflects impact: Phase 1 alone recovers 30+pp, Phase 2 recovers another 5–10pp, Phase 3 catches the long-tail.

Cached predictions are gold for diff-testing: the re-scoring path means Phase 1 can be validated **without re-running the model**, so changes are cheap to verify.

---

## Phase 1: Fix scoring routing + tolerance semantics

### Overview

Repair `score_answer` so the four `answer_type` branches actually fire, and switch numeric tolerance to absolute (parser-bench parity). This alone moves the matrix from 0% to ~30–60% per protocol on the existing predictions.

### Changes Required:

#### 1. `score_answer` enum normalization

**File**: `src/focusparse/eval/scoring.py`
**Changes**: Replace string-suffix checks with a normalized lower-case stem extracted from either an enum value or a string. Handles `"AnswerType.NUMERIC"`, `"numeric"`, and `AnswerType.NUMERIC` (passed as enum).

```python
def _answer_type_stem(answer_type: object) -> str:
    """Normalize answer_type to a lowercase stem regardless of enum vs string repr."""
    s = str(answer_type)
    return s.split(".")[-1].lower() if "." in s else s.lower()


def score_answer(prediction_text: str, example: BenchmarkExample) -> float:
    gold = (example.answer or "").strip()
    pred = (prediction_text or "").strip()
    stem = _answer_type_stem(example.answer_type)

    if stem == "unanswerable":
        return 1.0 if _is_abstention(pred) else 0.0
    if stem == "boolean":
        return 1.0 if _normalize_bool(pred) == _normalize_bool(gold) else 0.0
    if stem == "multiple_choice":
        return 1.0 if pred.upper()[:1] == gold.upper()[:1] else 0.0
    if stem == "numeric":
        return _score_numeric(pred, gold, example.tolerance)
    return 1.0 if pred.casefold() == gold.casefold() else 0.0
```

#### 2. Switch `_score_numeric` to absolute tolerance (parser-bench parity)

**File**: `src/focusparse/eval/scoring.py`

```python
def _score_numeric(pred: str, gold: str, tolerance: float | None) -> float:
    p = _extract_float(pred)
    g = _extract_float(gold)
    if p is None or g is None:
        return 0.0
    # parser-bench convention: tolerance is ABSOLUTE; default to 1% relative
    # only when no tolerance is provided.
    if tolerance is not None:
        return 1.0 if abs(p - g) <= tolerance else 0.0
    return 1.0 if abs(p - g) <= max(abs(g) * 0.01, 1e-9) else 0.0
```

Update the inline docstring to match.

#### 3. Test coverage to pin both behaviors

**File**: `tests/test_scoring.py`

Add cases:

- `score_answer` with `AnswerType.NUMERIC` enum _and_ with literal string `"AnswerType.NUMERIC"` both route to numeric.
- `score_answer` with `AnswerType.UNANSWERABLE`, `AnswerType.BOOLEAN`, `AnswerType.MULTIPLE_CHOICE` route correctly.
- `_score_numeric` with absolute tolerance: `(pred="50%", gold="40%", tol=10.0)` → `1.0`; `(pred="55%", gold="40%", tol=10.0)` → `0.0`.
- `_score_numeric` with `tolerance=None` falls back to 1% relative.
- Float-precision edge: `(pred="1.1", gold="1.0", tol=0.1)` → `1.0` (use `<=` and a `1e-9` epsilon if needed).

#### 4. (Optional) Re-score helper for cached predictions

**File**: `scripts/rescore_predictions.py` (new)

Reads a `results/hf/.../run.json` + its `predictions/`, re-applies `score_answer` against the staged benchmark, writes a new `run.json` with updated `accuracy` / `evidence_reward` fields. Lets us verify Phase 1 against the existing matrix without burning API credit. Tiny script (~80 lines).

### Success Criteria:

#### Automated Verification:

- [ ] `uv run pytest tests/test_scoring.py -v` passes the new cases
- [ ] `uv run pytest` full suite stays green (current 395 + new tests)
- [ ] `uv run ruff check src/ tests/` clean
- [ ] `uv run python scripts/rescore_predictions.py results/hf/single-doc-arm/focusparse_simple_tiled_4up_7d4b816d.json` reports accuracy ≥ 50% (was 0%)

#### Manual Verification:

- [ ] Re-scored matrix table shows full_doc ≥ 25%, oracle_page ≥ 35%, tiled_4up ≥ 50% on `Arm_EE382N_4` (7 examples)
- [ ] No protocol regresses below its old 0% (sanity: at worst we tied)

---

## Phase 2: Fix simple-agent page mapping + IoU coord space

### Overview

Make the simple agent's citations point to source page numbers, not positional indices. Wire `image_dims_by_page` into `_score_and_record` for the simple path so predicted-normalized vs gold-pixel IoU comparison works. Recovers `page_recall` and `bbox_iou` for protocols where the model emitted a usable bbox.

### Changes Required:

#### 1. Tell the simple agent which page each image is

**File**: `src/focusparse/pipeline/workflow.py`

Two parts:

(a) **System prompt update** — replace the static prompt with a builder that enumerates page numbers:

```python
def _build_simple_user_prompt(example: BenchmarkExample, image_pages: list[int]) -> str:
    lines = [f"Question: {example.question}"]
    if image_pages:
        listing = ", ".join(f"image {i+1} = page {p}" for i, p in enumerate(image_pages))
        lines.append(f"Images correspond to: {listing}")
    return "\n".join(lines)
```

(b) **Pass image_pages to the agent** — `SimpleBaselineAgent.run` accepts `image_pages: list[int] | None = None`; when provided, builds the enriched prompt and instructs the model to cite page numbers from that list.

The harness derives `image_pages` from `_images_by_page` already used on the focus path:

```python
# in run_simple_eval, after _prepare_images:
image_pages = _ordered_pages_for_images(example, images, protocol)
result = await agent.run(example, images, image_pages=image_pages)
```

For tiled protocols where multiple source pages are composed into one tile image, pass the list of constituent pages — the model can still cite "page 50" by understanding the tile is made of pages [50, 12, 7, ...].

#### 2. Fall-back remap when model still emits 1-indexed citations

**File**: `src/focusparse/eval/harness.py::_score_and_record`

When the model emits `page=1` and only one image was shown (e.g. `oracle_crop`), and the gold-supporting page is single, remap `page=1 → gold supporting page`. This is a safety net, not the primary fix — Phase 2.1 should make this unnecessary in practice.

```python
def _remap_positional_pages(
    citations: list[dict],
    image_pages: list[int],
) -> list[dict]:
    """If a citation page is 1-indexed positional (1..len(image_pages)),
    remap to the source page. Idempotent for already-source-numbered citations."""
    if not image_pages:
        return citations
    out = []
    for c in citations:
        p = c.get("page")
        if isinstance(p, int) and 1 <= p <= len(image_pages):
            # Heuristic: if p matches an entry in image_pages, leave alone;
            # else assume positional.
            if p not in image_pages:
                c = {**c, "page": image_pages[p - 1]}
        out.append(c)
    return out
```

Apply in `_score_and_record` before extracting `predicted_pages`.

#### 3. Wire `image_dims_by_page` into the simple path

**File**: `src/focusparse/eval/harness.py::run_simple_eval`

Mirror what `run_focus_eval` does:

```python
# before _score_and_record:
image_dims = _image_dims_by_page(example, images)
record = _score_and_record(
    example, result, protocol=protocol, image_dims_by_page=image_dims
)
```

For tiled protocols, `image_dims_by_page` is empty (the composed PNG isn't named `_page_NNNN_`). That's fine — `bbox_iou` falls back to raw-coord (giving 0 unless the model happens to cite in pixel space). Tiled protocols are localization-poor by design.

#### 4. Tests

**File**: `tests/test_workflow.py`

- `SimpleBaselineAgent.run` with `image_pages=[50]` → emitted prompt includes "image 1 = page 50".
- `SimpleBaselineAgent.run` without `image_pages` (legacy callers) → emitted prompt unchanged.

**File**: `tests/test_harness.py`

- `_score_and_record` with simple-agent citation `page=1`, `image_pages=[50]` → `predicted_pages == [50]`; `page_recall=1.0` against gold `[50]`.
- `_score_and_record` with simple-agent citation `page=50`, `image_pages=[50]` → unchanged (no double-remap).

### Success Criteria:

#### Automated Verification:

- [ ] `uv run pytest tests/test_workflow.py tests/test_harness.py -v` passes the new cases
- [ ] `uv run pytest` full suite green
- [ ] On the cached Arm matrix (no re-run), `page_recall` for `oracle_page` jumps from 0.29 → ≥ 0.85 after the remap pass

#### Manual Verification:

- [ ] Re-run `--protocol oracle_page --limit 7` after Phase 2 → `page_recall ≥ 0.85` (gold pages cited)
- [ ] `bbox_iou` non-zero on at least one `oracle_page` example (proves coord-space fix)

---

## Phase 3: Tighten the simple agent prompt for answer format

### Overview

The simple agent's prompt is generic enough that the model returns prose for numeric questions and verbose explanations for label questions. This converts answers that the strict scorer would otherwise reject. Add `answer_type` and `question_family` hints inline.

### Changes Required:

#### 1. Type-aware answer-format hint

**File**: `src/focusparse/pipeline/workflow.py`

Extend `_build_simple_user_prompt`:

```python
def _format_hint(answer_type: object) -> str:
    stem = _answer_type_stem(answer_type)
    if stem == "numeric":
        return ("Answer with a single number. If the question asks for a percentage, "
                "include the % sign. Do not include explanations.")
    if stem == "exact_match":
        return ("Answer with the exact label, identifier, or short phrase from the document. "
                "Do not paraphrase or add context.")
    if stem == "boolean":
        return "Answer 'yes' or 'no'."
    if stem == "multiple_choice":
        return "Answer with the letter of the correct choice (A, B, C, ...)."
    if stem == "unanswerable":
        return "If the document does not contain the answer, reply 'Unanswerable'."
    return ""
```

Compose into the user prompt only — system prompt stays JSON-format-only so the response shape doesn't drift.

#### 2. (Optional) `question_family` priming

If `example.question_family` is populated, append a one-line hint:

- `axis_value_interpolation` → "Read the axis carefully and interpolate if needed."
- `confusable_label` → "Distinguish similar-looking labels (e.g. O vs 0, l vs 1)."
- `cross_page_continuation` → "The answer may span multiple pages."

Skip for question_families we don't recognize. This is small but cheap to gate behind a flag.

#### 3. Tests

**File**: `tests/test_workflow.py`

- Numeric example → user prompt contains "single number".
- Exact-match example → user prompt contains "exact label".
- Boolean example → contains "yes' or 'no'".

### Success Criteria:

#### Automated Verification:

- [ ] `uv run pytest tests/test_workflow.py -v` passes
- [ ] `uv run pytest` full suite green

#### Manual Verification:

- [ ] Re-run `--protocol tiled_4up --limit 7` after Phase 3 → numeric answers come back as bare numbers (e.g. "70%" not "About 70% of the way down...")
- [ ] Aggregate accuracy on the 7-example smoke ≥ 50% on at least one protocol

---

## Phase 4 (gated): Soften `exact_match` if parser-bench parity allows

### Overview

If parser-bench's scorer applies any form of containment / normalization for `exact_match` and we're not, mirror it. If parser-bench is also strict-casefold, **skip this phase** — diverging hurts reproducibility more than it helps the score.

This phase is **gated on a code read of `third_party/parser-bench/src/eval/scoring.py`** at implementation time. Do not implement speculatively.

### Changes (conditional):

#### 1. Verify parser-bench's exact_match logic

Read `third_party/parser-bench/src/eval/scoring.py:178` and surrounding code. Document the exact normalization (lowercase? strip punctuation? substring? casefold?).

#### 2. Mirror in FocusParse

Add the same normalization to `score_answer`'s exact_match fall-through. Add tests pinning behavior.

### Success Criteria:

#### Automated Verification:

- [ ] If implemented: `score_answer` agrees with parser-bench's scorer on a 100-example diff suite (golden test).
- [ ] If skipped: a comment in `scoring.py` documents that parity is intentional ("parser-bench uses strict casefold; do not soften").

#### Manual Verification:

- [ ] N/A unless implemented — then re-run smoke and confirm accuracy delta ≤ 5pp (else parity is broken).

---

## Phase 5: Smoke validation + memory snapshot

### Overview

Bookkeeping. Re-run the single-doc 6-protocol matrix, compare to parser-bench's published baseline numbers, and snapshot the new accuracy floor in MEMORY.md so the next agent doesn't think 0% is the floor.

### Changes Required:

1. **Re-run the matrix** on `Arm_EE382N_4` (7 examples) with all four phases applied. Cost: ~$0.20.
2. **Update `.claude/memory/MEMORY.md`** changelog with one entry per phase landed (per `feedback_commit_granularity`), and a summary of the before → after accuracy table.
3. **(Stretch)** Re-run on a multi-doc slice (`--limit 30` covers 5 docs we have PDFs for). Compare aggregate to parser-bench's GPT-5.4 numbers.

### Success Criteria:

#### Automated Verification:

- [ ] `uv run pytest` green
- [ ] Matrix run completes for all 6 protocols without crashes (regression test against the `oracle_crop` bbox fix already landed today)

#### Manual Verification:

- [ ] Single-doc accuracy: `tiled_4up ≥ 50%`, `oracle_page ≥ 40%`, `full_doc ≥ 25%`
- [ ] (Stretch) 30-example aggregate within ±5pp of parser-bench's published GPT-5.4 baselines per protocol
- [ ] `.claude/memory/MEMORY.md` has a "what's the baseline floor now" entry for the next agent

---

## Testing Strategy

### Unit Tests:

- `tests/test_scoring.py` — pin enum normalization, absolute tolerance, all four answer-type branches, float-precision edges.
- `tests/test_harness.py` — pin `_remap_positional_pages` (Phase 2.2) and `image_dims_by_page` propagation in the simple path.
- `tests/test_workflow.py` — pin the prompt-building helpers (Phase 2.1, Phase 3.1).

### Integration Tests:

- Re-score golden run.json fixtures: write tiny fixtures simulating model outputs across all four answer_types, confirm accuracy/page_recall/bbox_iou all move correctly through the harness.

### Manual Testing Steps:

1. `set -a; source .env; set +a; uv run python scripts/run_hf_matrix.py --phase a --limit 7 --staging-dir ~/.cache/focusparse/hf_staging --pdfs-root ~/.cache/focusparse/pdfs --output-dir results/hf/post-fix-arm`
2. Inspect `results/hf/post-fix-arm/matrix_summary.json` — confirm per-protocol accuracy is in the expected band (full_doc 25–40%, tiled_4up 50–65%, oracle_crop 25–40%).
3. Spot-check 3 predictions per protocol — confirm the model is now emitting source page numbers and answer-format-appropriate strings.

## Performance Considerations

None. All changes are in the scoring + prompt layer; no impact on latency, tokens, or cost.

## Migration Notes

Cached predictions on disk (`results/hf/.../predictions/*.json`) record the **old** `answer_correct` / `page_recall` / `bbox_iou`. They are valid model outputs; only the **scoring** is wrong. Use `scripts/rescore_predictions.py` (Phase 1.4) to refresh aggregates without re-running the model.

`run.json` aggregates downstream of cached predictions (`evidence_reward_mean`, `lazy_answer_rate`, etc.) will need recomputation too — fold this into the rescore script.

## References

- Bug-fixed scorer prototype run: `tiled_4up 0.0% → 57.1%` (verified 2026-04-27 in this session)
- Parser-bench scoring: `third_party/parser-bench/src/eval/scoring.py:56-180`
- Parser-bench schema: `third_party/parser-bench/src/utils/schema.py:20-30` (AnswerType enum)
- Parser-bench published baselines: `.claude/memory/MEMORY.md` standing context
- Active SOTA-leverage plan: `plans/2026-04-27-phase2-sota-leverage.md` (this plan unblocks its accuracy gate)
- Recent commits: `ab7c908` (oracle_crop bbox fix), `78cf023` (matrix protocol extension)
