# FocusParse Bibliography Readiness Audit

Date: 2026-05-24

Status: bibliography and citation-key audit for the current paper draft package.
This file separates what is ready from what still needs Zotero, archival
metadata, or venue-policy decisions.

## Current Zotero Status

Zotero was retried on 2026-05-24 using the local helper:

```bash
python3 /Users/gabrielbo/.codex/plugins/cache/openai-curated/zotero/6188456f/skills/zotero/scripts/zotero.py status --json
```

Result:

```json
{
  "profile": null,
  "prefs_file": null,
  "local_api_enabled_pref": null,
  "api_running": false,
  "api_error": "<urlopen error [Errno 61] Connection refused>",
  "connector_running": false,
  "connector_error": "<urlopen error [Errno 61] Connection refused>",
  "base_url": "http://127.0.0.1:23119"
}
```

Attempting to launch the desktop app from macOS failed:

```bash
open -a Zotero
```

Result:

```text
Unable to find application named 'Zotero'
```

The common app locations were also checked on 2026-05-24:

```bash
ls -ld /Applications/Zotero.app
ls -ld /Users/gabrielbo/Applications/Zotero.app
```

Both paths were absent.

Interpretation:

Zotero export is blocked by local app availability, not just by a disabled API
preference. The paper package should continue to use primary-source BibTeX
until Zotero Desktop is installed or made available on this profile.

## Citation-Key Coverage

Current draft files checked:

```text
docs/research/paper-draft/focusparse-submission-draft.md
docs/research/paper-draft/focusparse-paper-draft.md
```

Current bibliography file:

```text
docs/research/paper-draft/references.bib
```

Result:

- 18 unique citation keys are used by the two paper drafts.
- All 18 used keys are present in `references.bib`.
- `references.bib` contains 20 entries total.
- The two extra entries are `focusparse2026` and `parserbench_gabrielbo2026`.

The extra artifact entries are intentional. They should be cited only after the
target venue's anonymity, artifact, and archival-reference rules are selected.
For a double-blind submission, the public GitHub/HF entries may need to move to
an anonymized supplementary artifact or be replaced with a post-review citation.

## Current Used Citation Keys

| Key | Bibliography status | Paper role |
| --- | --- | --- |
| `agenticocr2026` | Present | Closest query-conditioned parsing / on-demand visual extraction work. |
| `doclens2025` | Present | Closest long visual-document tool-agent comparison. |
| `parsebench2026` | Present | External ParseBench benchmark; explicitly distinct from Gabriel parser-bench. |
| `mpdocbenchparse2026` | Present | Multi-page document parsing benchmark; useful current contrast for document-level parsing versus query-conditioned QA evidence construction. |
| `omnidocbench2025` | Present | Broad PDF parsing benchmark context. |
| `doclaynet2022` | Present | Layout-analysis benchmark context. |
| `gtefintabnet2021` | Present | Financial table structure recognition lineage. |
| `docvqa2021` | Present | Document VQA foundation. |
| `infographicvqa2021` | Present | Infographic/document visual reasoning foundation. |
| `mmlongbenchdoc2024` | Present | Long-context document understanding benchmark. |
| `finragbenchv2025` | Present | Multimodal financial RAG with visual citation. |
| `finqa2021` | Present | Financial numerical reasoning. |
| `tatqa2021` | Present | Hybrid financial table/text QA. |
| `financebench2023` | Present | Financial open-book QA over filings. |
| `react2023` | Present | Generic reasoning/action comparator family. |
| `chartqa2022` | Present | Chart QA with visual/logical reasoning. |
| `plotqa2020` | Present | Plot QA / numeric visual answer lineage. |
| `pubtabnet2020` | Present | Image-based table recognition lineage. |

## Bibliography Quality Gates

Before submission:

1. Install or start Zotero Desktop on this machine/profile and rerun the helper
   status command.
2. Export or sync the Zotero-backed BibTeX and diff it against
   `references.bib`.
3. Preserve the current primary-source citation keys unless the venue style or
   Zotero export requires a deliberate key migration.
4. Decide whether `focusparse2026` and `parserbench_gabrielbo2026` are allowed
   in the submitted paper or need anonymized artifact handling.
5. Add model/provider citations or model-card references only after the final
   result table fixes the exact model set.
6. Replace moving GitHub/HF URLs with commit, dataset revision, software DOI,
   or archived URLs wherever venue policy permits.

## Commands Used

```bash
rg -o "@[A-Za-z0-9_:-]+" \
  docs/research/paper-draft/focusparse-submission-draft.md \
  docs/research/paper-draft/focusparse-paper-draft.md \
  | sed 's/.*@//' | sort -u

rg -o '^@[a-zA-Z]+\{[^,]+' docs/research/paper-draft/references.bib \
  | sed 's/^@[^{]*{//' | sort -u
```
