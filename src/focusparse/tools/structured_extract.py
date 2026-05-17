"""LLM-assisted table/element schema extraction for inspected crops.

This is a gated post-localization helper: it never retrieves new evidence and
never answers the benchmark question directly. It repackages the current crop
and deterministic text/OCR into a compact schema note for the reasoner.
"""

from __future__ import annotations

import json
import logging
import re
from inspect import signature
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from focusparse.models.base import ModelClient

logger = logging.getLogger(__name__)

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_MAX_CONTEXT_CHARS = 3000

_STRUCTURED_REGION_SYSTEM_PROMPT = (
    "You are a document table/element schema extractor for high-resolution PDF crops. "
    "Return STRICT JSON only, with no markdown and no prose outside JSON.\n"
    "\n"
    "Goal: describe visible structure that helps another model answer the user's "
    "question from the same crop. Do not answer the question directly unless the "
    "value is part of a visible row/key-value/checkbox candidate.\n"
    "\n"
    "Schema:\n"
    "{\n"
    '  "region_kind": "table|key_value|form|text|unknown",\n'
    '  "headers": ["..."],\n'
    '  "units": ["..."],\n'
    '  "candidate_rows": ["row label | column/value | condition/unit/note"],\n'
    '  "key_values": ["label: value"],\n'
    '  "checkboxes": ["label: yes/no/checked/unchecked"],\n'
    '  "notes": ["footnote/condition/caption text relevant to the crop"],\n'
    '  "confidence": 0.0\n'
    "}\n"
    "\n"
    "Rules:\n"
    "1. Use only the provided image and text/OCR context. Do not hallucinate rows.\n"
    "2. Prefer rows, labels, headers, units, and checkboxes that overlap the question.\n"
    "3. Preserve numeric values, units, capitalization, and code-like identifiers exactly.\n"
    "4. Keep arrays compact: at most 6 headers, 4 candidate_rows, 4 key_values, "
    "4 checkboxes, and 4 notes. Do not transcribe unrelated page text.\n"
    "5. If the crop is not readable, return empty arrays and confidence=0.0."
)


class StructuredRegionInput(BaseModel):
    crop_ref: str = Field(..., description="Absolute path to an inspected crop PNG.")
    question: str = Field(..., description="Benchmark question used only for relevance.")
    region_type: str | None = Field(default=None, description="Layout region type hint.")
    text_context: str | None = Field(
        default=None,
        description="Native text/OCR already extracted from this region.",
    )


class StructuredRegionOutput(BaseModel):
    region_kind: str = "unknown"
    headers: list[str] = Field(default_factory=list)
    units: list[str] = Field(default_factory=list)
    candidate_rows: list[str] = Field(default_factory=list)
    key_values: list[str] = Field(default_factory=list)
    checkboxes: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    confidence: float = 0.0

    def render_note(self) -> str:
        """Render a compact packet note for reasoner/verifier prompts."""

        lines = [f"Gemini structured extraction: kind={self.region_kind}"]
        for label, values in (
            ("headers", self.headers),
            ("units", self.units),
            ("candidate_rows", self.candidate_rows),
            ("key_values", self.key_values),
            ("checkboxes", self.checkboxes),
            ("notes", self.notes),
        ):
            compact = _clean_list(values)
            if compact:
                lines.append(f"{label}: " + " | ".join(compact[:6]))
        lines.append(f"confidence={self.confidence:.2f}")
        return "\n".join(lines)


async def extract_structured_region_llm(
    inp: StructuredRegionInput,
    *,
    backend_client: ModelClient,
) -> StructuredRegionOutput:
    """Use a vision LLM to extract table/element structure from one crop."""

    crop_path = Path(inp.crop_ref)
    if not crop_path.is_file():
        logger.warning("structured_extract: crop_ref does not exist: %s", crop_path)
        return StructuredRegionOutput(confidence=0.0)

    context = str(inp.text_context or "").strip()
    if len(context) > _MAX_CONTEXT_CHARS:
        context = context[: _MAX_CONTEXT_CHARS - 3] + "..."
    prompt = (
        f"Question: {inp.question}\n"
        f"Region type hint: {inp.region_type or 'unknown'}\n"
        "Existing native text/OCR context:\n"
        f"{context or '(none)'}\n"
        "\nExtract only the compact, question-relevant visible table/element schema as strict JSON."
    )
    try:
        kwargs: dict[str, Any] = {
            "prompt": prompt,
            "images": [crop_path],
            "system": _STRUCTURED_REGION_SYSTEM_PROMPT,
        }
        if _predict_accepts_response_schema(backend_client):
            kwargs["response_schema"] = StructuredRegionOutput
        response = await backend_client.predict(**kwargs)
    except Exception as exc:  # noqa: BLE001 — advisory helper, never raise
        logger.warning("structured_extract: backend call failed (%s)", exc)
        return StructuredRegionOutput(confidence=0.0)
    return parse_structured_region_response(response.text or "")


def parse_structured_region_response(text: str) -> StructuredRegionOutput:
    """Parse strict JSON, tolerating accidental fenced output."""

    if not text:
        return StructuredRegionOutput(confidence=0.0)
    candidate = text.strip()
    fence = _JSON_FENCE_RE.search(candidate)
    if fence:
        candidate = fence.group(1)
    else:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = candidate[start : end + 1]
    try:
        obj = json.loads(candidate)
    except json.JSONDecodeError:
        logger.debug("structured_extract: JSON parse failed on %r", text[:120])
        return StructuredRegionOutput(confidence=0.0)
    if not isinstance(obj, dict):
        return StructuredRegionOutput(confidence=0.0)
    return StructuredRegionOutput(
        region_kind=_clean_scalar(obj.get("region_kind")) or "unknown",
        headers=_clean_list(obj.get("headers")),
        units=_clean_list(obj.get("units")),
        candidate_rows=_clean_list(obj.get("candidate_rows")),
        key_values=_clean_list(obj.get("key_values")),
        checkboxes=_clean_list(obj.get("checkboxes")),
        notes=_clean_list(obj.get("notes")),
        confidence=_clamp_confidence(obj.get("confidence")),
    )


def _clean_scalar(value: Any) -> str:
    return " ".join(str(value or "").split())


def _clean_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        cleaned = _clean_scalar(item)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        out.append(cleaned)
    return out


def _clamp_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, confidence))


def _predict_accepts_response_schema(backend_client: ModelClient) -> bool:
    try:
        return "response_schema" in signature(backend_client.predict).parameters
    except (TypeError, ValueError):
        return False


__all__ = [
    "StructuredRegionInput",
    "StructuredRegionOutput",
    "extract_structured_region_llm",
    "parse_structured_region_response",
]
