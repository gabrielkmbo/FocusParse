"""Hydrate a list of processed docs from llama-nfs to local disk.

Usage:
    uv run python scripts/fetch_nfs_processed.py <doc_id> [<doc_id> ...]
"""

from __future__ import annotations

import sys
from pathlib import Path

from focusparse.dataset.nfs import rsync_pull

LOCAL_PROCESSED = Path("data/processed")


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: fetch_nfs_processed.py <doc_id> [<doc_id> ...]", file=sys.stderr)
        sys.exit(2)
    LOCAL_PROCESSED.mkdir(parents=True, exist_ok=True)
    for doc_id in sys.argv[1:]:
        print(f"[fetch] pulling {doc_id}")
        rsync_pull(doc_id, LOCAL_PROCESSED)
    print("done")


if __name__ == "__main__":
    main()
