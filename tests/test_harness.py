"""Tests for `focusparse.eval.harness.run_simple_eval`.

Uses a fake backend client (no network) and in-memory examples. Gated on the
parser-bench submodule because `BenchmarkExample` is needed to construct
inputs and `BBox` is needed for scoring.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from focusparse.eval.harness import _prepare_images, run_simple_eval
from focusparse.models.base import ModelResponse


class _FakeClient:
    def __init__(self, response_text: str) -> None:
        self._text = response_text
        self.calls = 0

    async def predict(
        self,
        prompt: str,
        images: list[Path] | None = None,
        system: str | None = None,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        self.calls += 1
        return ModelResponse(
            text=self._text,
            tokens_in=100,
            tokens_out=10,
            usd=0.0012,
            latency_ms=50,
        )

    def count_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)


def _make_example(example_id: str, answer: str = "5.5"):
    from focusparse._parser_bench import BBox, BenchmarkExample

    return BenchmarkExample(
        id=example_id,
        domain="datasheet",
        source_pdf="datasheet-A.pdf",
        page_images=[f"images/{example_id}_page_0003.png"],
        question="What is the max supply voltage?",
        answer=answer,
        answer_type="numeric",
        answer_unit="V",
        tolerance=0.01,
        supporting_pages=[3],
        supporting_bboxes=[BBox(page=3, x0=0.1, y0=0.2, x1=0.3, y1=0.4)],
        alternate_bboxes=[],
        evidence_relations=[],
        multi_region_required=False,
        requires_visual=True,
        difficulty={"visual": 2, "reasoning": 1, "localization": 3},
        question_family="min_typ_max_disambiguation",
        stress_type="none",
        reasoning_chain=None,
        evidence_page_spread=0,
        adversarial_type=None,
        split="dev",
        original_bboxes=[],
    )


# ---------------------------------------------------------------------------
# _prepare_images
# ---------------------------------------------------------------------------


def test_prepare_images_full_doc(tmp_path, parser_bench_submodule_present):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")

    example = _make_example("ex-1")
    paths = _prepare_images(example, protocol="full_doc", images_root=tmp_path)
    assert len(paths) == 1
    assert paths[0] == tmp_path / "images" / "ex-1_page_0003.png"


def test_prepare_images_oracle_page(tmp_path, parser_bench_submodule_present):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")

    example = _make_example("ex-1")
    paths = _prepare_images(example, protocol="oracle_page", images_root=tmp_path)
    # One supporting page → one image (the prefix matching supporting_pages length).
    assert len(paths) == 1


def test_prepare_images_oracle_crop_generates_crop(tmp_path, parser_bench_submodule_present):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")

    example = _make_example("ex-crop")
    img_path = tmp_path / "images" / "ex-crop_page_0003.png"
    img_path.parent.mkdir(parents=True)
    Image.new("RGB", (800, 600), color=(128, 128, 128)).save(img_path)

    paths = _prepare_images(example, protocol="oracle_crop", images_root=tmp_path)
    assert len(paths) == 1
    # Output is in .oracle_crops/<example_id>/page_NNNN.png, not the source image.
    assert ".oracle_crops" in str(paths[0])
    assert paths[0].exists()

    with Image.open(paths[0]) as out:
        # bbox normalized [0.1, 0.2] → [0.3, 0.4] of an 800x600 source:
        # (80, 120) → (240, 240) → 160×120 crop.
        assert out.size == (160, 120)


def test_prepare_images_rejects_unknown_protocol(tmp_path, parser_bench_submodule_present):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")

    example = _make_example("ex-1")
    with pytest.raises(ValueError):
        _prepare_images(example, protocol="bogus", images_root=tmp_path)


# ---------------------------------------------------------------------------
# run_simple_eval end-to-end (mocked client, no network)
# ---------------------------------------------------------------------------


async def test_run_simple_eval_scores_correct_answer(tmp_path, parser_bench_submodule_present):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")

    # Correct numeric answer + plausible citations
    client = _FakeClient(
        '{"answer": "5.5", "citations": [{"page": 3, "bbox": [0.1, 0.2, 0.3, 0.4]}]}'
    )
    examples = [_make_example("ex-a"), _make_example("ex-b")]

    result = await run_simple_eval(
        examples,
        backend_client=client,
        backend="fake",
        model="fake-1",
        protocol="full_doc",
        output_dir=tmp_path / "run",
        images_root=tmp_path,
        limit=2,
    )

    agg = result["aggregate"]
    assert agg.n == 2
    # Both answers match gold → accuracy = 1.0
    assert agg.accuracy == 1.0
    # USD should aggregate two calls
    assert agg.usd_total == pytest.approx(0.0024)
    assert agg.usd_per_correct == pytest.approx(0.0012)

    # Manifest written.
    manifest = json.loads((tmp_path / "run" / "run.json").read_text())
    assert manifest["agent"] == "simple"
    assert manifest["backend"] == "fake"
    assert manifest["protocol"] == "full_doc"
    assert manifest["n_examples"] == 2

    # Per-example JSONL written.
    lines = (tmp_path / "run" / "per_example.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2
    for line in lines:
        rec = json.loads(line)
        assert rec["answer_correct"] == 1.0
        assert rec["bbox_iou"] > 0.9


async def test_run_simple_eval_lazy_answer_zero_reward(tmp_path, parser_bench_submodule_present):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")

    # Correct answer but no citations → evidence_reward must be 0 (lazy)
    client = _FakeClient('{"answer": "5.5", "citations": []}')
    examples = [_make_example("ex-lazy")]

    result = await run_simple_eval(
        examples,
        backend_client=client,
        backend="fake",
        model="fake-1",
        protocol="full_doc",
        output_dir=tmp_path / "run",
        images_root=tmp_path,
        limit=1,
    )
    agg = result["aggregate"]
    assert agg.accuracy == 1.0  # answer matches
    assert agg.evidence_reward_mean == 0.0  # lazy penalty zeros it
    assert agg.lazy_answer_rate == 1.0


async def test_run_simple_eval_resume_hits_cache(tmp_path, parser_bench_submodule_present):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")

    client = _FakeClient('{"answer": "5.5", "citations": []}')
    examples = [_make_example("ex-a"), _make_example("ex-b")]

    run_dir = tmp_path / "run"
    await run_simple_eval(
        examples,
        backend_client=client,
        backend="fake",
        model="fake-1",
        protocol="full_doc",
        output_dir=run_dir,
        images_root=tmp_path,
        limit=2,
    )
    first_calls = client.calls
    assert first_calls == 2

    # Second call with the same output_dir → cache hit, no new API calls.
    examples2 = [_make_example("ex-a"), _make_example("ex-b")]
    await run_simple_eval(
        examples2,
        backend_client=client,
        backend="fake",
        model="fake-1",
        protocol="full_doc",
        output_dir=run_dir,
        images_root=tmp_path,
        limit=2,
        resume=True,
    )
    assert client.calls == first_calls  # no new calls


async def test_run_simple_eval_handles_backend_error(tmp_path, parser_bench_submodule_present):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")

    class _BrokenClient:
        async def predict(self, *a: Any, **kw: Any) -> ModelResponse:
            raise RuntimeError("simulated provider outage")

        def count_tokens(self, text: str) -> int:
            return 1

    examples = [_make_example("ex-err")]
    result = await run_simple_eval(
        examples,
        backend_client=_BrokenClient(),
        backend="fake",
        model="fake-1",
        protocol="full_doc",
        output_dir=tmp_path / "run",
        images_root=tmp_path,
        limit=1,
    )
    # Run should still complete; metrics aggregate reflects the failure row.
    agg = result["aggregate"]
    assert agg.n == 1
    assert agg.accuracy == 0.0
    per = result["per_example"][0]
    assert per["error"].startswith("simulated")


async def test_run_simple_eval_aborts_on_provider_throttle(
    tmp_path, parser_bench_submodule_present
):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")

    class _RateLimitedClient:
        async def predict(self, *a: Any, **kw: Any) -> ModelResponse:
            raise RuntimeError("429 Too Many Requests: rate_limit_error")

        def count_tokens(self, text: str) -> int:
            return 1

    with pytest.raises(RuntimeError, match="rate_limit_error"):
        await run_simple_eval(
            [_make_example("ex-quota")],
            backend_client=_RateLimitedClient(),
            backend="fake",
            model="fake-1",
            protocol="full_doc",
            output_dir=tmp_path / "run",
            images_root=tmp_path,
            limit=1,
        )

    assert not (tmp_path / "run" / "per_example.jsonl").exists()


# ---------------------------------------------------------------------------
# Phase 2: page mapping + IoU coord-space wiring for the simple agent
# ---------------------------------------------------------------------------


def test_remap_positional_pages_remaps_one_indexed(parser_bench_submodule_present):
    """Model emits page=1 for the only image; harness remaps to source page 50."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    from focusparse.eval.harness import _remap_positional_pages

    citations = [{"page": 1, "bbox": [0.1, 0.2, 0.3, 0.4]}]
    out = _remap_positional_pages(citations, image_pages=[50])
    assert out[0]["page"] == 50
    assert out[0]["bbox"] == [0.1, 0.2, 0.3, 0.4]  # bbox untouched


def test_remap_positional_pages_idempotent_when_already_source(parser_bench_submodule_present):
    """Citation already uses source page 50 — leave alone, don't double-remap."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    from focusparse.eval.harness import _remap_positional_pages

    citations = [{"page": 50, "bbox": [0.1, 0.2, 0.3, 0.4]}]
    out = _remap_positional_pages(citations, image_pages=[50])
    assert out[0]["page"] == 50


def test_remap_positional_pages_multi_image(parser_bench_submodule_present):
    """For [page=1,page=2] with image_pages=[50,12], remap to [50,12]."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    from focusparse.eval.harness import _remap_positional_pages

    citations = [
        {"page": 1, "bbox": [0, 0, 1, 1]},
        {"page": 2, "bbox": [0, 0, 1, 1]},
    ]
    out = _remap_positional_pages(citations, image_pages=[50, 12])
    assert [c["page"] for c in out] == [50, 12]


def test_remap_positional_pages_noop_when_image_pages_none(parser_bench_submodule_present):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    from focusparse.eval.harness import _remap_positional_pages

    citations = [{"page": 1, "bbox": [0, 0, 1, 1]}]
    out = _remap_positional_pages(citations, image_pages=None)
    assert out == citations


def test_ordered_pages_for_images_parses_filename(tmp_path, parser_bench_submodule_present):
    """`Arm_EE382N_4_page_0050_300dpi.png` → 50."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    from focusparse.eval.harness import _ordered_pages_for_images

    example = _make_example("ex-pg")
    img = tmp_path / "Arm_EE382N_4_page_0050_300dpi.png"
    img.write_bytes(b"fake")
    pages = _ordered_pages_for_images(example, [img], protocol="full_doc")
    assert pages == [50]


def test_ordered_pages_for_images_falls_back_to_supporting_pages(
    tmp_path, parser_bench_submodule_present
):
    """No `_page_NNNN_` in filename → fall back to supporting_pages."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    from focusparse.eval.harness import _ordered_pages_for_images

    example = _make_example("ex-fb")  # supporting_pages=[3]
    img = tmp_path / "anonymous.png"
    img.write_bytes(b"fake")
    pages = _ordered_pages_for_images(example, [img], protocol="oracle_page")
    assert pages == [3]


@pytest.mark.asyncio
async def test_run_simple_eval_remaps_positional_citation(tmp_path, parser_bench_submodule_present):
    """Model returns page=1; harness remaps to gold page 3 → page_recall=1.0."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")

    img_path = tmp_path / "datasheet-A_page_0003_300dpi.png"
    Image.new("RGB", (200, 300), color=(255, 255, 255)).save(img_path)
    examples = [_make_example("ex-remap").model_copy(update={"page_images": [str(img_path)]})]
    # Model emits a perfect numeric answer with positional page=1
    response_json = '{"answer": "5.5", "citations": [{"page": 1, "bbox": [0.1, 0.2, 0.3, 0.4]}]}'
    client = _FakeClient(response_text=response_json)
    result = await run_simple_eval(
        examples,
        backend_client=client,
        backend="fake",
        model="fake-1",
        protocol="full_doc",
        output_dir=tmp_path / "run",
        images_root=tmp_path,
        limit=1,
    )
    per = result["per_example"][0]
    # page_recall now 1.0 because page=1 was remapped to source page 3.
    assert per["page_recall"] == 1.0
    # Citation in the record reflects the remap.
    assert per["citations"][0]["page"] == 3
