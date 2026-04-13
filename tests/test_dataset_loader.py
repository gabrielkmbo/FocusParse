"""Tests for the BenchmarkLoader.

The HF streaming test is marked slow (hits network). The local-path test uses
a fixture JSONL placeholder that will be added in Phase 1 final.
"""

from __future__ import annotations

import pytest


def test_loader_instantiation_hf():
    from focusparse.dataset.loader import BenchmarkLoader

    loader = BenchmarkLoader.from_hf(repo="gabrielbo/parser-bench")
    assert loader.source == "hf"
    assert loader.hf_repo == "gabrielbo/parser-bench"


def test_loader_instantiation_local(tmp_path):
    from focusparse.dataset.loader import BenchmarkLoader

    loader = BenchmarkLoader.from_local(tmp_path)
    assert loader.source == "local"
    assert loader.local_root == tmp_path


def test_loader_rejects_bad_source():
    from focusparse.dataset.loader import BenchmarkLoader

    with pytest.raises(ValueError):
        BenchmarkLoader(source="invalid")


@pytest.mark.slow
def test_hf_streaming_yields_examples(parser_bench_submodule_present):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required for schema")
    from focusparse.dataset.loader import BenchmarkLoader

    loader = BenchmarkLoader.from_hf()
    count = 0
    for ex in loader.iter_split("dev", limit=3):
        assert ex.id
        assert ex.question
        count += 1
    assert count == 3
