"""Pull the source PDFs needed for staged benchmark examples from llama-nfs.

The HF dataset (`gabrielbo/parser-bench`) ships only page images. PDFs live
on `llama-nfs:/home/osx-user/shared-experiments/llamacloud-bench-ci/data/
parser-bench/raw/{datasheets,finance}/`. This script reads the staged
benchmark.jsonl, finds every unique `source_pdf` it references, and
rsyncs each one to `~/.cache/focusparse/pdfs/` (or a custom dest).

Idempotent: skips PDFs that already exist locally with non-zero size.
Reports per-doc success/failure so partial-pulls are visible at a glance.

Usage:
    uv run python scripts/source_pdfs_from_nfs.py
    uv run python scripts/source_pdfs_from_nfs.py --dest ~/my-pdfs
    uv run python scripts/source_pdfs_from_nfs.py --staging-dir <path>
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path

_DEFAULT_NFS_HOST = "llama-nfs"
_DEFAULT_NFS_ROOT = "/home/osx-user/shared-experiments/llamacloud-bench-ci/data/parser-bench/raw"
_DEFAULT_STAGING = Path.home() / ".cache" / "focusparse" / "hf_staging"
_DEFAULT_DEST = Path.home() / ".cache" / "focusparse" / "pdfs"

# Map our domain enum / string values to NFS subdirectory names.
_DOMAIN_TO_NFS_SUBDIR = {
    "datasheet": "datasheets",
    "Domain.DATASHEET": "datasheets",
    "finance": "finance",
    "Domain.FINANCE": "finance",
}


def main() -> int:
    args = _parse_args()
    bench_path = args.staging_dir / "benchmark.jsonl"
    if not bench_path.exists():
        print(f"error: {bench_path} not found. Run run_hf_eval.py first.", file=sys.stderr)
        return 2

    needed = _read_needed_pdfs(bench_path)
    if not needed:
        print("warning: no source_pdf entries found in staging benchmark.jsonl")
        return 0

    args.dest.mkdir(parents=True, exist_ok=True)
    print(f"Source: {args.nfs_host}:{args.nfs_root}/<domain>/<pdf>")
    print(f"Dest:   {args.dest}")
    print(f"PDFs needed: {len(needed)}")
    print()

    n_skipped = 0
    n_pulled = 0
    n_failed = 0
    for pdf_name, domain in sorted(needed.items()):
        local = args.dest / pdf_name
        if local.exists() and local.stat().st_size > 0 and not args.force:
            print(f"  [skip] {pdf_name} (already at {local}, {local.stat().st_size:,}b)")
            n_skipped += 1
            continue

        nfs_subdir = _DOMAIN_TO_NFS_SUBDIR.get(domain)
        if nfs_subdir is None:
            # Try both domains as a fallback — the domain field should cover it
            # but sometimes wrappers stringify the enum differently.
            for candidate in ("datasheets", "finance"):
                if _try_rsync(
                    pdf_name,
                    nfs_subdir=candidate,
                    nfs_host=args.nfs_host,
                    nfs_root=args.nfs_root,
                    dest=args.dest,
                ):
                    n_pulled += 1
                    break
            else:
                print(
                    f"  [fail] {pdf_name} (unknown domain {domain!r}; not in datasheets/ or finance/)"
                )
                n_failed += 1
            continue

        ok = _try_rsync(
            pdf_name,
            nfs_subdir=nfs_subdir,
            nfs_host=args.nfs_host,
            nfs_root=args.nfs_root,
            dest=args.dest,
        )
        if ok:
            n_pulled += 1
        else:
            n_failed += 1

    print()
    print(f"Done: {n_pulled} pulled, {n_skipped} skipped, {n_failed} failed.")
    return 0 if n_failed == 0 else 1


def _read_needed_pdfs(bench_path: Path) -> dict[str, str]:
    """Return {source_pdf: domain} for every example in the JSONL."""
    needed: dict[str, str] = {}
    for line in bench_path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        pdf = row.get("source_pdf")
        domain = row.get("domain") or ""
        if pdf and pdf not in needed:
            needed[pdf] = str(domain)
    return needed


def _try_rsync(
    pdf_name: str,
    *,
    nfs_subdir: str,
    nfs_host: str,
    nfs_root: str,
    dest: Path,
) -> bool:
    """rsync one PDF; return True on success."""
    # macOS openrsync lacks --protect-args; quote remote path manually.
    remote_path = shlex.quote(f"{nfs_root}/{nfs_subdir}/{pdf_name}")
    src = f"{nfs_host}:{remote_path}"
    dst = str(dest) + "/"
    cmd = ["rsync", "-az", src, dst]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        print(f"  [fail] {pdf_name} (rsync timeout after 120s)")
        return False

    if proc.returncode != 0:
        # 23 = "partial transfer due to error" — usually file-not-found on the
        # remote side. Surface the specific error so the user can chase it.
        msg = (proc.stderr.strip().splitlines() or [""])[-1][-200:]
        print(f"  [fail] {pdf_name} (rsync rc={proc.returncode}: {msg})")
        return False

    local = dest / pdf_name
    if not local.exists() or local.stat().st_size == 0:
        print(f"  [fail] {pdf_name} (rsync succeeded but file missing/empty)")
        return False

    print(f"  [ok]   {pdf_name} ({local.stat().st_size:,}b from {nfs_subdir}/)")
    return True


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--staging-dir", type=Path, default=_DEFAULT_STAGING)
    p.add_argument("--dest", type=Path, default=_DEFAULT_DEST)
    p.add_argument("--nfs-host", type=str, default=_DEFAULT_NFS_HOST)
    p.add_argument("--nfs-root", type=str, default=_DEFAULT_NFS_ROOT)
    p.add_argument(
        "--force",
        action="store_true",
        help="Re-pull PDFs even when a local copy exists.",
    )
    return p.parse_args()


if __name__ == "__main__":
    sys.exit(main())
