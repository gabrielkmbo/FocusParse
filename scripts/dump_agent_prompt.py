"""Dump the agent-facing tool block to stdout.

Useful for iterating on tool descriptions / chaining notes without firing
up an eval. Prints what an LLM would see in the system prompt for a given
`--tool-set` and `--mode`.

Usage:

    uv run python scripts/dump_agent_prompt.py --tool-set full --mode careful
    uv run python scripts/dump_agent_prompt.py --tool-set minimal --mode generic
"""

from __future__ import annotations

import argparse

from focusparse.tools import format_agent_tool_block, resolve_tool_set


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tool-set", choices=["minimal", "full"], default="full")
    ap.add_argument("--mode", choices=["careful", "generic"], default="careful")
    args = ap.parse_args()

    tools = resolve_tool_set(args.tool_set)
    print(format_agent_tool_block(tools, mode=args.mode))


if __name__ == "__main__":
    main()
