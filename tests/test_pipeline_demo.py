from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from focusparse.traces.pipeline_demo import (
    CURATED_EXAMPLE_IDS,
    crop_page_image,
    load_benchmark_lookup,
    normalize_bbox,
    select_example_ids,
    write_static_bundle,
)


def test_select_default_examples_filters_available_and_limits() -> None:
    records = [
        {"example_id": CURATED_EXAMPLE_IDS[1]},
        {"example_id": "not-curated"},
        {"example_id": CURATED_EXAMPLE_IDS[0]},
    ]

    assert select_example_ids(records) == [CURATED_EXAMPLE_IDS[0], CURATED_EXAMPLE_IDS[1]]
    assert select_example_ids(records, limit=1) == [CURATED_EXAMPLE_IDS[0]]


def test_select_requested_examples_preserves_order() -> None:
    records = [{"example_id": "a"}, {"example_id": "b"}]

    assert select_example_ids(records, requested_example_ids=["b", "missing", "a"]) == ["b", "a"]


def test_load_benchmark_lookup_parses_string_bboxes(tmp_path: Path) -> None:
    path = tmp_path / "benchmark.jsonl"
    row = {
        "id": "ex-1",
        "question": "What value is shown?",
        "answer": "42",
        "supporting_pages": "[3]",
        "supporting_bboxes": json.dumps([{"page": 3, "x0": 10, "y0": 20, "x1": 50, "y1": 80}]),
    }
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")

    lookup = load_benchmark_lookup(path)

    assert lookup["ex-1"]["question"] == "What value is shown?"
    assert lookup["ex-1"]["supporting_pages"] == [3]
    assert lookup["ex-1"]["supporting_bboxes"][0]["x1"] == 50


def test_normalize_bbox_accepts_pixel_coordinates() -> None:
    bbox = {"x0": 10, "y0": 20, "x1": 50, "y1": 80}

    assert normalize_bbox(bbox, (100, 100)) == [0.1, 0.2, 0.5, 0.8]


def test_crop_page_image_writes_png(tmp_path: Path) -> None:
    page = tmp_path / "page.png"
    output = tmp_path / "crop.png"
    Image.new("RGB", (20, 20), color="white").save(page)

    assert crop_page_image(page, [0.25, 0.25, 0.75, 0.75], output)
    assert output.is_file()

    with Image.open(output) as crop:
        assert crop.size[0] > 0
        assert crop.size[1] > 0


def test_write_static_bundle_shape(tmp_path: Path) -> None:
    data = {
        "stageOrder": ["plan"],
        "stageMeta": {"plan": {"label": "PLAN"}},
        "run": {},
        "examples": [],
    }

    write_static_bundle(data, tmp_path)

    assert (tmp_path / "index.html").is_file()
    assert (tmp_path / "assets" / "styles.css").is_file()
    assert (tmp_path / "assets" / "demo-data.js").is_file()
    assert (tmp_path / "assets" / "demo.js").is_file()
    assert (tmp_path / "vercel.json").is_file()
    assert "window.FOCUSPARSE_DEMO_DATA" in (tmp_path / "assets" / "demo-data.js").read_text()
