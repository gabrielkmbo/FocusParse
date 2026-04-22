"""Tests for `SimpleBaselineAgent` and its response parser.

Parser tests run without the parser-bench submodule (they don't construct
BenchmarkExample). Agent end-to-end tests are gated on the submodule fixture
since they need to instantiate a real `BenchmarkExample`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from focusparse.models.base import ModelResponse
from focusparse.pipeline.workflow import SimpleBaselineAgent, _parse_simple_response

# ---------------------------------------------------------------------------
# _parse_simple_response (no submodule required)
# ---------------------------------------------------------------------------


def test_parse_bare_json():
    text = '{"answer": "5.5", "citations": [{"page": 3, "bbox": [0.1, 0.2, 0.3, 0.4]}]}'
    answer, cites = _parse_simple_response(text)
    assert answer == "5.5"
    assert cites == [{"page": 3, "bbox": [0.1, 0.2, 0.3, 0.4]}]


def test_parse_fenced_json():
    text = 'The answer is:\n```json\n{"answer": "yes", "citations": []}\n```\n'
    answer, cites = _parse_simple_response(text)
    assert answer == "yes"
    assert cites == []


def test_parse_json_with_prefix_and_suffix():
    text = 'Looking at the image, {"answer": "42", "citations": []} is what I see.'
    answer, cites = _parse_simple_response(text)
    assert answer == "42"
    assert cites == []


def test_parse_non_json_falls_back_to_raw_text():
    answer, cites = _parse_simple_response("Just some free text with no JSON at all.")
    assert answer == "Just some free text with no JSON at all."
    assert cites == []


def test_parse_empty_string_returns_empty():
    assert _parse_simple_response("") == ("", [])


def test_parse_drops_malformed_citations():
    text = (
        '{"answer": "x", "citations": ['
        '{"page": 1, "bbox": [0, 0, 1, 1]}, '  # ok
        '{"page": "two", "bbox": [0, 0, 1, 1]}, '  # page coerced to int
        '{"page": 3, "bbox": [0, 0, 1]}, '  # too short — drop
        '{"page": 4}, '  # no bbox — drop
        '"raw string"]'  # not a dict — drop
        "}"
    )
    _, cites = _parse_simple_response(text)
    # Two valid: the first and the string-page one (which coerces to 2).
    assert len(cites) == 2
    assert cites[0]["page"] == 1
    assert cites[1]["page"] == 2


def test_parse_non_string_answer_is_stringified():
    text = '{"answer": 5.5, "citations": []}'
    answer, cites = _parse_simple_response(text)
    assert answer == "5.5"
    assert cites == []


# ---------------------------------------------------------------------------
# SimpleBaselineAgent.run (requires submodule for BenchmarkExample)
# ---------------------------------------------------------------------------


class _FakeClient:
    def __init__(self, response_text: str, tokens_in: int = 100, tokens_out: int = 20) -> None:
        self._text = response_text
        self._tokens_in = tokens_in
        self._tokens_out = tokens_out
        self.calls: list[dict[str, Any]] = []

    async def predict(
        self,
        prompt: str,
        images: list[Path] | None = None,
        system: str | None = None,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        self.calls.append({"prompt": prompt, "n_images": len(images or []), "system": system})
        return ModelResponse(
            text=self._text,
            tokens_in=self._tokens_in,
            tokens_out=self._tokens_out,
            usd=0.001,
            latency_ms=42,
        )

    def count_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)


def _make_example():
    """Build a minimal BenchmarkExample. Gated on submodule at call site."""
    from focusparse._parser_bench import BBox, BenchmarkExample

    return BenchmarkExample(
        id="ex-1",
        domain="datasheet",
        source_pdf="datasheet-A.pdf",
        page_images=["data/processed/datasheet-A/images/datasheet-A_page_0003_300dpi.png"],
        question="What is the max supply voltage?",
        answer="5.5",
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
        split="validation",
        original_bboxes=[],
    )


async def test_simple_agent_records_one_step(tmp_path, parser_bench_submodule_present):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required for BenchmarkExample")

    client = _FakeClient('{"answer": "5.5", "citations": [{"page": 3, "bbox": [0.1,0.2,0.3,0.4]}]}')
    agent = SimpleBaselineAgent(backend_client=client, protocol="full_doc")
    example = _make_example()

    # Image file doesn't need to exist for SimpleBaselineAgent — the fake client
    # doesn't open it. Just pass a path.
    result = await agent.run(example, [tmp_path / "fake.png"])

    assert result.answer == "5.5"
    assert len(result.citations) == 1
    assert result.citations[0]["page"] == 3

    # One trajectory step, llm_call at tier=baseline.
    assert len(result.trace.steps) == 1
    step = result.trace.steps[0]
    assert step.stage == "simple_answer"
    assert step.action == "llm_call"
    assert step.tokens_in == 100
    assert step.tokens_out == 20
    assert step.usd == 0.001

    # One API call recorded.
    assert len(client.calls) == 1
    assert client.calls[0]["n_images"] == 1


async def test_simple_agent_handles_non_json_response(tmp_path, parser_bench_submodule_present):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required for BenchmarkExample")

    client = _FakeClient("I'm not sure but my best guess is 5.5 volts.")
    agent = SimpleBaselineAgent(backend_client=client, protocol="full_doc")
    example = _make_example()

    result = await agent.run(example, [tmp_path / "fake.png"])
    assert "5.5" in result.answer
    assert result.citations == []
