"""NFS (llama-nfs) rsync helpers.

Mirrors parser-bench's `scripts/run_generate.py::_rsync` contract:
- SSH host alias `llama-nfs` (must exist in ~/.ssh/config).
- Flags `-a -z` (archive + compress). No `--delete` — NFS is the canonical copy.
- macOS openrsync lacks `--protect-args`, so we manually `shlex.quote` the
  remote path to keep spaces and special chars safe.
"""

from __future__ import annotations

import logging
import shlex
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_HOST = "llama-nfs"
DEFAULT_REMOTE_ROOT = (
    "/home/osx-user/shared-experiments/llamacloud-bench-ci/data/parser-bench"
)


def _rsync(src: str, dst: str, flags: list[str] | None = None) -> None:
    flags = flags or ["-a", "-z"]
    cmd = ["rsync", *flags, src, dst]
    logger.info("rsync: %s", " ".join(shlex.quote(p) for p in cmd))
    subprocess.run(cmd, check=True)


def rsync_pull(
    doc_name: str,
    local_dir: Path | str,
    *,
    host: str = DEFAULT_HOST,
    remote_root: str = DEFAULT_REMOTE_ROOT,
    subpath: str = "processed",
) -> None:
    """Pull a single processed-doc directory from NFS to `local_dir/<doc_name>/`."""
    local_dir = Path(local_dir)
    local_dir.mkdir(parents=True, exist_ok=True)
    remote = f"{host}:{shlex.quote(f'{remote_root}/{subpath}/{doc_name}/')}"
    _rsync(remote, str(local_dir / f"{doc_name}/"))


def rsync_push(
    doc_name: str,
    local_dir: Path | str,
    *,
    host: str = DEFAULT_HOST,
    remote_root: str = DEFAULT_REMOTE_ROOT,
    subpath: str = "processed",
) -> None:
    """Push a locally processed doc back to NFS."""
    local_dir = Path(local_dir)
    src = str(local_dir / f"{doc_name}/")
    remote = f"{host}:{shlex.quote(f'{remote_root}/{subpath}/{doc_name}/')}"
    _rsync(src, remote)
