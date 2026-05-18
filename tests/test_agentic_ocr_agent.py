"""Tests for the AgenticOCR-style faithful-lite comparator."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from focusparse.eval.metrics import AggregateMetrics
from focusparse.models.base import ModelResponse
from focusparse.pipeline.agentic_ocr_agent import AgenticOCRStyleAgent
from focusparse.tools.get_text_layer import GetTextLayerInput, GetTextLayerOutput
from focusparse.tools.inspect_region import InspectRegionInput, InspectRegionOutput

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_hf_eval.py"


class _ScriptedClient:
    def __init__(self, scripted_texts: list[str]) -> None:
        self._scripted = list(scripted_texts)
        self.calls: list[dict[str, Any]] = []

    async def predict(
        self,
        prompt: str,
        images: list[Path] | None = None,
        system: str | None = None,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        idx = len(self.calls)
        self.calls.append(
            {"prompt": prompt, "images": images, "system": system, "max_tokens": max_tokens}
        )
        text = self._scripted[idx] if idx < len(self._scripted) else self._scripted[-1]
        return ModelResponse(text=text, tokens_in=100, tokens_out=20, usd=0.001, latency_ms=50)

    def count_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)


def _example():
    return SimpleNamespace(
        id="ex-agentic-ocr",
        domain="datasheet",
        source_pdf="fake.pdf",
        page_images=["fake_page_0001.png", "fake_page_0002.png"],
        question="What is the output voltage?",
        answer="42 V",
        answer_type="string",
        tolerance=None,
        supporting_pages=[2],
        supporting_bboxes=[SimpleNamespace(page=2, x0=0.10, y0=0.10, x1=0.30, y1=0.30)],
        difficulty=SimpleNamespace(visual=1, reasoning=1, localization=1),
        question_family="single_value_lookup",
    )


def _pdf(tmp_path: Path) -> Path:
    path = tmp_path / "fake.pdf"
    path.write_bytes(b"%PDF-1.4\n% fake test pdf\n")
    return path


def _images(tmp_path: Path) -> list[Path]:
    return [
        tmp_path / "summary.png",
        tmp_path / "fake_page_0001_300dpi.png",
        tmp_path / "fake_page_0002_300dpi.png",
    ]


def _inspect_stub(tmp_path: Path):
    calls: list[InspectRegionInput] = []

    async def _run(inp: InspectRegionInput, **_kwargs: Any) -> InspectRegionOutput:
        calls.append(inp)
        crop = tmp_path / f"crop_{len(calls)}.png"
        crop.write_bytes(b"fake png bytes")
        return InspectRegionOutput(
            crop_ref=str(crop),
            ocr_text="Output voltage: 42 V",
            confidence=0.91,
            latency_ms=7,
            page_width_px=1000,
            page_height_px=1000,
        )

    return _run, calls


def _text_stub(text_by_page: dict[int, str]):
    calls: list[GetTextLayerInput] = []

    async def _run(inp: GetTextLayerInput, **_kwargs: Any) -> GetTextLayerOutput:
        calls.append(inp)
        text = text_by_page.get(inp.page, "")
        return GetTextLayerOutput(text=text, source="native" if text else "empty_native")

    return _run, calls


async def test_agentic_ocr_rejects_lazy_crop_then_records_evidence(tmp_path):
    inspect_func, inspect_calls = _inspect_stub(tmp_path)
    text_func, _ = _text_stub({})
    client = _ScriptedClient(
        [
            '{"action":"element","page":2,"bbox_norm":[0,0,1,1],"rationale":"too broad"}',
            '{"action":"element","page":2,"bbox_norm":[0.10,0.10,0.30,0.30],'
            '"rationale":"target voltage line"}',
            '{"action":"final","final_answer":"42 V","citations":[{"page":2,'
            '"bbox":[0.10,0.10,0.30,0.30],"evidence_ref":"agenticocr_pkt_000"}]}',
        ]
    )
    agent = AgenticOCRStyleAgent(
        backend_client=client,
        inspect_region_func=inspect_func,
        get_text_layer_func=text_func,
    )

    result = await agent.run(_example(), _images(tmp_path), pdf_path=_pdf(tmp_path))

    assert result.answer == "42 V"
    assert len(inspect_calls) == 1
    assert inspect_calls[0].mode == "element"
    meta = result.telemetry["agentic_ocr"]
    assert meta["lazy_crop_count"] == 1
    assert meta["rejected_crop_count"] == 1
    assert meta["inspected_crop_count"] == 1
    assert result.citations[0]["evidence_ref"] == "agenticocr_pkt_000"
    assert result.trace.evidence_snapshot
    assert result.trace.evidence_snapshot[0].local_crop_ref
    assert any(step.action == "crop_rejected" for step in result.trace.steps)


async def test_agentic_ocr_skips_duplicate_overlapping_crop(tmp_path):
    inspect_func, inspect_calls = _inspect_stub(tmp_path)
    text_func, _ = _text_stub({})
    client = _ScriptedClient(
        [
            '{"action":"image","page":2,"bbox_norm":[0.10,0.10,0.30,0.30]}',
            '{"action":"region","page":2,"bbox_norm":[0.11,0.11,0.31,0.31]}',
            '{"action":"final","final_answer":"42 V","citations":[]}',
        ]
    )
    agent = AgenticOCRStyleAgent(
        backend_client=client,
        inspect_region_func=inspect_func,
        get_text_layer_func=text_func,
    )

    result = await agent.run(_example(), _images(tmp_path), pdf_path=_pdf(tmp_path))

    assert len(inspect_calls) == 1
    meta = result.telemetry["agentic_ocr"]
    assert meta["duplicate_crop_count"] == 1
    assert meta["rejected_crop_count"] == 1
    assert result.citations == [
        {"page": 2, "bbox": [0.1, 0.1, 0.3, 0.3], "evidence_ref": "agenticocr_pkt_000"}
    ]


async def test_agentic_ocr_uses_text_layer_only_for_page_hints(tmp_path):
    inspect_func, _ = _inspect_stub(tmp_path)
    text_func, text_calls = _text_stub(
        {
            1: "Absolute maximum ratings and package information.",
            2: "Electrical characteristics list output voltage as 42 V.",
        }
    )
    client = _ScriptedClient(
        [
            '{"action":"element","page":2,"bbox_norm":[0.10,0.10,0.30,0.30]}',
            '{"action":"final","final_answer":"42 V","citations":[]}',
        ]
    )
    agent = AgenticOCRStyleAgent(
        backend_client=client,
        inspect_region_func=inspect_func,
        get_text_layer_func=text_func,
    )

    result = await agent.run(_example(), _images(tmp_path), pdf_path=_pdf(tmp_path))

    assert [call.page for call in text_calls] == [1, 2]
    assert "Top page hints" in client.calls[0]["prompt"]
    assert "page 2" in client.calls[0]["prompt"]
    assert "output voltage" in client.calls[0]["prompt"].lower()
    assert result.telemetry["agentic_ocr"]["inspected_crop_count"] == 1


async def test_agentic_ocr_missing_pdf_abstains(tmp_path):
    client = _ScriptedClient(['{"action":"final","final_answer":"42 V"}'])
    agent = AgenticOCRStyleAgent(backend_client=client)

    result = await agent.run(_example(), _images(tmp_path), pdf_path=None)

    assert result.answer == "Unanswerable"
    assert result.telemetry["agentic_ocr"]["missing_pdf_path"] is True
    assert client.calls == []


def _load_script_module():
    spec = importlib.util.spec_from_file_location("_run_hf_eval_agentic_ocr_test", SCRIPT_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_run_hf_eval_accepts_agentic_ocr_and_exposes_tool_metrics(monkeypatch):
    script = _load_script_module()
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_hf_eval.py", "--protocol", "agentic_multi_page", "--agent", "agentic_ocr"],
    )
    args = script._parse_args()
    assert args.agent == "agentic_ocr"
    assert script._protocol_matches_agent("agentic_ocr", "agentic_multi_page") is True

    from focusparse.eval.schemas import EvalRunResults, PerProtocolResults

    wrapped = script._wrap_results(
        {
            "aggregate": AggregateMetrics(
                n=1,
                accuracy=1.0,
                page_recall_mean=1.0,
                bbox_iou_mean=0.5,
                evidence_reward_mean=0.4,
                lazy_answer_rate=0.0,
                tool_calls_mean=2.0,
                tokens_in_mean=10.0,
                tokens_out_mean=5.0,
                latency_ms_mean=20.0,
                usd_total=0.01,
                usd_per_correct=0.01,
            ),
            "per_example": [{"answer_pred": "42 V"}],
        },
        config_key="focusparse_agentic_ocr_agentic_multi_page_deadbeef",
        agent="agentic_ocr",
        protocol="agentic_multi_page",
        tier_sha8="deadbeef",
        resolved_tiers={},
        hf_repo="gabrielbo/parser-bench",
        hf_split="validation",
        hf_revision=None,
        fingerprint={},
        schemas=(EvalRunResults, PerProtocolResults),
    )
    assert wrapped.overall.evidence_reward_mean == 0.4
    assert wrapped.overall.lazy_answer_rate == 0.0
    assert wrapped.overall.tool_calls_mean == 2.0
