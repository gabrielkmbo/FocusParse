---
description: Process multiple documents in parallel with subagents
---

# Process Documents in Parallel

Run preprocessing and/or QA generation for multiple documents using parallel subagents.

## Process:

1. **Determine what to process:**
   - If `$ARGUMENTS` specifies paths or domains, use those
   - Otherwise scan `data/raw/` for unprocessed PDFs and `data/processed/` for docs needing generation
   - Check `data/candidates/candidates.jsonl` for already-completed docs to skip

2. **Plan the work:**
   - List documents to process
   - Estimate disk usage (warn if large PDFs on a nearly-full disk)
   - Check `df -h` and warn if less than 10GB free
   - Group documents into batches suitable for parallel processing
   - Present the plan: "I'll process N documents in M parallel batches"

3. **Launch parallel subagents:**

   For **preprocessing** (raw PDF -> processed):
   - One agent per domain or per large PDF
   - Each runs:
     ```bash
     uv run python scripts/run_preprocess.py data/raw/<domain>/ --domain <domain>
     ```
   - For very large PDFs (1000+ pages), process one at a time with rsync between

   For **QA generation** (processed -> candidates):
   - One agent per document or small batch
   - Each runs:
     ```bash
     uv run python scripts/run_generate.py data/processed/<doc_stem>/
     ```
   - Add `--sync-nfs` if the user wants automatic NFS sync and local cleanup

4. **Monitor and report:**
   - As each agent completes, report success or failure
   - Track which documents produced candidates and how many
   - Flag any "Generated 0 candidates" for follow-up (suggest `/diagnose_pipeline`)

5. **Post-processing:**
   - Report total candidates generated
   - If `--sync-nfs` was used, confirm NFS sync completed
   - Suggest next steps: `/run_baselines` if benchmark is ready, or more processing if needed

## Important:
- Never process huge PDFs in parallel on a full disk — serialize those with rsync between each
- Resume logic in run_generate.py will skip docs already in candidates.jsonl
- Check disk space before and during processing with `du -sh data/processed/*`
- If a doc fails, continue with the rest — don't abort the whole batch
