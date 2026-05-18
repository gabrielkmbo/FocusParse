"""Tests for the official LlamaIndex ReAct comparator adapter."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from focusparse.eval.harness import run_comparator_eval
from focusparse.models.base import ModelResponse
from focusparse.pipeline.llamaindex_react_agent import LlamaIndexReActAgent
from focusparse.pipeline.workflow import WorkflowResult
from focusparse.tools import (
    GET_TEXT_LAYER_SPEC,
    INSPECT_REGION_SPEC,
    LAYOUT_DETECT_SPEC,
    RUN_PYTHON_SPEC,
    ToolSpec,
    resolve_tool_set,
)
from focusparse.traces.recorder import TrajectoryRecorder, TrajectoryStep

REPO_ROOT = Path(__file__).resolve().parent.parent
RUN_HF_EVAL = REPO_ROOT / "scripts" / "run_hf_eval.py"
RUN_HEADLINE_EVAL = REPO_ROOT / "scripts" / "run_headline_eval.py"


class _ScriptedClient:
    """ModelClient that returns a fixed sequence of responses."""

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
        return ModelResponse(text=text, tokens_in=100, tokens_out=25, usd=0.002, latency_ms=80)

    def count_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)


def _example():
    from focusparse._parser_bench import (
        AnswerType,
        BBox,
        BenchmarkExample,
        DifficultyScores,
        Domain,
    )

    return BenchmarkExample(
        id="ex-llamaindex-react",
        domain=Domain.DATASHEET,
        source_pdf="fake.pdf",
        page_images=["fake_page_0001.png"],
        question="What is X?",
        answer="42",
        answer_type=AnswerType.NUMERIC,
        tolerance=0.5,
        supporting_pages=[1],
        supporting_bboxes=[BBox(page=1, x0=0, y0=0, x1=1, y1=1)],
        difficulty=DifficultyScores(visual=1, reasoning=1, localization=1),
        question_family="single_value_lookup",
    )


def _agent_example():
    return SimpleNamespace(
        id="ex-llamaindex-react",
        question="What is X?",
        domain="datasheet",
        source_pdf="fake.pdf",
    )


def _stub_tool_spec(name: str = "stub_tool") -> ToolSpec:
    from pydantic import BaseModel

    class _StubInput(BaseModel):
        echo: str = ""

    async def _runner(inp: _StubInput, **_kw: Any) -> dict[str, Any]:
        return {"echoed": inp.echo}

    return ToolSpec(
        name=name,
        description="stub tool for tests",
        input_model=_StubInput,
        runner=_runner,
        summarize=lambda out: f"echoed={out.get('echoed')}",
    )


def _load_script(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


async def test_llamaindex_react_uses_official_tool_loop():
    client = _ScriptedClient(
        [
            (
                "Thought: I should inspect a tool observation.\n"
                "Action: stub_tool\n"
                'Action Input: {"echo": "ping"}'
            ),
            (
                "Thought: I can answer without using any more tools.\n"
                'Answer: {"final_answer": "42", "citations": '
                '[{"page": 1, "bbox": [0, 0, 1, 1]}]}'
            ),
        ]
    )
    agent = LlamaIndexReActAgent(backend_client=client, tools=[_stub_tool_spec()])

    result = await agent.run(_agent_example(), images=[])

    assert result.answer == "42"
    assert result.citations == [{"page": 1, "bbox": [0, 0, 1, 1]}]
    assert result.telemetry["official_llamaindex_react"] is True
    assert result.telemetry["n_tool_calls"] == 1
    assert result.telemetry["tokens_in"] == 200
    assert result.trace.plan["implementation"]["agent_api"].endswith(".ReActAgent")
    assert result.trace.plan["official_llamaindex_react"] is True
    assert result.trace.plan["early_stopping_method"] == "generate"
    assert result.trace.plan["max_iterations"] == 10
    assert [s.action for s in result.trace.steps].count("tool_call") == 1
    assert "echoed=ping" in client.calls[1]["prompt"]
    assert "Use LlamaIndex ReAct format exactly" in (client.calls[0]["system"] or "")


async def test_llamaindex_react_passes_images_only_on_first_turn(tmp_path):
    image = tmp_path / "doc_page_0001_300dpi.png"
    image.write_bytes(b"fake")
    client = _ScriptedClient(
        [
            ("Thought: I should inspect a tool observation.\nAction: stub_tool\nAction Input: {}"),
            (
                "Thought: I can answer without using any more tools.\n"
                'Answer: {"final_answer": "42", "citations": []}'
            ),
        ]
    )
    agent = LlamaIndexReActAgent(backend_client=client, tools=[_stub_tool_spec()])

    await agent.run(_agent_example(), images=[image])

    assert client.calls[0]["images"] == [image]
    assert client.calls[1]["images"] is None
    assert str(image) in client.calls[0]["prompt"]


async def test_run_comparator_eval_llamaindex_react_manifest(
    parser_bench_submodule_present, tmp_path
):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")

    client = _ScriptedClient(
        [
            (
                "Thought: I can answer without using any more tools.\n"
                'Answer: {"final_answer": "42", "citations": '
                '[{"page": 1, "bbox": [0, 0, 1, 1]}]}'
            )
        ]
    )
    result = await run_comparator_eval(
        [_example()],
        backend_client=client,
        backend="fake",
        model="fake-1",
        agent_kind="llamaindex_react",
        protocol="full_doc",
        output_dir=tmp_path / "run",
        images_root=tmp_path,
        limit=1,
        tool_set="minimal",
    )

    manifest = json.loads((tmp_path / "run" / "run.json").read_text())
    assert result["aggregate"].n == 1
    assert manifest["agent"] == "llamaindex_react"
    assert manifest["tool_set"] == "minimal"
    assert manifest["available_tools"] == [INSPECT_REGION_SPEC.name, GET_TEXT_LAYER_SPEC.name]
    assert manifest["comparator_impl"]["name"] == "official_llamaindex_react"
    assert manifest["comparator_impl"]["agent_api"].endswith(".ReActAgent")
    assert (tmp_path / "run" / "per_example.jsonl").exists()
    assert (tmp_path / "run" / "predictions" / "ex-llamaindex-react.json").exists()


async def test_run_comparator_eval_minimal_artifacts_uses_scratch_dirs(
    parser_bench_submodule_present, monkeypatch, tmp_path
):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")

    page_1 = tmp_path / "fake_page_0001.png"
    page_2 = tmp_path / "fake_page_0002.png"
    Image.new("RGB", (8, 8), "white").save(page_1)
    Image.new("RGB", (8, 8), "white").save(page_2)
    example = _example().model_copy(update={"page_images": [page_1.name, page_2.name]})
    captured: dict[str, Any] = {}

    async def fake_run(
        self,
        example,
        images,
        *,
        pdf_path=None,
        crop_cache_dir=None,
        text_layer_cache_dir=None,
        **_kwargs,
    ):
        del self, pdf_path
        summary_paths = [p for p in images if "_tiled_" in p.name]
        assert summary_paths and summary_paths[0].exists()
        assert crop_cache_dir is not None
        assert text_layer_cache_dir is not None
        crop_cache_dir.mkdir(parents=True, exist_ok=True)
        text_layer_cache_dir.mkdir(parents=True, exist_ok=True)
        (crop_cache_dir / "sentinel.png").write_bytes(b"crop")
        (text_layer_cache_dir / "sentinel.txt").write_text("text")
        captured.update(
            {
                "images": list(images),
                "summary_path": summary_paths[0],
                "crop_cache_dir": crop_cache_dir,
                "text_layer_cache_dir": text_layer_cache_dir,
                "scratch_root": summary_paths[0].parent.parent,
            }
        )

        recorder = TrajectoryRecorder(example_id=example.id, question=example.question)
        recorder.record(
            TrajectoryStep(
                step_index=0,
                stage="llamaindex_react_tool",
                tier="comparator",
                action="tool_call",
                tool="inspect_region",
            )
        )
        citations = [{"page": 1, "bbox": [0, 0, 1, 1]}]
        trace = recorder.finalize(answer="42", citations=citations)
        return WorkflowResult(
            answer="42",
            citations=citations,
            trace=trace,
            telemetry={"tokens_in": 1, "tokens_out": 1, "usd": 0.0, "latency_ms": 1},
        )

    monkeypatch.setattr(LlamaIndexReActAgent, "run", fake_run)

    result = await run_comparator_eval(
        [example],
        backend_client=_ScriptedClient(["unused"]),
        backend="fake",
        model="fake-1",
        agent_kind="llamaindex_react",
        protocol="agentic_multi_page",
        output_dir=tmp_path / "run",
        images_root=tmp_path,
        limit=1,
        tool_set="minimal",
        resume=True,
        write_prediction_cache=False,
        persistent_tool_artifacts=False,
    )

    manifest = json.loads((tmp_path / "run" / "run.json").read_text())
    assert result["aggregate"].n == 1
    assert result["per_example"][0]["agentic_meta"]["summary_view_cached"] is True
    assert manifest["artifact_policy"] == {
        "write_prediction_cache": False,
        "persistent_tool_artifacts": False,
    }
    assert not (tmp_path / "run" / "predictions").exists()
    assert not (tmp_path / "run" / "tiles").exists()
    assert not (tmp_path / "run" / "crops").exists()
    assert not (tmp_path / "run" / "text_layer").exists()
    assert captured["crop_cache_dir"].parent == captured["scratch_root"]
    assert captured["text_layer_cache_dir"].parent == captured["scratch_root"]
    assert captured["summary_path"] in captured["images"]
    assert not captured["scratch_root"].exists()


def test_llamaindex_react_tool_sets_match_focusparse_definitions():
    minimal = [tool.name for tool in resolve_tool_set("minimal")]
    full = [tool.name for tool in resolve_tool_set("full")]

    assert minimal == [INSPECT_REGION_SPEC.name, GET_TEXT_LAYER_SPEC.name]
    assert full == [
        INSPECT_REGION_SPEC.name,
        GET_TEXT_LAYER_SPEC.name,
        LAYOUT_DETECT_SPEC.name,
        RUN_PYTHON_SPEC.name,
    ]


def test_run_hf_eval_accepts_llamaindex_react(monkeypatch):
    mod = _load_script(RUN_HF_EVAL, "_run_hf_eval_llamaindex_react_test")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_hf_eval.py",
            "--protocol",
            "agentic_multi_page",
            "--agent",
            "llamaindex_react",
            "--tool-set",
            "minimal",
        ],
    )

    args = mod._parse_args()
    assert args.agent == "llamaindex_react"
    assert mod._protocol_matches_agent("llamaindex_react", "agentic_multi_page") is True
    assert mod._protocol_matches_agent("llamaindex_react", "focus_default") is False


def test_headline_specs_use_llamaindex_react_for_primary_react_rows():
    mod = _load_script(RUN_HEADLINE_EVAL, "_run_headline_eval_llamaindex_react_test")
    react_specs = [s for s in mod.HEADLINE_SPECS if s["label"].startswith("ReAct")]

    assert react_specs == [
        {"agent": "llamaindex_react", "tool_set": "minimal", "label": "ReAct +2 tools"},
        {"agent": "llamaindex_react", "tool_set": "full", "label": "ReAct +4 tools"},
    ]
    assert mod._config_key(react_specs[0], "abcd1234").endswith("_tminimal")
