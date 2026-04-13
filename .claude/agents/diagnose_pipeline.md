---
description: Diagnose pipeline failures using parallel investigation subagents
---

# Diagnose Pipeline Failure

Investigate why document processing failed or produced poor results, using parallel subagents to check multiple failure modes simultaneously.

## When to use:
- "Generated 0 candidate examples" for a document
- Whole-page crops only (layout fell back to stub)
- Missing or empty evidence graph
- Verifier rejecting everything

## Process:

1. **Identify the problem document:**
   - If `$ARGUMENTS` names a doc, use that
   - Otherwise check recent logs or ask the user
   - Find the doc directory under `data/processed/`

2. **Launch parallel diagnostic subagents:**

   Spawn these agents concurrently:

   **Agent 1 — Layout health check:**
   - Check if `document.json` has `regions` populated
   - Count regions by type (table, figure, text, etc.)
   - Look for signs of stub fallback (single full-page region)
   - Check if the HF endpoint is reachable: look for HTTP errors in recent output
   - Check `HF_TOKEN` is set in `.env`

   **Agent 2 — Evidence graph inspection:**
   - Read the document's `document.json` and check graph connectivity
   - Count nodes and edges
   - Check if cross-page links exist
   - Look for isolated nodes with no edges (regions that couldn't link to anything)
   - Check if the graph is empty or trivially small

   **Agent 3 — QA generation and verifier audit:**
   - Look at `candidates.jsonl` for this doc's entries (if any)
   - Check if the teacher generated candidates that the verifier rejected
   - Look for patterns in rejections (all too easy? all unsupported?)
   - Check if deduplication removed everything
   - Review teacher/verifier prompt config in `configs/default.yaml`

   **Agent 4 — Preprocessing quality:**
   - Check if page images exist and are reasonable size
   - Check if OCR text is populated in `document.json` (not empty strings)
   - Look for corrupt or zero-byte images
   - Verify TESSERACT_CMD is set correctly

3. **Synthesize findings:**
   - Combine all agent results
   - Identify the root cause (usually one of: endpoint down, empty OCR, graph too sparse, verifier too strict)
   - Present a clear diagnosis with the fix:
     ```
     Root cause: [what went wrong]
     Evidence: [what the agents found]
     Fix: [specific action to take]
     ```

4. **Offer to fix:**
   - If the fix is a config change or rerun, offer to do it
   - If it's an infrastructure issue (endpoint down, missing token), tell the user what to check
