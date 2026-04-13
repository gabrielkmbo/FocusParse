---
description: Audit generated QA quality with parallel review subagents
---

# Audit QA Quality

Review generated benchmark candidates for quality issues using parallel subagents that each check a different dimension.

## Process:

1. **Locate candidates:**
   - Default: `data/candidates/candidates.jsonl`
   - If `$ARGUMENTS` specifies a different file, use that
   - Count total candidates and report

2. **Sample candidates for review:**
   - Read a random sample (30-50 items) from the candidates file
   - Group by document and question family for balanced coverage

3. **Launch parallel audit subagents:**

   **Agent 1 — Trivial question detection:**
   - Check for questions answerable from a single table cell or one line of OCR
   - Flag questions that are simple lookups with no reasoning required
   - Report count and examples of trivial questions that slipped through

   **Agent 2 — Evidence coverage audit:**
   - Check that bbox annotations actually cover relevant content
   - Verify supporting pages match where the answer evidence lives
   - Flag items where evidence seems insufficient or misaligned

   **Agent 3 — Diversity analysis:**
   - Check distribution of question families (comparison, trend, cross-ref, etc.)
   - Check distribution across documents and domains
   - Flag if any single doc or family dominates the dataset
   - Report region type coverage (tables, charts, figures, text)

   **Agent 4 — Duplicate and near-duplicate check:**
   - Look for questions with high text overlap that survived dedup
   - Check for questions targeting the same bbox set
   - Flag semantic duplicates (different wording, same answer)

4. **Synthesize audit report:**
   ```
   Total candidates: N
   Sample reviewed: M

   Trivial questions found: X (Y%)
   Evidence misalignment: X items
   Near-duplicates missed: X pairs
   
   Family distribution:
     comparison: N%  |  trend: N%  |  cross-ref: N%  | ...

   Domain distribution:
     finance: N%  |  datasheet: N%

   Top issues to address:
   1. [most impactful finding]
   2. [second finding]
   ```

5. **Suggest fixes:**
   - If trivial questions are common: suggest tightening teacher prompts
   - If evidence is misaligned: suggest checking layout detection quality
   - If duplicates remain: suggest lowering dedup thresholds
   - If distribution is skewed: suggest rebalancing generation targets
