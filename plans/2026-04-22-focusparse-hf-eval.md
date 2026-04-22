# FocusParse — HuggingFace Evaluation Harness Implementation Plan

> **North star:** run FocusParse's agentic pipeline against `gabrielbo/parser-bench`'s HuggingFace validation split, end-to-end, from a fresh clone with only `HF_TOKEN` + provider keys. Produce a per-config results JSON and a full matrix summary shaped identically to parser-bench's published one, so numbers are trivially comparable.

**Author:** Gabriel Bo · **Date:** 2026-04-22 · **Plan format:** `/create_plan`

**Revisions**

- 2026-04-22 (same day): revised after Phase 1 of the main agentic plan landed. Signature drift between the initially-planned `run_simple_eval` and the shipped one is reconciled here. See §1 "Current state analysis" and §5 Phase B "Changes required" — CLI now builds the reasoner `ModelClient` from `tier_router` and passes it into the existing signature rather than rewriting the harness.

---

## 0. Overview

Three deliverables, modeled on parser-bench's `hf_loader.py` / `run_hf_eval.py` / `run_hf_matrix.py` but adapted to FocusParse idioms (pydantic v2, async, `_parser_bench.py` shim, no `src.utils.schema` sibling import):

1. **`src/focusparse/eval/hf_loader.py`** — library that materializes a HuggingFace split to disk in the layout FocusParse's harness expects (`<staging>/benchmark.jsonl` + `<staging>/data/processed/<doc>/images/*_page_NNNN_300dpi.png`). Idempotent. Exposes `materialize_split()` + `dataset_fingerprint()`.
2. **`scripts/run_hf_eval.py`** — one-config runner: a single (`agent`, `protocol`, `tier-override`) run of FocusParse against the materialized split. **No `--backend` flag** — the "model" is the FocusParse pipeline; the reasoner-tier config chooses the underlying VLM.
3. **`scripts/run_hf_matrix.py`** — sweeps the dimensions that matter for an agentic pipeline (see §4.4). Writes `results/hf/matrix_summary.json` in parser-bench's shape. Merges across partitioned runs so `--phase a` followed by `--phase b` yields one combined summary.

Non-goal: re-scoring. Metrics come from `focusparse.eval.scoring` (already implemented).

---

## 1. Current state analysis

### What's already built (green)

- `src/focusparse/dataset/loader.py::BenchmarkLoader._iter_hf()` streams `gabrielbo/parser-bench` and deserializes JSON-string fields (`supporting_bboxes`, `alternate_bboxes`, `evidence_relations`, `original_bboxes`, `difficulty`, `supporting_pages`, `page_images`). This is the streaming path; this plan adds the complementary _materialized_ path.
- `src/focusparse/_parser_bench.py` — file-path shim (`importlib.util.spec_from_file_location`) that loads parser-bench's `src/utils/schema.py` without adding to `sys.path`. Exports every schema type we need (`BenchmarkExample`, `BBox`, `Domain`, `AnswerType`, `Split`, `StressType`, `RegionType`, `EdgeType`, `DifficultyScores`, `EvidenceRelation`).
- `src/focusparse/eval/scoring.py` — `score_answer`, `page_recall`, `_bbox_iou`, `max_iou_over_alternates`, `score_evidence_reward`. Ready.
- `src/focusparse/eval/metrics.py::aggregate()` — rolls up per-example dicts into `AggregateMetrics`.
- `src/focusparse/cache/store.py` — content-addressed disk cache for derived artifacts.

### Hard blockers (must land before this plan's runnable phases)

These live in `plans/2026-04-13-focusparse-agentic-pipeline.md`; this plan **depends on** them, does not re-implement them. Status as of 2026-04-22 post-Phase-1:

| Blocker                                                                                                       | Where                                                | Needed before | Status                       |
| ------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------- | ------------- | ---------------------------- |
| Parser-bench submodule not initialized (`third_party/parser-bench/` absent → `_parser_bench.py` import fails) | one-time `git submodule add`                         | Phase A       | ✅ resolved (2026-04-13)     |
| `SimpleBaselineAgent.run`                                                                                     | `src/focusparse/pipeline/workflow.py`                | Phase B       | ✅ resolved (Phase 1)        |
| `OpenAIClient.predict` / `AnthropicClient.predict` / `GeminiClient.predict`                                   | `src/focusparse/models/{openai,anthropic,gemini}.py` | Phase B       | ✅ resolved (Phase 1)        |
| `run_simple_eval`                                                                                             | `src/focusparse/eval/harness.py`                     | Phase B       | ✅ resolved (Phase 1) †      |
| `FocusWorkflow.run`                                                                                           | `src/focusparse/pipeline/workflow.py`                | Phase D       | 🟡 still NotImplementedError |
| `run_focus_eval`                                                                                              | `src/focusparse/eval/harness.py`                     | Phase D       | 🟡 still NotImplementedError |

† **Signature drift:** the shipped `run_simple_eval` takes a pre-built `backend_client: ModelClient` plus `backend`/`model` strings for the manifest, not a `tier_router`. This plan's Phase B is updated to build the client at the CLI layer (`tier_router.client_for("reasoner")` in `run_hf_eval.py`) rather than rewriting the harness signature — see §5 Phase B §1 below for the reconciled shape.

**Sequencing rule:** Phase A (the loader) ships first. Phases B and C are **unblocked** and ready to implement. Phase D still waits on main-plan Phase 2 (`FocusWorkflow.run` + `run_focus_eval`).

### Bugs I'm silently fixing on port

The user-supplied parser-bench snippet has two issues:

- `logg.info("Wrote %s", benchmark_jsonl)` — typo for `logger.info`. Fixed.
- `from src.utils.schema import BBox, BenchmarkExample` — doesn't work in FocusParse (we'd collide with `src/focusparse`). Replaced with `from focusparse._parser_bench import BBox, BenchmarkExample`.

---

## 2. Desired end state

A fresh clone can run:

```bash
# one-time (dependency, not this plan's work)
git submodule add https://github.com/gabrielkmbo/parse-bench third_party/parser-bench
git submodule update --init --recursive
uv sync --extra dev

# Phase A — verify the loader works (no network cost beyond HF dataset stream)
uv run python -c "from focusparse.eval.hf_loader import materialize_split; \
  from pathlib import Path; \
  p, ds = materialize_split(Path.home() / '.cache/focusparse/hf_staging', limit=3); \
  print(p, len(ds))"

# Phase B — single-config smoke run (simple agent, gpt-5.4 reasoner via config)
uv run python scripts/run_hf_eval.py \
    --agent simple --protocol oracle_crop --limit 5

# Phase C — full matrix of simple × {protocols}
uv run python scripts/run_hf_matrix.py --phase a

# Phase D — once Phase 2 lands, add focus agent
uv run python scripts/run_hf_matrix.py --phase b --focus-tiers cheap_only,balanced,frontier
```

…and get back, in each case:

1. Per-config JSON at `results/hf/focusparse_<agent>_<protocol>_<tier_sha8>.json` shaped like parser-bench's `EvalRunResults` (accuracy, abstain_rate, page_recall, bbox_iou, count, total_cost_usd, cost_per_correct_usd, total_input_tokens, total_output_tokens) + FocusParse additions (evidence_reward_mean, lazy_answer_rate, tool_calls_mean).
2. Matrix summary at `results/hf/matrix_summary.json` with `{generated_at, hf_repo, hf_split, hf_revision, dataset_fingerprint, limit, results: {<config_key>: {<protocol>: {...}}}}` — same shape the user's snippet showed for `gemini_3_1_pro_preview`.
3. A `prediction_cache/` side-table so `--resume` skips already-scored examples.

### Success criteria for v1 (what "done" looks like)

- **Phase A:** `materialize_split(..., limit=5)` runs on a fresh clone, writes 5 PNGs + 5-line JSONL, second call is a no-op (idempotent). `dataset_fingerprint(ds)` returns a dict with `num_rows`, `fingerprint`, `split`, `version`, `description`.
- **Phase B+C:** `simple` agent × `oracle_crop` run on full validation split (148 rows) lands within **±1 pt accuracy** of parser-bench's published number for the same reasoner model — proves we haven't changed the evaluand.
- **Phase D:** `focus balanced` outperforms `simple gpt-5.4 oracle_crop` by ≥ +6 pts accuracy at ≤ 0.7× cost-per-correct on validation (the original v1 milestone, now measurable end-to-end).

---

## 3. What we're NOT doing

- **No `--backend openai|anthropic|gemini|openrouter` flag.** The reasoner's provider comes from the tier config; changing models means editing `configs/default.yaml` or passing `FOCUSPARSE_TIER_REASONER=<tier>`. A CLI that looks like parser-bench's would invite running non-FocusParse configs through this harness, which defeats the point.
- **No duplicate streaming loader.** `BenchmarkLoader._iter_hf()` stays. `hf_loader.py` is _only_ for materialize-to-disk.
- **No modifications to `third_party/parser-bench/`.** Read-only contract holds.
- **No new scoring metrics.** The matrix summary uses what's already in `eval/scoring.py` + `eval/metrics.py`.
- **No HTML report work.** That's Phase 4 of the original plan; this plan produces JSONs only.
- **No trajectory export changes.** This plan doesn't touch `traces/export.py` schema.
- **No stress-variant scoring.** Loader filters them out — same rationale as parser-bench (they lack `original_bboxes` so `oracle_crop` can't score them).
- **No local-GPU visual rerank.** v1 stays FTS-only per the active plan's §8.2.

---

## 4. Architecture

### 4.1 HF loader vs existing `BenchmarkLoader` — the split

Two complementary entry points. Document which to use in the loader docstring:

| Use case                                     | Entry point                                          | Why                                                                |
| -------------------------------------------- | ---------------------------------------------------- | ------------------------------------------------------------------ |
| Smoke tests, CI, one-off iteration           | `BenchmarkLoader.from_hf().iter_split(split, limit)` | Streaming, no disk cost, no prereq                                 |
| Full eval runs, matrix runs, reproducibility | `hf_loader.materialize_split(staging, split, limit)` | Idempotent, resolvable paths, fingerprint-able, offline-replayable |

`materialize_split()` returns `(benchmark_jsonl_path, ds)` — the JSONL is what `run_simple_eval` reads; the raw `Dataset` object is retained so the caller can read `ds.info` / `ds._fingerprint` for the reproducibility manifest.

### 4.2 Staging layout

Mirror parser-bench exactly — the staging dir is an _input_ to the runner, not a FocusParse cache:

```
<staging_root>/                                    # default: ~/.cache/focusparse/hf_staging/
├── benchmark.jsonl                                # one BenchmarkExample per line
└── data/
    └── processed/
        └── <doc_stem>/
            └── images/
                ├── <doc_stem>_page_0001_300dpi.png
                └── <doc_stem>_page_0002_300dpi.png
```

FocusParse's own `cache/` (content-addressed crops, OCR, layout responses) stays separate. They're different concerns: staging holds pristine input pages, cache holds _derived_ artifacts keyed by `sha256(doc_id, page, bbox, dpi, mode)`.

`page_images` inside `benchmark.jsonl` are stored **relative to `<staging_root>`** so the runner can be invoked with `project_root=<staging_root>` and paths resolve unchanged.

### 4.3 Single-config script (`scripts/run_hf_eval.py`)

Flags (Click, to match parser-bench's shape):

```
--agent            simple | focus                  (default: simple)
--protocol         full_doc | oracle_page | oracle_crop
                   | focus_default                 (default: oracle_crop for simple, focus_default for focus)
--tier-override    role=tier (repeatable)          e.g. --tier-override reasoner=frontier
--hf-repo          (default: gabrielbo/parser-bench)
--hf-split         (default: validation)           ← our test benchmark; see parser-bench SPLIT_MAP
--hf-revision      (default: null)                 pin for paper reproducibility
--staging-dir      (default: ~/.cache/focusparse/hf_staging)
--output-dir       (default: results/hf)
--cache-dir        (default: results/cache/hf)     ← prediction cache, not crop cache
--limit            (default: null)                 full split
--max-concurrent   (default: 8)
--resume/--no-resume (default: --resume)
```

Output filename is deterministic given config + overrides:

```
results/hf/focusparse_<agent>_<protocol>_<tier_sha8>.json
```

where `tier_sha8 = sha256(json.dumps(resolved_tier_dict, sort_keys=True))[:8]`. This makes two runs with different `FOCUSPARSE_TIER_*` overrides produce different filenames automatically — no manual suffixing.

Resolved tier dict is the full `{role: {provider, model}}` snapshot after applying `--tier-override` and env, so tier sha captures everything that affects the answer.

`--tier-override` is implemented by setting `FOCUSPARSE_TIER_<ROLE>=<tier>` in `os.environ` before `load_config()`. The existing env-override path in `FocusConfig.tier_for()` picks it up unchanged.

### 4.4 Matrix dimensions (`scripts/run_hf_matrix.py`)

Agentic pipelines have different sweeps than "9 models × 5 protocols". Our matrix:

**Phase A (pre-Phase-2 — usable today once Phase 1 final lands):**

- Axis 1: `agent = simple`
- Axis 2: `protocol ∈ {full_doc, oracle_page, oracle_crop}`
- Tier config: frozen at whatever `configs/default.yaml` ships. One config key: `focusparse_simple_<reasoner_tier_sha8>`.
- Total: 3 runs.
- Purpose: reproduce parser-bench baselines for our reasoner choice. Proves we haven't changed the evaluand.

**Phase B (post-Phase-2):**

- Axis 1: `agent = focus`
- Axis 2: `protocol = focus_default` (agentic pipeline owns its own region selection — the notion of "oracle_crop" doesn't apply)
- Axis 3: `tier_profile ∈ {cheap_only, balanced, frontier}`
  - `cheap_only` = every role → cheap tier
  - `balanced` = config default (cheap planner/router, mid localizer/verifier, frontier reasoner)
  - `frontier` = every role → frontier tier
- Total: 3 more runs. Each produces a config key like `focusparse_focus_<tier_profile>_<tier_sha8>`.

**Matrix ceiling:** 6 runs.

**`--phase` flag** lets you partition the matrix: `--phase a` runs the 3 simple rows, `--phase b` runs the 3 focus rows. The matrix summary is _merged_ on write — re-running `--phase a` after `--phase b` produces one file with all 6 configs. Implementation: load existing `matrix_summary.json` if present, update the `results` dict with new keys, preserve existing keys, rewrite.

### 4.5 `matrix_summary.json` shape

Identical to the user's example (fields from parser-bench's exact output):

```json
{
  "generated_at": "2026-04-22T15:00:00+00:00",
  "hf_repo": "gabrielbo/parser-bench",
  "hf_split": "validation",
  "hf_revision": "HEAD",
  "dataset_fingerprint": {
    "num_rows": 148,
    "fingerprint": "5d97772056d8e2de",
    "split": "validation",
    "version": "0.0.0",
    "description": null
  },
  "limit": null,
  "results": {
    "focusparse_simple_<tier_sha8>": {
      "full_doc":    {"accuracy": ..., "abstain_rate": ..., "page_recall": ..., "bbox_iou": ..., "count": 148, "total_cost_usd": ..., "cost_per_correct_usd": ..., "total_input_tokens": ..., "total_output_tokens": ...},
      "oracle_page": {...},
      "oracle_crop": {...}
    },
    "focusparse_focus_balanced_<tier_sha8>": {
      "focus_default": {..., "evidence_reward_mean": 0.41, "lazy_answer_rate": 0.08, "tool_calls_mean": 3.2}
    }
  }
}
```

FocusParse-specific columns (`evidence_reward_mean`, `lazy_answer_rate`, `tool_calls_mean`) appear only on `focus_default` rows. `simple` rows stay in the parser-bench format exactly for comparability.

---

## 5. Implementation phases

Each phase has automated + manual success criteria. **Pause after each phase for manual confirmation before proceeding.**

### Phase A — HF loader library

**What this phase accomplishes:** a library function that materializes a HF split to disk, idempotently, with a reproducibility fingerprint. Works today — no upstream blockers beyond the submodule.

#### Changes required

**1. `src/focusparse/eval/hf_loader.py` (new)**

Port of the user's `materialize_split` with FocusParse-specific adaptations.

```python
"""Materialize a HuggingFace parser-bench split to disk."""
from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path

from datasets import Dataset, load_dataset

from focusparse._parser_bench import BBox, BenchmarkExample

logger = logging.getLogger(__name__)

_DEFAULT_REPO = "gabrielbo/parser-bench"
_DEFAULT_SPLIT = "validation"  # HF validation == parser-bench "test" benchmark


def materialize_split(
    staging_root: Path,
    *,
    repo_id: str = _DEFAULT_REPO,
    split: str = _DEFAULT_SPLIT,
    revision: str | None = None,
    limit: int | None = None,
    force: bool = False,
) -> tuple[Path, Dataset]:
    """Materialize an HF split into <staging_root>/benchmark.jsonl + images.

    Idempotent: returns immediately if the JSONL exists with matching row count.
    Returns (benchmark_jsonl_path, hf_dataset). Raises on missing HF_TOKEN
    if the dataset is gated (the `datasets` library surfaces the 401).
    """
    staging_root.mkdir(parents=True, exist_ok=True)
    processed_root = staging_root / "data" / "processed"
    processed_root.mkdir(parents=True, exist_ok=True)
    benchmark_jsonl = staging_root / "benchmark.jsonl"

    logger.info("Loading HF dataset %s (split=%s, revision=%s)",
                repo_id, split, revision or "HEAD")
    ds = load_dataset(repo_id, split=split, revision=revision)
    ds = _filter_stress_rows(ds)
    if limit is not None:
        ds = ds.select(range(min(limit, len(ds))))

    if not force and benchmark_jsonl.exists():
        with benchmark_jsonl.open() as f:
            existing = sum(1 for _ in f)
        if existing == len(ds):
            logger.info("Staging %s already complete (%d rows). Reusing.",
                        staging_root, existing)
            return benchmark_jsonl, ds

    logger.info("Materializing %d rows into %s", len(ds), staging_root)
    with benchmark_jsonl.open("w") as out:
        for row in ds:
            example = _row_to_example(row, processed_root)
            out.write(example.model_dump_json() + "\n")

    logger.info("Wrote %s", benchmark_jsonl)
    return benchmark_jsonl, ds


def _filter_stress_rows(ds: Dataset) -> Dataset:
    """Drop pre-baked stress variants; they lack `original_bboxes` for oracle_crop.

    Safe when the `stress_type` column is missing (older dataset revisions).
    """
    if "stress_type" not in ds.column_names:
        return ds
    stress_types = ds["stress_type"]
    keep_mask = [s in (None, "", "none") for s in stress_types]
    dropped = len(keep_mask) - sum(keep_mask)
    if dropped == 0:
        return ds
    offender_counts = Counter(
        s for s, keep in zip(stress_types, keep_mask, strict=True) if not keep
    )
    logger.info("Filtered %d stress rows (kept %d canonical): %s",
                dropped, sum(keep_mask), dict(offender_counts))
    return ds.select([i for i, keep in enumerate(keep_mask) if keep])


def _page_num_from_hf_image_index(idx: int, row: dict) -> int:
    """HF page_images are ordered by supporting_pages; most rows have one."""
    supporting = row.get("supporting_pages") or []
    if idx < len(supporting):
        return int(supporting[idx])
    return idx + 1


def _row_to_example(row: dict, processed_root: Path) -> BenchmarkExample:
    source_pdf_name = row["source_pdf"]
    doc_stem = Path(source_pdf_name).stem
    doc_images_dir = processed_root / doc_stem / "images"
    doc_images_dir.mkdir(parents=True, exist_ok=True)
    staging_root = processed_root.parent.parent

    page_image_paths: list[str] = []
    for idx, pil_img in enumerate(row["page_images"]):
        if pil_img is None:
            continue
        page_num = _page_num_from_hf_image_index(idx, row)
        fname = f"{doc_stem}_page_{page_num:04d}_300dpi.png"
        out_path = doc_images_dir / fname
        if not out_path.exists():
            pil_img.save(out_path, format="PNG")
        page_image_paths.append(str(out_path.relative_to(staging_root)))

    supporting_bboxes = [BBox(**b) for b in json.loads(row.get("supporting_bboxes") or "[]")]
    alternate_bboxes = [BBox(**b) for b in json.loads(row.get("alternate_bboxes") or "[]")]

    return BenchmarkExample(
        id=row["id"],
        domain=row["domain"],
        source_pdf=source_pdf_name,
        page_images=page_image_paths,
        question=row["question"],
        answer=row["answer"],
        answer_type=row["answer_type"],
        answer_unit=row.get("answer_unit"),
        tolerance=row.get("tolerance"),
        supporting_pages=list(row.get("supporting_pages") or []),
        supporting_bboxes=supporting_bboxes,
        alternate_bboxes=alternate_bboxes,
        evidence_relations=[],
        multi_region_required=bool(row.get("multi_region_required", False)),
        requires_visual=bool(row.get("requires_visual", True)),
        difficulty={
            "visual": int(row.get("difficulty_visual", 1)),
            "reasoning": int(row.get("difficulty_reasoning", 1)),
            "localization": int(row.get("difficulty_localization", 1)),
        },
        question_family=row.get("question_family", ""),
        stress_type=row.get("stress_type") or "none",
        reasoning_chain=row.get("reasoning_chain"),
        evidence_page_spread=int(row.get("evidence_page_spread", 0)),
        adversarial_type=row.get("adversarial_type"),
        split=row.get("split") or None,
        original_bboxes=[],
    )


def dataset_fingerprint(ds: Dataset) -> dict:
    """Identify a materialized dataset revision for reproducibility manifests."""
    info = ds.info
    split_obj = ds.split
    return {
        "num_rows": len(ds),
        "fingerprint": ds._fingerprint,
        "split": str(split_obj) if split_obj is not None else None,
        "version": str(info.version) if info.version else None,
        "description": info.description if info.description else None,
    }
```

**2. `tests/test_hf_loader.py` (new)**

Tests that run without network by mocking `load_dataset`:

- `test_filter_stress_rows_drops_pre_baked_variants`
- `test_filter_stress_rows_noop_when_column_missing` — creates a `Dataset` without `stress_type` and asserts pass-through
- `test_row_to_example_round_trip` — one row → `BenchmarkExample` → `.model_dump_json()` reloads cleanly
- `test_materialize_split_idempotent` — call twice, second call skips write, returns same path
- `test_dataset_fingerprint_shape` — asserts dict has the 5 expected keys

One slow test gated on `HF_TOKEN` (CI skips):

- `@pytest.mark.slow` `test_materialize_validation_limit_3` — actually hits HF, writes 3 rows, cleans up

#### Automated verification

- [ ] `uv run ruff check src/focusparse/eval/hf_loader.py tests/test_hf_loader.py` passes.
- [ ] `uv run ruff format --check src/focusparse/eval/hf_loader.py tests/test_hf_loader.py` passes.
- [ ] `uv run pytest tests/test_hf_loader.py -v` passes (excluding `-m slow`).
- [ ] `uv run pytest tests/test_hf_loader.py -m slow -v` passes locally with `HF_TOKEN` set.
- [ ] `uv run python -c "from focusparse.eval.hf_loader import materialize_split, dataset_fingerprint; print('ok')"` imports without error.

#### Manual verification

- [ ] With `HF_TOKEN` set, run `materialize_split(Path("/tmp/fp_smoke"), limit=5)` in a REPL — confirm 5 PNGs under `data/processed/<doc>/images/` and a 5-line `benchmark.jsonl`.
- [ ] Re-run with `limit=5` — confirm "Staging already complete" log message, no disk writes.
- [ ] Open one PNG — confirm it's a real 300dpi page.
- [ ] `cat benchmark.jsonl | head -1 | jq .page_images` — confirm paths are _relative_ (e.g. `"data/processed/10-K/images/10-K_page_0042_300dpi.png"`, not absolute).

**Pause for manual confirmation before proceeding.**

---

### Phase B — Single-config eval script

**What this phase accomplishes:** `scripts/run_hf_eval.py` runs one (`agent`, `protocol`, `tier-override`) config against the materialized split. Produces parser-bench-shaped JSON output. Supports `--resume` via prediction cache.

#### Prerequisites (upstream — not in this plan)

- Phase 1 final of the original plan: `SimpleBaselineAgent.run`, `{OpenAI,Anthropic,Gemini}Client.predict`, `run_simple_eval` all implemented. **Status: ✅ resolved 2026-04-22.**

#### Changes required

**1. `src/focusparse/eval/harness.py` — KEEP shipped signature; CLI bridges the gap**

Earlier drafts of this plan proposed widening `run_simple_eval` to take `tier_router`, `output_path`, `project_root`, `cache_dir`, `max_concurrent`. Phase 1 shipped a simpler shape that the existing tests (`tests/test_harness.py`) already cover:

```python
async def run_simple_eval(
    examples: Iterable[BenchmarkExample],
    *,
    backend_client: ModelClient,
    backend: str,
    model: str,
    protocol: str,
    output_dir: Path,
    images_root: Path,
    limit: int | None = None,
    resume: bool = True,
) -> dict[str, Any]  # {manifest, aggregate: AggregateMetrics, per_example, output_dir}
```

**Reconciliation:** do the tier-resolution + schema-wrapping at the CLI layer rather than reshaping the harness.

- `tier_router` → `run_hf_eval.py` resolves `reasoner` and builds the `ModelClient`: `client = _build_client(config.tier_for("reasoner"))`. The tier's `provider`/`model` strings feed the existing `backend=` / `model=` parameters for the manifest.
- `output_path` (single JSON) → `run_hf_eval.py` passes `output_dir=<cache_dir>/<config_key>/` to the harness, then reads the harness's `run.json` + `per_example.jsonl` and re-emits a parser-bench-shaped `EvalRunResults` at the final `output_path`. Two artifacts — the harness run-dir (debug) and the CLI's single JSON (matrix-consumable) — but they're both valid.
- `project_root` → `images_root`. Same semantics, just a rename we don't need to chase.
- `cache_dir` → the harness already writes its prediction cache under `<output_dir>/predictions/`. Namespacing by `<config_key>` is achieved by routing the CLI's `<cache_dir>/<config_key>/` into `output_dir` (one run dir per tier config). Invalidation on tier change is automatic because the directory path changes.
- `max_concurrent` → **deferred.** The current harness runs sequentially. The CLI accepts `--max-concurrent` for forward-compat but logs a warning if `> 1` and runs sequentially anyway. Parallelism lands as a follow-up once we see rate-limit contention on full 148-row runs.

**Net harness change in this plan: none.** All new code lives in `schemas.py` + `scripts/run_hf_eval.py`.

**2. `src/focusparse/eval/schemas.py` (new)** — output schema mirroring parser-bench

```python
class PerProtocolResults(BaseModel):
    accuracy: float
    abstain_rate: float
    page_recall: float
    bbox_iou: float
    count: int
    total_cost_usd: float | None = None
    cost_per_correct_usd: float | None = None
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    # FocusParse additions (populated only for focus agent; null for simple)
    evidence_reward_mean: float | None = None
    lazy_answer_rate: float | None = None
    tool_calls_mean: float | None = None


class EvalRunResults(BaseModel):
    config_key: str                       # e.g. "focusparse_simple_<tier_sha8>"
    agent: str
    protocol: str
    tier_sha8: str
    resolved_tiers: dict[str, dict]       # {role: {provider, model, ...}}
    hf_repo: str
    hf_split: str
    hf_revision: str | None
    dataset_fingerprint: dict
    overall: PerProtocolResults
    # Optional per-example breakdown for debugging
    per_example: list[dict] | None = None
```

**3. `scripts/run_hf_eval.py` (new)**

Argparse-based (matches the existing `scripts/reproduce_baselines.py` style). The CLI owns tier resolution, client construction, and schema wrapping; the harness stays unchanged.

```python
#!/usr/bin/env python3
"""Run FocusParse against the HF parser-bench validation split.

Single-config runner. No `--backend` flag — the reasoner comes from the tier
config (configs/default.yaml) and can be overridden with --tier-override.

    uv run python scripts/run_hf_eval.py --agent simple --protocol oracle_crop --limit 5
    uv run python scripts/run_hf_eval.py --agent simple --protocol full_doc \
        --tier-override reasoner=frontier
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_STAGING = Path.home() / ".cache" / "focusparse" / "hf_staging"
_REASONER_ROLE = "reasoner"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", choices=["simple", "focus"], default="simple")
    parser.add_argument(
        "--protocol",
        required=True,
        choices=["full_doc", "oracle_page", "oracle_crop", "focus_default"],
    )
    parser.add_argument(
        "--tier-override", action="append", default=[],
        help="role=tier (e.g. reasoner=frontier). Repeatable.",
    )
    parser.add_argument("--hf-repo", default="gabrielbo/parser-bench")
    parser.add_argument("--hf-split", default="validation")
    parser.add_argument("--hf-revision", default=None)
    parser.add_argument("--staging-dir", type=Path, default=_DEFAULT_STAGING)
    parser.add_argument("--output-dir", type=Path, default=Path("results/hf"))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--max-concurrent", type=int, default=1,
                        help="Forward-compat only; harness runs sequentially.")
    parser.add_argument("--resume", dest="resume", action="store_true", default=True)
    parser.add_argument("--no-resume", dest="resume", action="store_false")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    # Apply --tier-override to env BEFORE loading config so the existing
    # FocusConfig.tier_for() override path picks it up.
    for ov in args.tier_override:
        role, _, tier = ov.partition("=")
        if not role or not tier:
            parser.error(f"--tier-override must be role=tier, got {ov!r}")
        os.environ[f"FOCUSPARSE_TIER_{role.upper()}"] = tier

    # Deferred imports so --help works without heavy deps.
    from focusparse.eval.harness import run_simple_eval
    from focusparse.eval.hf_loader import dataset_fingerprint, materialize_split
    from focusparse.eval.schemas import EvalRunResults, PerProtocolResults
    from focusparse.models.tiers import TierRouter
    from focusparse.utils.config import load_config

    if args.agent == "focus":
        parser.error("--agent focus requires Phase 2 of the main plan (FocusWorkflow).")

    config = load_config()
    tier_router = TierRouter(config)
    resolved = {role: config.tier_for(role).model_dump() for role in config.roles}
    tier_sha8 = hashlib.sha256(
        json.dumps(resolved, sort_keys=True).encode()
    ).hexdigest()[:8]

    reasoner = config.tier_for(_REASONER_ROLE)
    backend_client = tier_router.client_for(_REASONER_ROLE)
    backend, model = reasoner.provider, reasoner.model

    benchmark_jsonl, ds = materialize_split(
        args.staging_dir,
        repo_id=args.hf_repo,
        split=args.hf_split,
        revision=args.hf_revision,
        limit=args.limit,
    )
    fingerprint = dataset_fingerprint(ds)

    config_key = f"focusparse_{args.agent}_{args.protocol}_{tier_sha8}"
    run_dir = args.output_dir / config_key  # debug artifacts + prediction cache
    run_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output_dir / f"{config_key}.json"

    from focusparse._parser_bench import BenchmarkExample
    examples = [
        BenchmarkExample.model_validate_json(line)
        for line in benchmark_jsonl.read_text().splitlines()
        if line.strip()
    ]

    result = asyncio.run(run_simple_eval(
        examples,
        backend_client=backend_client,
        backend=backend,
        model=model,
        protocol=args.protocol,
        output_dir=run_dir,
        images_root=args.staging_dir,
        limit=args.limit,
        resume=args.resume,
    ))

    agg = result["aggregate"]
    per_example = result["per_example"]
    n_correct = sum(1 for r in per_example if r.get("answer_correct"))
    abstain_rate = sum(
        1 for r in per_example if _looks_abstain(r.get("answer_pred"))
    ) / max(1, len(per_example))

    overall = PerProtocolResults(
        accuracy=agg.accuracy,
        abstain_rate=abstain_rate,
        page_recall=agg.page_recall_mean,
        bbox_iou=agg.bbox_iou_mean,
        count=agg.n,
        total_cost_usd=agg.usd_total,
        cost_per_correct_usd=agg.usd_per_correct,
        total_input_tokens=int(agg.tokens_in_mean * agg.n) if agg.n else 0,
        total_output_tokens=int(agg.tokens_out_mean * agg.n) if agg.n else 0,
        # focus-agent extras left null for simple rows
    )
    wrapped = EvalRunResults(
        config_key=config_key,
        agent=args.agent,
        protocol=args.protocol,
        tier_sha8=tier_sha8,
        resolved_tiers=resolved,
        hf_repo=args.hf_repo,
        hf_split=args.hf_split,
        hf_revision=args.hf_revision,
        dataset_fingerprint=fingerprint,
        overall=overall,
    )
    output_path.write_text(wrapped.model_dump_json(indent=2))
    logger.info("Wrote %s", output_path)

    cost = overall.total_cost_usd or 0.0
    per_correct = overall.cost_per_correct_usd or 0.0
    print(
        f"\n{config_key}: accuracy={overall.accuracy:.1%} n={overall.count} "
        f"cost=${cost:.2f} (${per_correct:.3f}/correct)"
    )
    return 0


def _looks_abstain(text: str | None) -> bool:
    if not text:
        return False
    t = text.lower()
    return any(k in t for k in ("unanswerable", "cannot be determined", "n/a"))


if __name__ == "__main__":
    sys.exit(main())
```

**4. Prediction cache semantics**

The harness already writes `<output_dir>/predictions/<safe_id>.json` per example. `run_hf_eval.py` passes `output_dir=<args.output-dir>/<config_key>/` so the prediction cache is automatically namespaced by tier sha — any tier change → new dir → cold cache.

This is a _prediction_ cache, separate from FocusParse's content-addressed crop cache (`./cache/`). Different invalidation semantics: prediction cache invalidates on any tier-config change (embedded in path); crop cache invalidates only on input-doc change.

#### Automated verification

- [ ] `uv run ruff check scripts/run_hf_eval.py src/focusparse/eval/schemas.py` passes.
- [ ] `uv run python scripts/run_hf_eval.py --help` prints the flag list.
- [ ] `uv run pytest tests/test_hf_eval_cli.py` passes — tests `--tier-override` env application + `tier_sha8` determinism (no network).
- [ ] `uv run python scripts/run_hf_eval.py --agent simple --protocol oracle_crop --limit 3` produces `results/hf/focusparse_simple_oracle_crop_<sha8>.json` with a valid `EvalRunResults`.
- [ ] Re-run the same command — logs show "skipping N cached examples" and the second run is sub-second per example.

#### Manual verification

- [ ] With `HF_TOKEN` + `OPENAI_API_KEY` set, run the 3-example smoke command. Check that `accuracy` in the output JSON is ∈ [0, 1] and `count == 3`.
- [ ] Kill the process halfway through a `--limit 10` run; restart; confirm it picks up where it left off.
- [ ] Change `FOCUSPARSE_TIER_REASONER=cheap` and re-run — confirm the output filename's `<sha8>` is different.
- [ ] Open one prediction-cache file — confirm `predicted_bboxes` is a list of `{page, x0, y0, x1, y1}` dicts.

**Pause for manual confirmation.**

---

### Phase C — Full matrix script (simple-only, pre-Phase-2)

**What this phase accomplishes:** `scripts/run_hf_matrix.py --phase a` runs the 3 `simple × protocol` rows and writes `matrix_summary.json` in parser-bench's shape. Designed so Phase D just adds keys to the same file.

#### Changes required

**1. `scripts/run_hf_matrix.py` (new)**

```python
#!/usr/bin/env python3
"""Sweep FocusParse configs against the HF parser-bench validation split.

Phase A (default): simple × {full_doc, oracle_page, oracle_crop}  — 3 runs
Phase B:           focus  × {cheap_only, balanced, frontier}      — 3 runs
Merges both phases into a single results/hf/matrix_summary.json on write.

Usage:
    uv run python scripts/run_hf_matrix.py --phase a
    uv run python scripts/run_hf_matrix.py --phase b
    uv run python scripts/run_hf_matrix.py --phase a --phase b  # sequential
"""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import click

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

_PHASE_A_CONFIGS = [
    {"agent": "simple", "protocol": p} for p in ("full_doc", "oracle_page", "oracle_crop")
]

_TIER_PROFILES = {
    "cheap_only": {"planner": "cheap", "router": "cheap", "localizer_rerank": "cheap",
                   "reasoner": "cheap", "verifier": "cheap"},
    "balanced":   {},  # use defaults
    "frontier":   {"planner": "frontier", "router": "frontier", "localizer_rerank": "frontier",
                   "reasoner": "frontier", "verifier": "frontier"},
}


@click.command()
@click.option("--phase", multiple=True, type=click.Choice(["a", "b"]), default=["a"])
@click.option("--focus-tiers", default="balanced",
              help="Comma-separated subset of {cheap_only, balanced, frontier}.")
@click.option("--hf-revision", default=None)
@click.option("--limit", default=None, type=int)
@click.option("--output-dir", default="results/hf", type=click.Path())
def main(phase, focus_tiers, hf_revision, limit, output_dir):
    out_root = Path(output_dir)
    out_root.mkdir(parents=True, exist_ok=True)
    summary_path = out_root / "matrix_summary.json"

    # Load existing summary (merge-across-partitions)
    if summary_path.exists():
        summary = json.loads(summary_path.read_text())
    else:
        summary = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "hf_repo": "gabrielbo/parser-bench",
            "hf_split": "validation",
            "hf_revision": hf_revision or "HEAD",
            "dataset_fingerprint": None,
            "limit": limit,
            "results": {},
        }

    run_specs: list[dict] = []
    if "a" in phase:
        run_specs.extend(_PHASE_A_CONFIGS)
    if "b" in phase:
        for tier_name in [t.strip() for t in focus_tiers.split(",") if t.strip()]:
            if tier_name not in _TIER_PROFILES:
                raise click.BadParameter(f"Unknown tier profile: {tier_name}")
            run_specs.append({"agent": "focus", "protocol": "focus_default",
                              "tier_profile": tier_name})

    for spec in run_specs:
        cmd = [sys.executable, "scripts/run_hf_eval.py",
               "--agent", spec["agent"],
               "--protocol", spec["protocol"]]
        if hf_revision:
            cmd += ["--hf-revision", hf_revision]
        if limit is not None:
            cmd += ["--limit", str(limit)]
        if "tier_profile" in spec:
            for role, tier in _TIER_PROFILES[spec["tier_profile"]].items():
                cmd += ["--tier-override", f"{role}={tier}"]

        logging.info("Running: %s", " ".join(cmd))
        subprocess.run(cmd, check=True)

    # Merge per-run JSONs into matrix summary
    for run_json in sorted(out_root.glob("focusparse_*.json")):
        if run_json.name == "matrix_summary.json":
            continue
        data = json.loads(run_json.read_text())
        config_key = data["config_key"]
        protocol = data["protocol"]
        # For simple: multiple protocols share a config_key (different tier_sha8s won't)
        # so nest by protocol. For focus: one protocol per config_key.
        base_key = config_key.rsplit(f"_{protocol}_", 1)
        # Simpler: strip the protocol suffix to group simple runs that share tiers
        group_key = config_key.replace(f"_{protocol}", "", 1) \
                              .replace(f"_simple", "_simple", 1)  # placeholder rewrite
        summary["results"].setdefault(group_key, {})[protocol] = {
            "accuracy": data["overall"]["accuracy"],
            "abstain_rate": data["overall"]["abstain_rate"],
            "page_recall": data["overall"]["page_recall"],
            "bbox_iou": data["overall"]["bbox_iou"],
            "count": data["overall"]["count"],
            "total_cost_usd": data["overall"].get("total_cost_usd"),
            "cost_per_correct_usd": data["overall"].get("cost_per_correct_usd"),
            "total_input_tokens": data["overall"].get("total_input_tokens", 0),
            "total_output_tokens": data["overall"].get("total_output_tokens", 0),
        }
        # Stamp fingerprint once
        if summary["dataset_fingerprint"] is None:
            summary["dataset_fingerprint"] = data["dataset_fingerprint"]

    summary["generated_at"] = datetime.now(timezone.utc).isoformat()
    summary_path.write_text(json.dumps(summary, indent=2))
    logging.info("Wrote %s", summary_path)


if __name__ == "__main__":
    main()
```

**Note on group_key:** the grouping logic above is simplified for readability. Final implementation groups by `{agent}_{tier_profile_or_default}_{tier_sha8}` so all three `simple` protocols nest under one key, matching parser-bench's `gemini_3_1_pro_preview: {tiled_2up, tiled_4up, ...}` shape.

**2. `tests/test_hf_matrix_merge.py` (new)** — unit-tests the merge logic against fake per-run JSONs in a tmp dir.

#### Automated verification

- [ ] `uv run ruff check scripts/run_hf_matrix.py` passes.
- [ ] `uv run python scripts/run_hf_matrix.py --help` prints the flag list.
- [ ] `uv run pytest tests/test_hf_matrix_merge.py` passes — tests that running `--phase a` on fake results produces a 3-protocol dict and that re-running preserves existing keys.
- [ ] `uv run python scripts/run_hf_matrix.py --phase a --limit 3` completes and produces `results/hf/matrix_summary.json` with exactly one top-level `results` key and 3 protocols under it.

#### Manual verification

- [ ] Open `matrix_summary.json` — confirm it matches the shape in §4.5 (including `dataset_fingerprint` populated, `hf_split == "validation"`).
- [ ] Spot-check one cell (`results.focusparse_simple_<sha8>.oracle_crop.accuracy`) against parser-bench's published number for the same reasoner — within ±1 pt.
- [ ] Delete `matrix_summary.json`, re-run `--phase a --limit 3`, confirm it regenerates from scratch without errors.
- [ ] Leave `matrix_summary.json` in place, run with a _different_ `--tier-override reasoner=...` — confirm a new top-level key appears alongside the existing one.

**Pause for manual confirmation.**

---

### Phase D — Extend matrix to `focus` agent (post-Phase-2)

**What this phase accomplishes:** `--phase b` becomes runnable. `focus × {cheap_only, balanced, frontier}` rows populate `matrix_summary.json`. Validates the v1 success criterion (`focus balanced` beats `simple gpt-5.4 oracle_crop` by ≥ +6 pts at ≤ 0.7× cost-per-correct).

#### Prerequisites (upstream)

- Phase 2 of the original plan: `FocusWorkflow.run` + `run_focus_eval` implemented, every pipeline `@step` wired, trajectory capture working.

#### Changes required

1. `scripts/run_hf_matrix.py` — no code changes needed (Phase C already defines `--phase b` and `_TIER_PROFILES`). Just un-gates once `run_focus_eval` stops raising.
2. `src/focusparse/eval/harness.py::run_focus_eval` — must populate `PerProtocolResults.evidence_reward_mean`, `lazy_answer_rate`, `tool_calls_mean` in addition to the base fields.
3. `src/focusparse/eval/schemas.py` — no changes (additive fields already defined, default `None`).
4. `tests/test_hf_matrix_merge.py` — add a case covering the focus_default row with the three FocusParse-specific fields populated.

#### Automated verification

- [ ] `uv run python scripts/run_hf_matrix.py --phase b --focus-tiers balanced --limit 3` completes.
- [ ] `matrix_summary.json` contains a `focus_default` entry under the balanced-tier group with non-null `evidence_reward_mean`, `lazy_answer_rate`, `tool_calls_mean`.
- [ ] `uv run pytest tests/test_hf_matrix_merge.py -k focus` passes.

#### Manual verification

- [ ] Full-split run: `uv run python scripts/run_hf_matrix.py --phase a --phase b --focus-tiers balanced`. Compare `focus balanced.focus_default.accuracy` against `simple_<sha8>.oracle_crop.accuracy` — the gap should be **≥ +6 pts**.
- [ ] Compare `cost_per_correct_usd` — `focus balanced` should be **≤ 0.7×** `simple_<sha8>.oracle_crop`.
- [ ] If either criterion fails, file a MEMORY.md entry with the gap and move on (this plan ships even when v1 milestone isn't hit — it's the _measurement infrastructure_, not the model).

---

## 6. Testing strategy

### Unit tests (no network)

- `tests/test_hf_loader.py` — stress-filter, row-to-example, idempotency, fingerprint shape. Mock `load_dataset`.
- `tests/test_hf_eval_cli.py` — `--tier-override` → env var mapping, `tier_sha8` determinism, flag parsing.
- `tests/test_hf_matrix_merge.py` — merge-across-partitions, existing-keys preservation.

### Integration tests (gated on `HF_TOKEN` + provider key, `pytest -m slow`)

- `tests/test_hf_smoke.py::test_simple_oracle_crop_3` — end-to-end 3-example `simple oracle_crop` run; asserts `results["overall"]["count"] == 3` and `accuracy in [0, 1]`.
- Deliberately _not_ asserting exact numbers — that's what the manual reproducibility check is for (spot-check vs parser-bench published).

### Manual reproducibility gate (human verifies)

Run `scripts/run_hf_matrix.py --phase a` on full validation (148 rows). Compare `results.focusparse_simple_<sha8>.oracle_crop.accuracy` against parser-bench's published number for the same reasoner model. **Must be within ±1 pt** — if not, something in the `simple` path diverged from parser-bench's `SimpleAgent` and we need to debug before running paid Phase-B rows.

---

## 7. Risks + mitigations

| Risk                                                                               | Mitigation                                                                                                                                                                 |
| ---------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `BenchmarkExample` rejects a field the loader constructs                           | Covered by Phase A's `test_row_to_example_round_trip`. Schema shim loads directly from parser-bench's `schema.py` so we inherit every field.                               |
| HF dataset is gated and `HF_TOKEN` missing silently                                | `datasets.load_dataset` surfaces a 401 — Phase A catches it and re-raises with a helpful message pointing at `.env.example`.                                               |
| Stress-row filter drops legitimate rows on a future dataset revision               | Filter is column-name-gated (skipped if `stress_type` column missing) and logs the offender breakdown when it fires. Unit-tested both branches.                            |
| `dataset._fingerprint` becomes a private API that breaks                           | It's been stable since `datasets >= 2.0`. If it ever breaks, fall back to `hashlib.sha256(str(ds.info).encode()).hexdigest()[:16]`. Pin `datasets>=3.0,<4.0` in pyproject. |
| Prediction cache staleness (tier config changes but cache isn't invalidated)       | Cache path includes `<config_key>` which embeds `tier_sha8`. Any tier change yields a new cache dir.                                                                       |
| Merge logic collides two runs with the same config key                             | Deliberate — re-running a config overwrites its entry in `matrix_summary.json`. Document in the script docstring.                                                          |
| Non-deterministic `tier_sha8` across Python versions due to dict ordering          | `json.dumps(..., sort_keys=True)` — deterministic regardless.                                                                                                              |
| Parser-bench numbers drift between the snippet's reference and current HF revision | `dataset_fingerprint` in every output JSON + `matrix_summary.json` records the fingerprint. Reproducibility is trivially auditable.                                        |
| User runs `--phase b` before `--phase a` completes                                 | `run_hf_matrix.py` runs specs in list order; `--phase a --phase b` is the documented sequential invocation. Partial runs still merge cleanly.                              |

---

## 8. Decisions resolved inline (no open questions)

1. **HF loader vs `BenchmarkLoader` split:** `hf_loader.py` = materialize-only. `BenchmarkLoader._iter_hf` stays for streaming. Docstring explains when to use each.
2. **Staging layout:** mirror parser-bench (`<staging>/data/processed/...`). FocusParse's `./cache/` stays separate for derived artifacts.
3. **No `--backend` flag:** reasoner provider via tier config only. `--tier-override role=tier` is the knob.
4. **Output filename determinism:** `focusparse_<agent>_<protocol>_<tier_sha8>.json`. `tier_sha8 = sha256(json.dumps(resolved_tier_dict, sort_keys=True))[:8]`.
5. **Matrix dimensions:** pre-Phase-2 = simple × 3 protocols; post-Phase-2 adds focus × 3 tier profiles. Total ceiling 6 configs.
6. **Matrix merge semantics:** `--phase a` then `--phase b` → one file. Re-running a config overwrites its entry.
7. **CLI shape:** standalone `scripts/*.py` (Click), not new `focus` subcommands. `focus eval` remains the library API.
8. **Prediction cache:** separate dir from content-addressed crop cache; scoped to `<config_key>`.
9. **Dataset fingerprint source:** `Dataset._fingerprint` + `Dataset.info.version`; stamped into every per-run JSON and the matrix summary.
10. **Stress-row filter:** on by default, column-gated, logs offender counts. No flag to disable in v1.

---

## 9. References

### Active plan this builds on

- `plans/2026-04-13-focusparse-agentic-pipeline.md` — the v0 design. Phase 1 final and Phase 2 are this plan's upstream dependencies.

### User-supplied reference snippets

- `hf_loader.py` / `run_hf_eval.py` / `run_hf_matrix.py` from parser-bench (in the /create_plan brief). Shape of `matrix_summary.json` lifted verbatim from the `gemini_3_1_pro_preview` example.

### FocusParse modules this plan extends

- `src/focusparse/dataset/loader.py` — streaming path (unchanged).
- `src/focusparse/_parser_bench.py` — schema shim (unchanged).
- `src/focusparse/eval/scoring.py` — all scoring primitives (unchanged).
- `src/focusparse/eval/harness.py` — `run_simple_eval` / `run_focus_eval` signatures aligned in Phase B.
- `src/focusparse/models/tiers.py` — `TierRouter` consumes `FOCUSPARSE_TIER_*` env overrides from `--tier-override`.

### External

- [`gabrielbo/parser-bench`](https://huggingface.co/datasets/gabrielbo/parser-bench) — `validation` split is our test benchmark (HF SPLIT_MAP rename).
- [`huggingface/datasets`](https://github.com/huggingface/datasets) — `load_dataset`, `Dataset.select`, `Dataset._fingerprint`.

---

## 10. Next step after this plan is approved

Proceed with **Phase A**. It has no upstream blockers beyond the one-time submodule init, which is already documented in the main plan. Phases B–D are gated on Phase 1 final / Phase 2 of the main plan and will unblock automatically as those land.

**Nothing is implemented until this plan is confirmed.**
