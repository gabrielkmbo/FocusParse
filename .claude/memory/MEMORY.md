# FocusParse — Agent Memory

> Agents: keep this file current. Add a dated entry any time you learn something
> that would not be obvious to the next agent from the code alone — model quirks,
> debugging gotchas, tier-routing decisions, trajectory schema evolutions.
> Structure: one **## YYYY-MM-DD — topic** heading per discovery, newest at top.
> Keep standing context at the top; prune stale entries aggressively.

## Standing context

- **Benchmark:** `gabrielbo/parser-bench` on HF. Schema: `BenchmarkExample` in the `third_party/parser-bench` submodule.
- **Baseline numbers to beat (parser-bench 2026-04-13 slide deck):**
  - GPT-5.4: full_doc 48.6% → oracle_crop 59.4% (+10.8 pt localization gap)
  - Gemini 3.1 Pro Preview: 42.0 → 50.3 (+8.3 pt)
  - Claude Opus 4.6: 29.8 → 43.2 (+13.4 pt)
- **Cost headroom:** Claude full_doc $0.065/correct vs GPT-5.4 oracle_crop $0.010/correct → ~6× if agentic routing works.
- **Target v1 milestone:** `focus balanced` ≥ +6 pts accuracy at ≤ 0.7× cost-per-correct vs `focus simple gpt-5.4` on dev split.
- **Do not modify `parser-bench`** from this repo — it is a read-only submodule at `third_party/parser-bench/`.

## Environment keys (actually used in .env)

- `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` (note: not `GOOGLE_API_KEY`), `HF_TOKEN`, `TESSERACT_CMD`, `VLLM_API_KEY`.
- `VLLM_API_KEY` exists for self-hosted vLLM / sglang OSS model serving. Use via `openai` backend + `base_url` when we wire OSS models in Phase 5.

## Training plan (tracked here; not built here)

- Recipe: AgenticOCR-style. SFT on teacher trajectories filtered by dual threshold
  (coverage recall ≥ 0.8 AND IoU ≥ 0.3); then GRPO with reward shape:
  `answer × IoU × coverage − spurious_box − overlap − lazy_full_page`.
- Mask loss so only assistant reasoning + tool-call tokens contribute (AgenticOCR §3.2).
- Base model: Qwen3-VL-4B. Training: **Modal**. Deploy: HF Inference Endpoint.
- Trajectory source: `results/runs/<ts>/traces.jsonl` from FocusParse's `focus eval --tier frontier`
  plus hard negatives where parser-bench teacher and verifier disagreed.
- Training repo (future): `FocusTrain` — consumes traces at `schema_version = "1"`.

## Model quirks (living)

- **Gemini 2.5/3.x**: set `thinking_budget ≥ 1024` or visible response is empty.
- **GPT-5.x**: uses `max_completion_tokens`, not `max_tokens`.
- **Claude Opus 4.6**: full_doc accuracy lags on finance charts; prefer GPT-5.4 as reasoner tier.
- **Gemini 3.1 Pro Preview**: cheapest frontier for `full_doc` per-correct; solid default for early experiments.

## Known sharp edges

- Layout HF endpoint (`jqkx3k3gn4ciymvi…`) returns a **single full-page bbox stub** on failure.
  Signal: "whole page crops only". Check `HF_TOKEN` + backoff logs first; `tools/layout_detect.py` must raise on stub, not succeed silently.
- NFS path uses SSH alias `llama-nfs` — must exist in `~/.ssh/config`. macOS `openrsync` needs `shlex.quote`'d remote paths (lift from parser-bench `scripts/run_generate.py` `_rsync`).
- HF dataset revision is **not** pinned yet (plan §8.4 deferred). Benchmark is still being hardened (contact-sheet bbox fix + 300 dpi oracle crops per parser-bench slide deck 2026-04-13). Re-run baselines whenever the dataset advances; note advances here with the new revision SHA.
- Layout endpoint is **shared** with parser-bench. Rate-limit to ≤ 2 req/s; cache layout output on disk under `cache/layout/<doc_sha>.json` so eval sweeps don't burn shared quota.

## Standing decisions (from plan §8)

- **8.1 parser-bench schema dep**: git submodule at `third_party/parser-bench/`.
- **8.2 visual rerank**: skipped in v1 — FTS-only router. `visual_rerank.py` is a stub seam.
- **8.3 layout endpoint**: cache-on-disk + rate-limited fallback to shared parser-bench endpoint.
- **8.4 HF revision pin**: deferred; `FOCUSPARSE_DATASET_REVISION` env var wired for one-line flip later.

## Run log

### 2026-04-13 — Initial scaffold

First commit: plan written, repo scaffolded, parser-bench submodule seam created. Nothing executed locally yet — user asked to defer all local runs.

Next up: user runs `git submodule add https://github.com/gabrielkmbo/parse-bench third_party/parser-bench && uv sync --extra dev`, then we validate Phase 1 automated verification (§5 Phase 1 in the plan).
