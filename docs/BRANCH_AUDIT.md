# Hanging Branch Audit

Date: 2026-05-27

Main was first checkpointed at `021969d` (`checkpoint: save paper experiment
state`). Then refs were refreshed with `git fetch --all --prune`; the stale
remote `origin/codex/inspect-expand-page-image-fallback` was pruned.

## Decision

No hanging branch was merged into the public mainline during this cleanup. The
current `main` already contains the reproducible seven-method headline harness
used by the raw-verified May 24 paper table. The unmerged branches below are
useful historical references, but merging them now would mix older appendix
prototypes and a partly unverified 66.9% checkpoint into the simpler public
path.

## Branches With Unique Work

| Branch | Unique work | Decision |
| --- | --- | --- |
| `codex/exp-basic-vlm-protocols` | Appendix protocol registry and `scripts/run_related_work_protocols.py`. | Leave as historical appendix scaffolding. |
| `codex/exp-llamaindex-react` | Official LlamaIndex ReAct comparator adapter and tests. | Leave branch-local for now; current paper table uses repo-native ReAct rows. |
| `codex/exp-coding-agent` | Coding-agent comparator with full +4 tool belt. | Leave branch-local; appendix proxy, not part of public quickstart. |
| `codex/exp-doclens-baseline` | DocLens-style faithful proxy and related CLI wiring. | Leave branch-local; proxy row depends on older related-work monitor. |
| `codex/exp-agenticocr-baseline` | AgenticOCR-style faithful-lite proxy. | Leave branch-local; useful for appendix, not a headline dependency. |
| `codex/exp-related-work-monitor` | Related-work monitor snapshots around a 66.9% FocusParse checkpoint. | Leave branch-local because the 66.9% row is documented but not raw-verified in this checkout. |
| `codex/harness-60-accuracy` | Older answer-shape and layout changes from the 60% sprint. | Leave stale; later harness work is already merged or superseded. |
| `codex/set-research-north-star` | Agent config and handoff scaffolding. | Do not promote into public repo. |

## Already Merged Or Superseded

Branches such as `codex/harness-65plus-iteration`,
`codex/headline-machine-artifacts`,
`codex/chart-to-table-tool-orchestration`, `harness-60plus-phase3f`,
`phase3b-self-consistency`, `phase6a-exact-match-tightening`, and
`phase7-chart-to-table-llm` are already merged into main history or superseded
by the May 24 paper package.

## Recovery

If an appendix release needs one of the proxy comparators, recover it from the
named branch and integrate it deliberately behind a separate documented
experiment path.
