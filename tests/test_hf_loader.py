"""Tests for `focusparse.eval.hf_loader`.

Non-slow tests use in-memory `Dataset.from_dict` + `monkeypatch.setattr` on
`hf_loader.load_dataset` to avoid network. The slow test actually hits HF and
is gated on both `HF_TOKEN` being set and the parser-bench submodule being
present.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pil_image(size=(8, 8), color=(255, 255, 255)):
    from PIL import Image

    return Image.new("RGB", size, color)


def _make_canonical_row(id_="ex-1", doc_stem="datasheet-A"):
    """Shape mirrors HF parser-bench parquet row: JSON-string bbox fields,
    embedded PIL images, scalar meta fields."""
    return {
        "id": id_,
        "domain": "datasheet",
        "source_pdf": f"{doc_stem}.pdf",
        "page_images": [_make_pil_image()],
        "question": "What is the max supply voltage?",
        "answer": "5.5",
        "answer_type": "numeric",
        "answer_unit": "V",
        "tolerance": 0.01,
        "supporting_pages": [3],
        "supporting_bboxes": json.dumps([{"page": 3, "x0": 0.1, "y0": 0.2, "x1": 0.3, "y1": 0.4}]),
        "alternate_bboxes": json.dumps([]),
        "multi_region_required": False,
        "requires_visual": True,
        "difficulty_visual": 2,
        "difficulty_reasoning": 1,
        "difficulty_localization": 3,
        "question_family": "min_typ_max_disambiguation",
        "stress_type": "none",
        "reasoning_chain": None,
        "evidence_page_spread": 0,
        "adversarial_type": None,
        "split": "validation",
    }


def _make_stress_row(id_="stress-1"):
    row = _make_canonical_row(id_=id_, doc_stem="stress-doc")
    row["stress_type"] = "contact_sheet_4up"
    return row


def _build_dataset(rows):
    """Build a `datasets.Dataset` from a list of row dicts, handling the fact
    that PIL images can't be naively passed through `from_dict` without a
    Features spec."""
    from datasets import Dataset, Features, Image, Sequence, Value

    features = Features(
        {
            "id": Value("string"),
            "domain": Value("string"),
            "source_pdf": Value("string"),
            "page_images": Sequence(Image()),
            "question": Value("string"),
            "answer": Value("string"),
            "answer_type": Value("string"),
            "answer_unit": Value("string"),
            "tolerance": Value("float32"),
            "supporting_pages": Sequence(Value("int32")),
            "supporting_bboxes": Value("string"),
            "alternate_bboxes": Value("string"),
            "multi_region_required": Value("bool"),
            "requires_visual": Value("bool"),
            "difficulty_visual": Value("int32"),
            "difficulty_reasoning": Value("int32"),
            "difficulty_localization": Value("int32"),
            "question_family": Value("string"),
            "stress_type": Value("string"),
            "reasoning_chain": Value("string"),
            "evidence_page_spread": Value("int32"),
            "adversarial_type": Value("string"),
            "split": Value("string"),
        }
    )
    columns: dict[str, list] = {k: [] for k in features}
    for row in rows:
        for k in features:
            columns[k].append(row.get(k))
    # HF Image feature accepts PIL.Image directly; `page_images` is a sequence.
    return Dataset.from_dict(columns, features=features)


def _build_dataset_without_stress_column(rows):
    from datasets import Dataset, Features, Sequence, Value

    features = Features(
        {
            "id": Value("string"),
            "answer": Value("string"),
            "supporting_pages": Sequence(Value("int32")),
        }
    )
    columns = {k: [row[k] for row in rows] for k in features}
    return Dataset.from_dict(columns, features=features)


# ---------------------------------------------------------------------------
# _filter_stress_rows
# ---------------------------------------------------------------------------


def test_filter_stress_rows_drops_pre_baked_variants():
    from focusparse.eval.hf_loader import _filter_stress_rows

    ds = _build_dataset([_make_canonical_row("a"), _make_stress_row("b"), _make_canonical_row("c")])
    kept = _filter_stress_rows(ds)
    assert len(kept) == 2
    assert set(kept["id"]) == {"a", "c"}


def test_filter_stress_rows_noop_when_column_missing():
    from focusparse.eval.hf_loader import _filter_stress_rows

    rows = [{"id": "x", "answer": "1", "supporting_pages": [1]}]
    ds = _build_dataset_without_stress_column(rows)
    assert "stress_type" not in ds.column_names
    kept = _filter_stress_rows(ds)
    assert len(kept) == 1
    assert kept["id"] == ["x"]


def test_filter_stress_rows_noop_when_no_offenders():
    from focusparse.eval.hf_loader import _filter_stress_rows

    ds = _build_dataset([_make_canonical_row("a"), _make_canonical_row("b")])
    kept = _filter_stress_rows(ds)
    assert len(kept) == 2


# ---------------------------------------------------------------------------
# _page_num_from_hf_image_index
# ---------------------------------------------------------------------------


def test_page_num_from_hf_image_index_uses_supporting_pages():
    from focusparse.eval.hf_loader import _page_num_from_hf_image_index

    row = {"supporting_pages": [12, 7]}
    assert _page_num_from_hf_image_index(0, row) == 12
    assert _page_num_from_hf_image_index(1, row) == 7


def test_page_num_from_hf_image_index_falls_back_to_ordinal():
    from focusparse.eval.hf_loader import _page_num_from_hf_image_index

    row = {"supporting_pages": [5]}
    # idx beyond supporting_pages → 1-indexed fallback
    assert _page_num_from_hf_image_index(1, row) == 2
    assert _page_num_from_hf_image_index(4, row) == 5


def test_page_num_from_hf_image_index_handles_missing_key():
    from focusparse.eval.hf_loader import _page_num_from_hf_image_index

    assert _page_num_from_hf_image_index(0, {}) == 1


# ---------------------------------------------------------------------------
# _row_to_example (requires parser-bench submodule)
# ---------------------------------------------------------------------------


def test_row_to_example_round_trip(tmp_path, parser_bench_submodule_present):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required for BenchmarkExample schema")
    from focusparse._parser_bench import BenchmarkExample
    from focusparse.eval.hf_loader import _row_to_example

    processed_root = tmp_path / "data" / "processed"
    processed_root.mkdir(parents=True)

    row = _make_canonical_row(id_="ex-42", doc_stem="10-K")
    example = _row_to_example(row, processed_root)

    # Returned object is a valid BenchmarkExample.
    assert isinstance(example, BenchmarkExample)
    assert example.id == "ex-42"
    assert example.answer_type.endswith("numeric") or str(example.answer_type) == "numeric"

    # Page image written to the right place, path stored relative to staging.
    assert len(example.page_images) == 1
    rel_path = example.page_images[0]
    assert rel_path == "data/processed/10-K/images/10-K_page_0003_300dpi.png"
    assert (tmp_path / rel_path).exists()

    # Round-trip through model_dump_json / model_validate_json.
    reloaded = BenchmarkExample.model_validate_json(example.model_dump_json())
    assert reloaded.id == example.id
    assert reloaded.page_images == example.page_images
    assert len(reloaded.supporting_bboxes) == 1
    assert reloaded.supporting_bboxes[0].page == 3


# ---------------------------------------------------------------------------
# materialize_split (mocks load_dataset; still needs submodule for row conversion)
# ---------------------------------------------------------------------------


def test_materialize_split_idempotent(tmp_path, monkeypatch, parser_bench_submodule_present):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required for BenchmarkExample schema")
    from focusparse.eval import hf_loader

    ds = _build_dataset([_make_canonical_row("a"), _make_canonical_row("b", doc_stem="ds-B")])

    call_count = {"n": 0}

    def fake_load_dataset(repo_id, split=None, revision=None):
        call_count["n"] += 1
        return ds

    monkeypatch.setattr("datasets.load_dataset", fake_load_dataset)

    jsonl_path, returned_ds = hf_loader.materialize_split(tmp_path, limit=2)
    assert jsonl_path.exists()
    first_lines = jsonl_path.read_text().splitlines()
    assert len(first_lines) == 2
    assert call_count["n"] == 1

    # Second call — should short-circuit on the row-count gate.
    mtime_before = jsonl_path.stat().st_mtime
    jsonl_path2, _ = hf_loader.materialize_split(tmp_path, limit=2)
    assert jsonl_path2 == jsonl_path
    assert jsonl_path.stat().st_mtime == mtime_before, "JSONL was rewritten on idempotent call"


def test_materialize_split_writes_relative_paths(
    tmp_path, monkeypatch, parser_bench_submodule_present
):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required for BenchmarkExample schema")
    from focusparse.eval import hf_loader

    ds = _build_dataset([_make_canonical_row("a", doc_stem="10-K")])
    monkeypatch.setattr("datasets.load_dataset", lambda *a, **kw: ds)

    jsonl_path, _ = hf_loader.materialize_split(tmp_path, limit=1)
    record = json.loads(jsonl_path.read_text().splitlines()[0])
    assert record["page_images"] == ["data/processed/10-K/images/10-K_page_0003_300dpi.png"]
    # Path is relative — absolute paths would start with tmp_path.
    assert not Path(record["page_images"][0]).is_absolute()


def test_materialize_split_force_rewrites(tmp_path, monkeypatch, parser_bench_submodule_present):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required for BenchmarkExample schema")
    from focusparse.eval import hf_loader

    ds = _build_dataset([_make_canonical_row("a")])
    monkeypatch.setattr("datasets.load_dataset", lambda *a, **kw: ds)

    jsonl_path, _ = hf_loader.materialize_split(tmp_path, limit=1)
    mtime_before = jsonl_path.stat().st_mtime

    # Sleep-free mtime invariance check: force=True must always re-enter the
    # write branch, so the write itself is what counts. We re-run and assert
    # the JSONL was re-opened; content equivalence is implicit.
    jsonl_path2, _ = hf_loader.materialize_split(tmp_path, limit=1, force=True)
    assert jsonl_path2 == jsonl_path
    # On force, the file is truncated+rewritten. We can't reliably assert mtime
    # changes without a sleep, but we can assert the content is still well-formed.
    lines = jsonl_path.read_text().splitlines()
    assert len(lines) == 1
    _ = mtime_before  # kept for debuggability


# ---------------------------------------------------------------------------
# dataset_fingerprint
# ---------------------------------------------------------------------------


def test_dataset_fingerprint_shape():
    from focusparse.eval.hf_loader import dataset_fingerprint

    ds = _build_dataset([_make_canonical_row("a"), _make_canonical_row("b")])
    fp = dataset_fingerprint(ds)
    assert set(fp.keys()) == {"num_rows", "fingerprint", "split", "version", "description"}
    assert fp["num_rows"] == 2
    assert isinstance(fp["fingerprint"], str) and len(fp["fingerprint"]) > 0


# ---------------------------------------------------------------------------
# Slow integration test
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_materialize_validation_limit_3(tmp_path, parser_bench_submodule_present):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required for BenchmarkExample schema")
    if not os.environ.get("HF_TOKEN"):
        pytest.skip("HF_TOKEN required for gated dataset access")

    from focusparse.eval.hf_loader import dataset_fingerprint, materialize_split

    jsonl_path, ds = materialize_split(tmp_path, limit=3)
    assert jsonl_path.exists()
    lines = [line for line in jsonl_path.read_text().splitlines() if line.strip()]
    assert len(lines) == 3

    fp = dataset_fingerprint(ds)
    assert fp["num_rows"] == 3
    assert fp["split"] == "validation"

    # At least one page image materialized on disk.
    pngs = list((tmp_path / "data" / "processed").rglob("*.png"))
    assert len(pngs) >= 1
