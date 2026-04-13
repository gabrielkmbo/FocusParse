# Monitor Eval Runs

You are an eval monitoring agent for the doclens/parser-bench benchmark. Your job is to persistently track running evaluations and report status back.

## What to monitor

1. **Background eval tasks** — check output files in `/private/tmp/claude-501/` for running eval processes
2. **Modal server health** — verify endpoints are responding
3. **Eval progress** — count 200 OK vs errors, check if protocols have completed

## How to check

### Check eval progress
```bash
# Find active eval output files
ls -lt /private/tmp/claude-501/-Users-gabrielbo-projects-parser-bench/*/tasks/*.output 2>/dev/null | head -5

# For each output file, check progress:
grep -c "200 OK" <output_file>        # successful requests
grep -c "ERROR" <output_file>         # failed requests  
grep "Completed" <output_file>        # completed protocols
grep "Saved.*predictions" <output_file>  # cached predictions saved
tail -5 <output_file>                 # latest activity
```

### Check Modal server health
```bash
# Qwen3.5-35B (experimental, team server)
curl -s -H "Authorization: Bearer $(grep VLLM_API_KEY .env | cut -d= -f2)" \
  https://llamaindex--qwen3-5-vllm-inference-serve.modal.run/v1/models

# Our servers (if deployed)
curl -s -H "Authorization: Bearer $(grep VLLM_API_KEY .env | cut -d= -f2)" \
  https://llamaindex--parser-bench-llama4-scout-serve.modal.run/v1/models
```

### Check results
```bash
# List completed result files
ls -lt results/*.json | head -10

# Check matrix summary
cat results/matrix_summary.json 2>/dev/null | python3 -m json.tool

# Compare models
uv run python3 -c "
import json
for f in sorted(Path('results/').glob('*_oracle_page.json')):
    data = json.loads(f.read_text())
    print(f'{f.stem}: {data[\"overall\"][\"accuracy\"]:.1%} ({data[\"overall\"][\"count\"]} examples)')
"
```

## When to alert

Report back to the main session when:
- An eval protocol **completes** (grep for "Completed" in output)
- An eval **fails** or gets stuck (no new 200s for >5 minutes)
- A Modal server **goes down** (curl returns error)
- All planned evals are **done**

## Current eval targets

| Setup | Model | Endpoint | Status |
|-------|-------|----------|--------|
| oss_qwen3_5_35b | qwen3.5-35b-a3b | llamaindex--qwen3-5-vllm-inference-serve.modal.run | Running oracle_page + oracle_crop |
| oss_gemma4_26b | gemma-4-26b-a4b | llamaindex--gemma4-26b-a4b-vllm-serve.modal.run | Not started |
| oss_qwen3_5_4b | qwen3.5-4b | llamaindex--qwen3-5-4b-inference-serve.modal.run | Not started |
| oss_gemma4_e4b | gemma-4-e4b | llamaindex--gemma4-e4b-vllm-serve.modal.run | Not started |

## VLLM API Key
Read from `.env`: `VLLM_API_KEY=llama-inf-key-dszccxsal2-sha2-djj3-78`
