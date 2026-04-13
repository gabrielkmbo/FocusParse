"""Shared pytest fixtures for FocusParse tests."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture(scope="session")
def parser_bench_submodule_present() -> bool:
    return (REPO_ROOT / "third_party" / "parser-bench" / "src" / "utils" / "schema.py").exists()
