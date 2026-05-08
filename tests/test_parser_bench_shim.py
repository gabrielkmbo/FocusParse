"""Tests for parser-bench schema loading fallback."""

from __future__ import annotations

from pathlib import Path

from focusparse import _parser_bench as pb


def test_parser_bench_schema_fallback_accepts_hf_row_shape(tmp_path: Path) -> None:
    schema = pb._load_parser_bench_schema(tmp_path / "missing" / "schema.py")

    example = schema.BenchmarkExample.model_validate(
        {
            "id": "dat-example",
            "domain": "datasheet",
            "source_pdf": "datasheets/example.pdf",
            "page_images": ["dat-example/page_0001.png"],
            "question": "What is VCC max?",
            "answer": "3.6 V",
            "answer_type": "exact_match",
            "supporting_pages": [1],
            "supporting_bboxes": [{"page": 1, "x0": 10, "y0": 20, "x1": 30, "y1": 40}],
            "alternate_bboxes": [],
            "evidence_relations": [],
            "multi_region_required": False,
            "requires_visual": True,
            "difficulty": {"visual": 1, "reasoning": 1, "localization": 1},
            "question_family": "spec_table_cell_retrieval",
            "stress_type": "none",
            "original_bboxes": [],
            "split": "dev",
            "reasoning_chain": None,
            "evidence_page_spread": 0,
            "adversarial_type": None,
        }
    )

    assert example.id == "dat-example"
    assert example.domain.value == "datasheet"
    assert example.supporting_bboxes[0].x1 == 30
    assert schema.BenchmarkExample.model_validate_json(example.model_dump_json()).id == example.id
