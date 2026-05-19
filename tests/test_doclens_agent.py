"""Tests for the faithful DocLens-style comparator."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from focusparse.models.base import ModelResponse
from focusparse.pipeline.doclens_agent import (
    DocLensAgent,
    _CandidateElement,
    _extract_json_obj,
    _parse_answer_sample,
    _parse_pages_response,
)


class _ScriptedClient:
    def __init__(self, texts: list[str]) -> None:
        self._texts = list(texts)
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
            {
                "prompt": prompt,
                "images": images,
                "system": system,
                "max_tokens": max_tokens,
            }
        )
        text = self._texts[idx] if idx < len(self._texts) else self._texts[-1]
        return ModelResponse(
            text=text,
            tokens_in=100 + idx,
            tokens_out=20 + idx,
            usd=0.001,
            latency_ms=50,
        )

    def count_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)


def _example():
    return SimpleNamespace(
        id="ex-doclens",
        domain="datasheet",
        source_pdf="fake.pdf",
        page_images=[
            "fake_page_0001_300dpi.png",
            "fake_page_0002_300dpi.png",
            "fake_page_0003_300dpi.png",
        ],
        question="What is the configured output current?",
        answer="42 mA",
        answer_type="string",
        supporting_pages=[3],
        supporting_bboxes=[],
        difficulty={"visual": 1, "reasoning": 1, "localization": 1},
        question_family="single_value_lookup",
    )


def _images(tmp_path: Path) -> list[Path]:
    return [
        tmp_path / "fake_page_0001_300dpi.png",
        tmp_path / "fake_page_0002_300dpi.png",
        tmp_path / "fake_page_0003_300dpi.png",
    ]


async def test_doclens_unions_navigation_and_adjudicates_disagreement(
    tmp_path,
):
    client = _ScriptedClient(
        [
            '{"pages": [2], "rationale": "possible table"}',
            '{"pages": [3], "rationale": "independent pass finds label"}',
            '{"elements": [{"ref": "cand_000", "reason": "likely answer"}]}',
            '{"answer": "40 mA", "evidence_refs": ["ev_000"]}',
            '{"answer": "42 mA", "evidence_refs": ["ev_000"]}',
            '{"selected": 1, "answer": "42 mA", "evidence_refs": ["ev_000"]}',
        ]
    )
    agent = DocLensAgent(backend_client=client, answer_samples=2)

    result = await agent.run(_example(), _images(tmp_path))

    assert result.answer == "42 mA"
    assert result.citations == [
        {
            "page": 2,
            "bbox": [0.0, 0.0, 1.0, 1.0],
            "evidence_ref": "ev_000",
            "source": "doclens",
        }
    ]
    assert len(client.calls) == 6

    stages = [step.stage for step in result.trace.steps]
    assert stages[:2] == ["route_pages", "route_pages"]
    assert "answer_sampling" in stages
    assert stages[-1] == "adjudication"

    doclens_meta = result.telemetry["doclens"]
    assert doclens_meta["page_navigation"]["selected_pages"] == [2, 3]
    assert doclens_meta["answer_sampling"]["sample_count"] == 2
    assert doclens_meta["adjudication"]["method"] == "llm_adjudicator"
    assert result.telemetry["stage_diagnostics"]["element_localization"]["selected_count"] == 1


async def test_doclens_majority_vote_skips_adjudicator_call(
    tmp_path,
):
    client = _ScriptedClient(
        [
            '{"pages": [3]}',
            '{"pages": [3]}',
            '{"elements": [{"ref": "cand_000"}]}',
            '{"answer": "42 mA", "evidence_refs": ["ev_000"]}',
            '{"answer": "42 mA", "evidence_refs": ["ev_000"]}',
        ]
    )
    agent = DocLensAgent(backend_client=client, answer_samples=2)

    result = await agent.run(_example(), _images(tmp_path))

    assert result.answer == "42 mA"
    assert len(client.calls) == 5
    assert result.trace.steps[-1].action == "majority_vote"
    assert result.telemetry["doclens"]["adjudication"]["method"] == "majority_vote"


def test_parse_pages_response_filters_to_valid_pages():
    pages = _parse_pages_response(
        '{"pages": [9, "3", 3, 1]}',
        valid_pages=[1, 2, 3],
        max_pages=2,
    )

    assert pages == [3, 1]


def test_parse_answer_sample_maps_evidence_refs_to_citations():
    evidence = {
        "ev_000": _CandidateElement(
            ref="ev_000",
            page=7,
            bbox=(0.1, 0.2, 0.3, 0.4),
            label="table",
        )
    }

    sample = _parse_answer_sample('{"answer": "yes", "evidence_refs": ["ev_000"]}', evidence)

    assert sample.answer == "yes"
    assert sample.citations == [
        {
            "page": 7,
            "bbox": [0.1, 0.2, 0.3, 0.4],
            "evidence_ref": "ev_000",
            "source": "doclens",
        }
    ]


def test_extract_json_obj_uses_first_object_when_response_concatenates_json():
    obj = _extract_json_obj(
        '{"pages": [2], "rationale": "candidate"}'
        '{"pages": [3], "rationale": "extra speculative object"}'
    )

    assert obj == {"pages": [2], "rationale": "candidate"}


def test_extract_json_obj_skips_leading_non_json_text():
    obj = _extract_json_obj('Thought: inspect first\n{"answer": "42 mA"}')

    assert obj == {"answer": "42 mA"}


def test_run_hf_eval_argparse_accepts_doclens(monkeypatch):
    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "scripts" / "run_hf_eval.py"
    spec = importlib.util.spec_from_file_location("_run_hf_eval_doclens_test", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    monkeypatch.setattr(
        sys,
        "argv",
        ["run_hf_eval.py", "--protocol", "agentic_multi_page", "--agent", "doclens"],
    )

    args = module._parse_args()
    assert args.agent == "doclens"
