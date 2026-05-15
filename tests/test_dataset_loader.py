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


def test_hf_split_name_maps_legacy_local_names():
    from focusparse.dataset.loader import hf_split_name

    assert hf_split_name("dev") == "train"
    assert hf_split_name("test") == "validation"
    assert hf_split_name("holdout") == "test"
    assert hf_split_name("validation") == "validation"


def test_row_to_example_normalizes_current_hf_shape(parser_bench_submodule_present):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required for schema")
    from focusparse.dataset.loader import _row_to_example

    ex = _row_to_example(
        {
            "id": "dat-smoke-0001",
            "domain": "datasheet",
            "source_pdf": "smoke.pdf",
            "page_images": [object()],
            "question": "What is the value?",
            "answer": "1",
            "answer_type": "numeric",
            "answer_unit": None,
            "tolerance": None,
            "supporting_pages": "[1]",
            "supporting_bboxes": "[]",
            "alternate_bboxes": "[]",
            "evidence_relations": "[]",
            "multi_region_required": False,
            "requires_visual": True,
            "difficulty_visual": 2,
            "difficulty_reasoning": 1,
            "difficulty_localization": 3,
            "question_family": "smoke",
            "stress_type": "none",
            "original_bboxes": "[]",
            "split": "dev",
            "reasoning_chain": None,
            "evidence_page_spread": 0,
            "distractor_region_ids": "[]",
            "adversarial_type": None,
        }
    )

    assert ex.page_images == []
    assert ex.difficulty.visual == 2
    assert ex.supporting_pages == [1]


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
