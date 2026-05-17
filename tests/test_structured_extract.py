"""Tests for Gemini-assisted structured region extraction."""

from pathlib import Path

from focusparse.tools.structured_extract import (
    StructuredRegionInput,
    StructuredRegionOutput,
    extract_structured_region_llm,
    parse_structured_region_response,
)


def test_parse_structured_region_response_accepts_fenced_json() -> None:
    out = parse_structured_region_response(
        """```json
        {
          "region_kind": "table",
          "headers": ["Parameter", "Min", "Typ", "Max"],
          "units": ["V"],
          "candidate_rows": ["VDD | 1.7 | 1.8 | 1.9"],
          "key_values": ["mode: DPD_MODE1"],
          "checkboxes": ["Large accelerated filer: checked"],
          "notes": ["TA = 25 C"],
          "confidence": 0.82
        }
        ```"""
    )

    assert out.region_kind == "table"
    assert out.headers == ["Parameter", "Min", "Typ", "Max"]
    assert out.units == ["V"]
    assert out.candidate_rows == ["VDD | 1.7 | 1.8 | 1.9"]
    assert out.key_values == ["mode: DPD_MODE1"]
    assert out.checkboxes == ["Large accelerated filer: checked"]
    assert out.notes == ["TA = 25 C"]
    assert out.confidence == 0.82


def test_structured_region_note_is_compact_and_deduped() -> None:
    note = StructuredRegionOutput(
        region_kind="table",
        headers=["Parameter", "Parameter", "Typ"],
        candidate_rows=["VDD | 1.8 V"],
        confidence=0.7,
    ).render_note()

    assert "Gemini structured extraction: kind=table" in note
    assert "headers: Parameter | Typ" in note
    assert "candidate_rows: VDD | 1.8 V" in note
    assert "confidence=0.70" in note


def test_parse_structured_region_response_fails_closed() -> None:
    out = parse_structured_region_response("not json")
    assert out.confidence == 0.0
    assert out.candidate_rows == []


async def test_extract_structured_region_uses_native_response_schema(tmp_path: Path) -> None:
    crop = tmp_path / "crop.png"
    crop.write_bytes(b"png")

    class _Resp:
        text = '{"region_kind":"table","candidate_rows":["A | B"],"confidence":0.5}'

    class _GeminiLikeClient:
        response_schema = None

        async def predict(self, *, response_schema=None, **kwargs):  # noqa: ANN001, ANN003
            del kwargs
            self.response_schema = response_schema
            return _Resp()

    client = _GeminiLikeClient()
    out = await extract_structured_region_llm(
        StructuredRegionInput(crop_ref=str(crop), question="What value?", region_type="table"),
        backend_client=client,
    )

    assert client.response_schema is StructuredRegionOutput
    assert out.candidate_rows == ["A | B"]
