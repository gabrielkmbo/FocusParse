"""Tool layer tests — most wired in Phase 3. Phase 1 just asserts schemas load."""

from __future__ import annotations


def test_inspect_region_schema():
    from focusparse.tools.inspect_region import InspectRegionInput

    inp = InspectRegionInput(
        doc_id="fake", page=3, bbox_norm=(0.1, 0.1, 0.4, 0.5), mode="element"
    )
    assert inp.mode == "element"
    assert inp.dpi == 300


def test_layout_stub_detection():
    from focusparse.tools.layout_detect import DetectedBox, is_stub_response

    stub = [DetectedBox(label="Page", bbox=(0, 0, 1000, 1300), score=1.0)]
    assert is_stub_response(stub, 1000, 1300) is True

    real = [
        DetectedBox(label="Chart", bbox=(50, 100, 500, 400), score=0.9),
        DetectedBox(label="Caption", bbox=(50, 410, 500, 440), score=0.8),
    ]
    assert is_stub_response(real, 1000, 1300) is False


def test_run_python_input_schema_limits():
    from focusparse.tools.run_python import ALLOWED_IMPORTS, DEFAULT_WALL_TIME_S, RunPythonInput

    inp = RunPythonInput(code="print(1)")
    assert inp.wall_time_s == DEFAULT_WALL_TIME_S
    assert "numpy" in ALLOWED_IMPORTS
    assert "os" not in ALLOWED_IMPORTS
    assert "subprocess" not in ALLOWED_IMPORTS
