---
description: Run baseline eval matrix with parallel subagents per model/protocol
---

# Run Baseline Evaluations

Run the baseline evaluation matrix using parallel subagents, one per model-protocol combination.

## Process:

1. **Check prerequisites:**
   - Verify `data/benchmark/` exists and has exported data
   - Check that required API keys are set (OPENAI_API_KEY, GEMINI_API_KEY, ANTHROPIC_API_KEY as needed)
   - Run `ls data/benchmark/` to confirm benchmark files

2. **Determine the matrix:**
   - Default models: `gpt-4o` (openai), `gemini-2.0-flash` (gemini), `claude-sonnet-4-6-20250514` (anthropic), `Qwen/Qwen2-VL-72B-Instruct` (openai + base-url)
   - Default protocols: `full_doc`, `oracle_page`, `oracle_crop`
   - If `$ARGUMENTS` specifies a subset (e.g. "gpt4o only" or "full_doc only"), narrow accordingly
   - Skip OSS/local models if no local endpoint is running

3. **Launch parallel subagents:**
   - Spawn one Agent per model-protocol cell using `run_in_background: true`
   - Each agent runs:
     ```bash
     uv run python scripts/run_eval.py data/benchmark/ \
       --backend <backend> --model <model> --protocol <protocol> \
       --output results/<name>_<protocol>.json \
       --resume --cache-dir results/cache
     ```
   - Add `--base-url` for OSS models with local endpoints
   - Add `--limit N` if the user requested a quick test

4. **Collect results:**
   - As each agent completes, note its accuracy and any errors
   - Present a summary table:
     ```
     Model              | full_doc | oracle_page | oracle_crop
     -------------------|----------|-------------|------------
     gpt-4o             |   72.3%  |     81.1%   |     88.5%
     gemini-2.0-flash   |   68.9%  |     76.4%   |     84.2%
     claude-sonnet      |   71.0%  |     79.8%   |     86.7%
     ```

5. **Report diagnostic gaps:**
   - If results exist, run comparison across runs
   - Flag any model that failed entirely (missing API key, endpoint down)

## Important:
- Use `--resume` so partial runs can continue
- Results go to `results/` directory
- Cache goes to `results/cache/` for reuse across runs
- If a single model fails, report it but don't block the others
