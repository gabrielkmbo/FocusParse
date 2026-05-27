"""Build a slim review package for the FocusParse paper draft artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tarfile
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_RESULT_ROOT = Path("results/hf/paper/2026-05-24-paper-headline-v1")
DEFAULT_PACKAGE_ROOT = Path("results/paper/submission-review-package")
DEFAULT_INTERNAL_PACKAGE_NAME = "focusparse-paper-review-package-2026-05-24-v32"
DEFAULT_PUBLIC_METADATA_PACKAGE_NAME = "focusparse-paper-public-metadata-package-2026-05-26-v10"

DOC_FILES = [
    "focusparse-paper.md",
    "references.bib",
    "main.tex",
]

RESULT_FILES = [
    "README.md",
    "manifest.json",
    "git_commit.txt",
    "git_status.txt",
    "config/default.yaml",
    "diagnostics/headline-diagnosis.md",
    "diagnostics/headline-diagnosis.json",
    "headline/headline_table.json",
    "headline/headline_table.jsonl",
    "headline/headline_table.md",
    "headline/headline_table.csv",
    "headline/headline_table.html",
]

QUALITATIVE_DIRS = [
    ("results/paper/ablation-summary", "analysis/ablation-summary"),
    ("results/paper/mechanism-ablation", "analysis/mechanism-ablation"),
    ("results/hf/paper/ablation-smoke-no-expand-v1", "analysis/ablation-smoke/no-expand"),
    ("results/hf/paper/ablation-smoke-no-rerank-v1", "analysis/ablation-smoke/no-rerank"),
    ("results/hf/paper/ablation-smoke-retry-off-v1", "analysis/ablation-smoke/retry-off"),
    ("results/paper/failure-taxonomy", "analysis/failure-taxonomy"),
    ("results/paper/qualitative-figure-panels", "qualitative/figure-panels"),
    (
        "results/paper/qualitative-baseline-comparisons",
        "qualitative/baseline-comparisons",
    ),
    (
        "results/trace_viewer/paper-final-qualitative-assets",
        "qualitative/trace-viewer-assets",
    ),
]

PUBLIC_METADATA_DIRS = [
    ("results/paper/ablation-summary", "analysis/ablation-summary"),
    ("results/paper/mechanism-ablation", "analysis/mechanism-ablation"),
    ("results/hf/paper/ablation-smoke-no-expand-v1", "analysis/ablation-smoke/no-expand"),
    ("results/hf/paper/ablation-smoke-no-rerank-v1", "analysis/ablation-smoke/no-rerank"),
    ("results/hf/paper/ablation-smoke-retry-off-v1", "analysis/ablation-smoke/retry-off"),
    ("results/paper/failure-taxonomy", "analysis/failure-taxonomy"),
    (
        "results/paper/qualitative-baseline-comparisons",
        "qualitative/baseline-comparisons",
    ),
]

AGENT_EYES_LIGHT_FILES = [
    (
        "results/agent_eyes/paper-final-headline-qualitative-focus-full/index.html",
        "qualitative/agent-eyes-viewer/index.html",
    ),
    (
        "results/agent_eyes/paper-final-headline-qualitative-focus-full/agent_eyes_audit.jsonl",
        "qualitative/agent-eyes-viewer/agent_eyes_audit.jsonl",
    ),
]

MECHANISM_RUN_LIGHT_FILES = [
    (
        "results/hf/paper/ablation-no-expand-v1/focusparse_focus_agentic_multi_page_0b139a04.json",
        "results/mechanism-ablation/no-expand/focusparse_focus_agentic_multi_page_0b139a04.json",
    ),
    (
        "results/hf/paper/ablation-no-expand-v1/focusparse_focus_agentic_multi_page_0b139a04/run.json",
        "results/mechanism-ablation/no-expand/focusparse_focus_agentic_multi_page_0b139a04/run.json",
    ),
    (
        "results/hf/paper/ablation-no-expand-v1/focusparse_focus_agentic_multi_page_0b139a04/per_example.jsonl",
        "results/mechanism-ablation/no-expand/focusparse_focus_agentic_multi_page_0b139a04/per_example.jsonl",
    ),
    (
        "results/hf/paper/ablation-no-rerank-v1/focusparse_focus_agentic_multi_page_0b139a04.json",
        "results/mechanism-ablation/no-rerank/focusparse_focus_agentic_multi_page_0b139a04.json",
    ),
    (
        "results/hf/paper/ablation-no-rerank-v1/focusparse_focus_agentic_multi_page_0b139a04/run.json",
        "results/mechanism-ablation/no-rerank/focusparse_focus_agentic_multi_page_0b139a04/run.json",
    ),
    (
        "results/hf/paper/ablation-no-rerank-v1/focusparse_focus_agentic_multi_page_0b139a04/per_example.jsonl",
        "results/mechanism-ablation/no-rerank/focusparse_focus_agentic_multi_page_0b139a04/per_example.jsonl",
    ),
    (
        "results/hf/paper/ablation-verifier-off-v1/focusparse_focus_agentic_multi_page_0b139a04.json",
        "results/mechanism-ablation/verifier-off/focusparse_focus_agentic_multi_page_0b139a04.json",
    ),
    (
        "results/hf/paper/ablation-verifier-off-v1/focusparse_focus_agentic_multi_page_0b139a04/run.json",
        "results/mechanism-ablation/verifier-off/focusparse_focus_agentic_multi_page_0b139a04/run.json",
    ),
    (
        "results/hf/paper/ablation-verifier-off-v1/focusparse_focus_agentic_multi_page_0b139a04/per_example.jsonl",
        "results/mechanism-ablation/verifier-off/focusparse_focus_agentic_multi_page_0b139a04/per_example.jsonl",
    ),
    (
        "results/hf/paper/ablation-answer-shape-off-v1/focusparse_focus_agentic_multi_page_0b139a04.json",
        "results/mechanism-ablation/answer-shape-off/focusparse_focus_agentic_multi_page_0b139a04.json",
    ),
    (
        "results/hf/paper/ablation-answer-shape-off-v1/focusparse_focus_agentic_multi_page_0b139a04/run.json",
        "results/mechanism-ablation/answer-shape-off/focusparse_focus_agentic_multi_page_0b139a04/run.json",
    ),
    (
        "results/hf/paper/ablation-answer-shape-off-v1/focusparse_focus_agentic_multi_page_0b139a04/per_example.jsonl",
        "results/mechanism-ablation/answer-shape-off/focusparse_focus_agentic_multi_page_0b139a04/per_example.jsonl",
    ),
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_file(repo: Path, package: Path, src: str | Path, dst: str | Path) -> Path:
    source = repo / src
    if not source.is_file():
        raise FileNotFoundError(source)
    target = package / dst
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target


def copy_tree(repo: Path, package: Path, src: str | Path, dst: str | Path) -> None:
    source = repo / src
    if not source.is_dir():
        raise FileNotFoundError(source)
    target = package / dst
    if target.exists():
        raise FileExistsError(target)
    shutil.copytree(source, target)


def iter_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file())


def package_name_for_mode(release_mode: str) -> str:
    if release_mode == "public-metadata":
        return DEFAULT_PUBLIC_METADATA_PACKAGE_NAME
    return DEFAULT_INTERNAL_PACKAGE_NAME


def doc_files_for_mode(release_mode: str) -> list[str]:
    return DOC_FILES


def excludes_for_mode(release_mode: str, include_agent_eyes_examples: bool) -> list[str]:
    excludes = [
        "large per-example prediction payload directories",
        "large tile directories from the full headline result package",
    ]
    if release_mode == "public-metadata":
        excludes.extend(
            [
                "compiled paper PDF because it may embed uncleared source-derived figures",
                "qualitative figure panel PNGs",
                "trace-viewer page renders, crops, and N-up tile images",
                "agent-eyes viewer files and example HTML",
                "full source PDFs",
            ]
        )
    elif not include_agent_eyes_examples:
        excludes.append(
            "full agent-eyes HTML examples unless --include-agent-eyes-examples is used"
        )
    return excludes


def build_manifest(
    package: Path,
    repo: Path,
    result_root: Path,
    release_mode: str,
    include_agent_eyes_examples: bool,
) -> dict[str, object]:
    files = []
    for path in iter_files(package):
        if path.name == "manifest.json":
            continue
        files.append(
            {
                "path": path.relative_to(package).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "release_mode": release_mode,
        "repo_root": repo.as_posix(),
        "source_result_root": result_root.as_posix(),
        "purpose": "Slim paper review package for FocusParse/parser-bench submission preparation.",
        "excludes": excludes_for_mode(release_mode, include_agent_eyes_examples),
        "files": files,
    }


def write_readme(
    package: Path,
    result_root: Path,
    release_mode: str,
    included_agent_eyes_examples: bool,
) -> None:
    agent_eyes_note = (
        "The package includes the full agent-eyes example HTML files."
        if included_agent_eyes_examples
        else (
            "The package includes only the agent-eyes index and audit JSONL; "
            "the full HTML examples remain in the source workspace because they are large."
        )
    )
    if release_mode == "public-metadata":
        qualitative_note = (
            "This public-metadata package intentionally excludes compiled PDFs and "
            "source-derived page, crop, tile, and figure-panel images. It keeps "
            "paper sources, result metadata, diagnostics, per-example rows, and "
            "text/CSV analysis artifacts."
        )
        agent_eyes_note = (
            "Agent-eyes viewer files and example HTML are excluded in public-metadata mode."
        )
    else:
        qualitative_note = (
            "It includes composed qualitative figure panels and the lighter trace-viewer "
            "crop/page asset bundle for the qualitative examples."
        )
    readme = f"""# FocusParse Paper Review Package

Generated from `{result_root.as_posix()}`.

Release mode: `{release_mode}`.

This is a slim package for paper review and submission preparation. It includes:

- paper draft sources and bibliography;
- final headline tables, diagnostics, config, git snapshot, and result manifest;
- every method's `run.json` and `per_example.jsonl`;
- no-expand, no-rerank, verifier-repair, and answer-shape-repair mechanism ablation `run.json` and `per_example.jsonl`;
- same-revision qualitative baseline comparisons;
- venue-template conversion audit for the next official author kit;
- NeurIPS-style checklist prep with draft reproducibility/disclosure answers;
- compute/resource disclosure for the headline sweep;
- archival snapshot readiness notes and archive sidecar checksum policy;
- source-PDF terms manifest and derived-image release audit;

It intentionally excludes the full 4+ GB headline result payload containing
large tile and prediction directories.

{qualitative_note}

{agent_eyes_note}

Use `manifest.json` for file-level checksums.
"""
    (package / "README.md").write_text(readme, encoding="utf-8")


def create_archive(package: Path) -> Path:
    archive = package.with_suffix(".tar.gz")
    if archive.exists():
        raise FileExistsError(archive)
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(package, arcname=package.name)
    checksum_path = archive.with_suffix(archive.suffix + ".sha256")
    if checksum_path.exists():
        raise FileExistsError(checksum_path)
    checksum_path.write_text(f"{sha256_file(archive)}  {archive.name}\n", encoding="utf-8")
    return archive


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result-root", type=Path, default=DEFAULT_RESULT_ROOT)
    parser.add_argument("--paper-doc-root", type=Path, default=Path("docs/paper"))
    parser.add_argument("--output-root", type=Path, default=DEFAULT_PACKAGE_ROOT)
    parser.add_argument("--package-name", default=None)
    parser.add_argument(
        "--release-mode",
        choices=("internal-review", "public-metadata"),
        default="internal-review",
        help=(
            "internal-review keeps source-derived qualitative image assets; "
            "public-metadata excludes compiled PDFs and source-derived images."
        ),
    )
    parser.add_argument(
        "--include-agent-eyes-examples",
        action="store_true",
        help="Also include the large agent-eyes example HTML files.",
    )
    parser.add_argument("--no-archive", action="store_true", help="Skip .tar.gz creation.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repo = Path.cwd()
    result_root = args.result_root
    output_root = args.output_root
    package_name = args.package_name or package_name_for_mode(args.release_mode)
    package = output_root / package_name
    if package.exists():
        raise FileExistsError(package)
    package.mkdir(parents=True)

    if args.release_mode == "public-metadata" and args.include_agent_eyes_examples:
        raise ValueError("--include-agent-eyes-examples is not valid with public-metadata mode")

    for doc in doc_files_for_mode(args.release_mode):
        copy_file(repo, package, args.paper_doc_root / doc, Path("paper-docs") / doc)

    for result in RESULT_FILES:
        copy_file(repo, package, result_root / result, Path("results/headline") / result)

    headline_root = repo / result_root / "headline"
    method_dirs = sorted(path for path in headline_root.iterdir() if path.is_dir())
    for method_dir in method_dirs:
        for filename in ("run.json", "per_example.jsonl"):
            copy_file(
                repo,
                package,
                method_dir.relative_to(repo) / filename,
                Path("results/methods") / method_dir.name / filename,
            )

    package_dirs = (
        PUBLIC_METADATA_DIRS if args.release_mode == "public-metadata" else QUALITATIVE_DIRS
    )
    for src, dst in package_dirs:
        copy_tree(repo, package, src, dst)

    if args.release_mode == "internal-review":
        for src, dst in AGENT_EYES_LIGHT_FILES:
            copy_file(repo, package, src, dst)

    for src, dst in MECHANISM_RUN_LIGHT_FILES:
        copy_file(repo, package, src, dst)

    if args.include_agent_eyes_examples:
        copy_tree(
            repo,
            package,
            "results/agent_eyes/paper-final-headline-qualitative-focus-full/examples",
            "qualitative/agent-eyes-viewer/examples",
        )

    write_readme(package, result_root, args.release_mode, args.include_agent_eyes_examples)
    manifest = build_manifest(
        package,
        repo,
        result_root,
        args.release_mode,
        args.include_agent_eyes_examples,
    )
    (package / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    archive = None if args.no_archive else create_archive(package)
    checksum_path = archive.with_suffix(archive.suffix + ".sha256") if archive else None
    print(
        json.dumps(
            {
                "package": package.as_posix(),
                "archive": archive.as_posix() if archive else None,
                "archive_sha256": sha256_file(archive) if archive else None,
                "archive_sha256_file": checksum_path.as_posix() if checksum_path else None,
            }
        )
    )


if __name__ == "__main__":
    main()
