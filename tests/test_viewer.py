"""Tests for src/focusparse/traces/viewer.py."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from focusparse.traces.viewer import (
    build_view_model,
    example_id_to_doc_stem,
    find_page_image,
    image_to_data_url,
    render_html,
    resolve_crop_ref,
)

# Tiny 1x1 PNG (transparent) — enough to pass "looks like a PNG" sniff.
_TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6300010000000500010d0a2db40000000049454e44ae42"
    "6082"
)


@pytest.fixture
def tiny_png(tmp_path: Path) -> Path:
    p = tmp_path / "crop.png"
    p.write_bytes(_TINY_PNG)
    return p


# ---------------------------------------------------------------------------
# Resolution helpers
# ---------------------------------------------------------------------------


def test_example_id_to_doc_stem_datasheet() -> None:
    assert example_id_to_doc_stem("dat-AN040_EN-0008") == "AN040_EN"


def test_example_id_to_doc_stem_finance_with_dashes() -> None:
    assert example_id_to_doc_stem("fin-10-K-0010") == "10-K"


def test_example_id_to_doc_stem_unknown_prefix() -> None:
    assert example_id_to_doc_stem("misc-abc-0001") == "misc-abc"


def test_find_page_image_missing_returns_none(tmp_path: Path) -> None:
    assert find_page_image("dat-AN040_EN-0008", page=6, staging_root=tmp_path) is None


def test_find_page_image_resolves_via_canonical_layout(tmp_path: Path) -> None:
    images = tmp_path / "data" / "processed" / "AN040_EN" / "images"
    images.mkdir(parents=True)
    target = images / "AN040_EN_page_0006_300dpi.png"
    target.write_bytes(_TINY_PNG)
    found = find_page_image("dat-AN040_EN-0008", page=6, staging_root=tmp_path)
    assert found == target


def test_resolve_crop_ref_literal_path(tiny_png: Path) -> None:
    assert resolve_crop_ref(str(tiny_png), search_dirs=[]) == tiny_png


def test_resolve_crop_ref_via_search_dir(tmp_path: Path, tiny_png: Path) -> None:
    cache = tmp_path / "crops"
    cache.mkdir()
    name = "abc123"
    (cache / f"{name}.png").write_bytes(_TINY_PNG)
    found = resolve_crop_ref(name, search_dirs=[cache])
    assert found == cache / f"{name}.png"


def test_resolve_crop_ref_returns_none_for_missing() -> None:
    assert resolve_crop_ref("does_not_exist", search_dirs=[]) is None


def test_resolve_crop_ref_handles_none() -> None:
    assert resolve_crop_ref(None, search_dirs=[]) is None


def test_image_to_data_url_round_trip(tiny_png: Path) -> None:
    url = image_to_data_url(tiny_png)
    assert url.startswith("data:image/png;base64,")
    payload = url.split(",", 1)[1]
    assert base64.b64decode(payload) == _TINY_PNG


# ---------------------------------------------------------------------------
# View model + render
# ---------------------------------------------------------------------------


def _record_with_snapshot(crop_ref: str | None) -> dict:
    return {
        "example_id": "dat-Foo-0001",
        "domain": "DATASHEET",
        "protocol": "agentic_multi_page",
        "answer_pred": "42",
        "answer_gold": "42",
        "answer_correct": 1.0,
        "is_lazy": 0,
        "page_recall": 1.0,
        "bbox_iou": 0.5,
        "evidence_reward": 0.5,
        "tool_calls": 1,
        "tokens_in": 100,
        "tokens_out": 5,
        "usd": 0.001,
        "latency_ms": 800,
        "citations": [{"page": 1, "bbox": [0.0, 0.0, 0.5, 0.5]}],
        "trace": {
            "question": "What is the answer?",
            "steps": [
                {
                    "step_index": 0,
                    "stage": "answer",
                    "tier": "frontier",
                    "action": "llm_call",
                    "tool": None,
                    "args": {"n_packets": 1},
                    "obs_summary": "model said 42",
                    "tokens_in": 100,
                    "tokens_out": 5,
                    "usd": 0.001,
                    "latency_ms": 800,
                    "confidence": 0.9,
                }
            ],
            "evidence_snapshot": [
                {
                    "packet_id": "pkt_000",
                    "page": 1,
                    "bbox_norm": [0.0, 0.0, 0.5, 0.5],
                    "region_type": "picture",
                    "local_crop_ref": crop_ref,
                    "linked_crop_refs": [],
                    "text_layer_snippet": None,
                    "ocr_snippet": None,
                    "confidence": 0.9,
                    "provenance_tool": "deterministic_inspector",
                }
            ],
        },
    }


def test_build_view_model_inlines_crops(tmp_path: Path, tiny_png: Path) -> None:
    record = _record_with_snapshot(crop_ref=str(tiny_png))
    view = build_view_model(record, search_dirs=[], staging_root=tmp_path)
    snap = view["evidence_snapshot"][0]
    assert snap["crop_data_url"] is not None
    assert snap["crop_data_url"].startswith("data:image/png;base64,")


def test_build_view_model_handles_unresolvable_crop(tmp_path: Path) -> None:
    record = _record_with_snapshot(crop_ref="missing_ref")
    view = build_view_model(record, search_dirs=[tmp_path], staging_root=tmp_path)
    snap = view["evidence_snapshot"][0]
    assert snap["crop_data_url"] is None


def test_build_view_model_attaches_page_image_when_present(tmp_path: Path) -> None:
    images = tmp_path / "data" / "processed" / "Foo" / "images"
    images.mkdir(parents=True)
    (images / "Foo_page_0001_300dpi.png").write_bytes(_TINY_PNG)
    record = _record_with_snapshot(crop_ref=None)
    view = build_view_model(record, search_dirs=[], staging_root=tmp_path)
    pages = view["pages"]
    assert len(pages) == 1
    assert pages[0]["image_data_url"] is not None


def test_render_html_includes_question_and_payload(tmp_path: Path, tiny_png: Path) -> None:
    record = _record_with_snapshot(crop_ref=str(tiny_png))
    view = build_view_model(record, search_dirs=[], staging_root=tmp_path)
    html_str = render_html(view, title="my-trace")
    # Title interpolated.
    assert "my-trace" in html_str
    # Question + answer text injected.
    assert "What is the answer?" in html_str
    # Step summary visible to JS.
    assert "model said 42" in html_str
    # Tailwind CDN script tag present.
    assert "cdn.tailwindcss.com" in html_str


def test_render_html_handles_missing_evidence_snapshot(tmp_path: Path) -> None:
    record = {
        "example_id": "ex1",
        "answer_pred": "x",
        "answer_gold": "x",
        "answer_correct": 1.0,
        "trace": {"question": "Q?", "steps": [], "evidence_snapshot": None},
        "citations": [],
    }
    view = build_view_model(record, search_dirs=[], staging_root=tmp_path)
    html_str = render_html(view)
    # Should render without errors and embed a JSON payload.
    assert "evidence_snapshot" in html_str
    # The JSON payload must parse round-trip.
    start = html_str.index("const VIEW = ") + len("const VIEW = ")
    end = html_str.index("};\n", start) + 1
    parsed = json.loads(html_str[start:end])
    assert parsed["example_id"] == "ex1"
