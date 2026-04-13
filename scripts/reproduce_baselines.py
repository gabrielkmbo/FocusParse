"""Reproduce parser-bench's published single-shot baselines.

Runs `focus eval --agent simple` across {gemini-3.1-pro-preview, claude-opus-4-6,
gpt-5.4} × {full_doc, oracle_page, oracle_crop} on the dev split and diffs
against a pinned baseline JSON. A PR that breaks the ±1 pt gate must update the
pinned JSON and explain why in the PR body.

TODO(Phase 1 final): wire the actual runs + diff table.
"""

from __future__ import annotations


def main() -> None:
    raise NotImplementedError("reproduce_baselines — wire in Phase 1 final commit")


if __name__ == "__main__":
    main()
