"""get_text_layer — deterministic PDF text span extraction via PyMuPDF.

Crucial for beating OCR-only adversarial filters in parser-bench. If a PDF has
a real text layer, we read it directly instead of OCR-ing; otherwise we fall
back to cached Tesseract output.
"""

from __future__ import annotations

from pydantic import BaseModel


class GetTextLayerInput(BaseModel):
    doc_path: str                              # local path to the PDF
    page: int
    bbox_norm: tuple[float, float, float, float] | None = None


class GetTextLayerOutput(BaseModel):
    text: str
    source: str                                # "native" | "ocr"
    spans: list[dict] = []                     # [{text, bbox, confidence}]


async def get_text_layer(inp: GetTextLayerInput) -> GetTextLayerOutput:
    raise NotImplementedError("get_text_layer — wire in Phase 3")
