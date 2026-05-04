"""Tool layer tests — most wired in Phase 3. Phase 1 just asserts schemas load."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from focusparse.tools._schemas import bbox_norm_field
from focusparse.tools.get_text_layer import GetTextLayerInput, GetTextLayerOutput
from focusparse.tools.inspect_region import InspectRegionInput, InspectRegionOutput
from focusparse.tools.layout_detect import DetectedBox, LayoutDetectionOutput, is_stub_response
from focusparse.tools.run_python import (
    ALLOWED_IMPORTS,
    DEFAULT_WALL_TIME_S,
    RunPythonInput,
    RunPythonOutput,
)


def test_inspect_region_schema():
    inp = InspectRegionInput(
        doc_path="/tmp/fake.pdf", page=3, bbox_norm=(0.1, 0.1, 0.4, 0.5), mode="element"
    )
    assert inp.mode == "element"
    assert inp.dpi == 300


def test_layout_stub_detection():
    stub = [DetectedBox(label="Page", bbox=(0, 0, 1000, 1300), score=1.0)]
    assert is_stub_response(stub, 1000, 1300) is True

    real = [
        DetectedBox(label="Chart", bbox=(50, 100, 500, 400), score=0.9),
        DetectedBox(label="Caption", bbox=(50, 410, 500, 440), score=0.8),
    ]
    assert is_stub_response(real, 1000, 1300) is False


def test_run_python_input_schema_limits():
    inp = RunPythonInput(code="print(1)")
    assert inp.wall_time_s == DEFAULT_WALL_TIME_S
    assert "numpy" in ALLOWED_IMPORTS
    assert "os" not in ALLOWED_IMPORTS
    assert "subprocess" not in ALLOWED_IMPORTS


# ---------------------------------------------------------------------------
# 2026-05-04 — Phase 1: every input/output field has a description + examples
# where appropriate. The agent prompt renderer (Phase 2) reads these directly.
# ---------------------------------------------------------------------------


def _all_fields_have_descriptions(model_cls) -> list[str]:
    """Return any field names that are missing `description=` metadata."""
    schema = model_cls.model_json_schema()
    missing: list[str] = []
    for name, prop in schema.get("properties", {}).items():
        # Pydantic v2 inlines $ref'd subschemas; for those we look up the def.
        if "$ref" in prop:
            ref = prop["$ref"].split("/")[-1]
            prop = schema.get("$defs", {}).get(ref) or {}
        if not prop.get("description"):
            missing.append(name)
    return missing


@pytest.mark.parametrize(
    "model_cls",
    [
        InspectRegionInput,
        InspectRegionOutput,
        GetTextLayerInput,
        GetTextLayerOutput,
        DetectedBox,
        LayoutDetectionOutput,
        RunPythonInput,
        RunPythonOutput,
    ],
)
def test_every_field_has_a_description(model_cls):
    missing = _all_fields_have_descriptions(model_cls)
    assert not missing, f"{model_cls.__name__} missing description on: {missing}"


def test_bbox_norm_renders_as_array_of_4_numbers():
    """The shared bbox_norm_field helper must produce a clean array schema.

    The old `tuple[float, float, float, float]` shape rendered as
    `prefixItems` in JSON Schema — our agent prompt renderer can't read
    that, and the LLM saw `bbox_norm: ?` instead of "4 numbers in [0,1]".
    """
    schema = InspectRegionInput.model_json_schema()
    bbox = schema["properties"]["bbox_norm"]
    assert bbox["type"] == "array"
    assert bbox["minItems"] == 4
    assert bbox["maxItems"] == 4
    assert bbox["items"]["type"] == "number"
    assert "[x0, y0, x1, y1]" in bbox["description"]


def test_bbox_norm_examples_present():
    schema = InspectRegionInput.model_json_schema()
    examples = schema["properties"]["bbox_norm"]["examples"]
    assert examples == [[0.10, 0.20, 0.50, 0.60]]


def test_bbox_norm_rejects_wrong_length():
    with pytest.raises(ValidationError) as exc_info:
        InspectRegionInput(
            doc_path="/tmp/x.pdf",
            page=1,
            bbox_norm=[0.1, 0.2, 0.3],  # only 3 floats
        )
    msg = str(exc_info.value)
    assert "bbox_norm" in msg
    # Pydantic v2 emits "List should have at least 4 items" on min_length.
    assert "at least 4" in msg or "4 items" in msg


def test_bbox_norm_accepts_tuple_input_back_compat():
    """Existing call sites still pass tuple literals; coercion stays working."""
    inp = InspectRegionInput(
        doc_path="/tmp/x.pdf",
        page=1,
        bbox_norm=(0.1, 0.2, 0.3, 0.4),  # tuple, not list
    )
    assert inp.bbox_norm == [0.1, 0.2, 0.3, 0.4]


def test_get_text_layer_bbox_norm_optional():
    """Optional variant defaults to None and accepts None explicitly."""
    out = GetTextLayerInput(doc_path="/tmp/x.pdf", page=1)
    assert out.bbox_norm is None
    out2 = GetTextLayerInput(doc_path="/tmp/x.pdf", page=1, bbox_norm=None)
    assert out2.bbox_norm is None


def test_layout_detect_bbox_description_mentions_pixel_to_norm_conversion():
    """The pixel→norm chaining contract for the LLM lives in the schema."""
    schema = DetectedBox.model_json_schema()
    desc = schema["properties"]["bbox"]["description"]
    assert "ABSOLUTE PIXEL" in desc
    assert "image_width" in desc
    assert "image_height" in desc
    assert "bbox_norm" in desc


def test_run_python_code_example_is_a_worked_template():
    """The `code` field's example is the canonical 5-line template."""
    schema = RunPythonInput.model_json_schema()
    examples = schema["properties"]["code"]["examples"]
    assert len(examples) == 1
    template = examples[0]
    assert "images[" in template
    assert "save_image" in template
    assert "print(" in template


def test_run_python_image_refs_description_mentions_crop_ref_compat():
    schema = RunPythonInput.model_json_schema()
    desc = schema["properties"]["image_refs"]["description"]
    assert "absolute paths" in desc.lower()
    assert "inspect_region" in desc


def test_inspect_region_crop_ref_description_mentions_run_python_chain():
    schema = InspectRegionOutput.model_json_schema()
    desc = schema["properties"]["crop_ref"]["description"]
    assert "run_python" in desc
    assert "image_refs" in desc


def test_bbox_norm_field_optional_helper():
    """The optional variant injects a 'Pass null' note into the description."""
    field_info = bbox_norm_field(optional=True)
    assert field_info.default is None
    assert "null" in (field_info.description or "")
