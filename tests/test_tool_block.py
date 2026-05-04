"""Tests for format_agent_tool_block.

The renderer is what the LLM literally sees in its system prompt. Broken
output here = silent agent failures at eval time. The strongest contract
test parses each tool's worked example as JSON and validates it against
the tool's input model — so a typo in `_EXAMPLE_CALLS` fails the build.
"""

from __future__ import annotations

import json

import pytest

from focusparse.tools import (
    _EXAMPLE_CALLS,  # noqa: F401  (intentional access for testing)
    GET_TEXT_LAYER_SPEC,
    INSPECT_REGION_SPEC,
    LAYOUT_DETECT_SPEC,
    RUN_PYTHON_SPEC,
    format_agent_tool_block,
    resolve_tool_set,
)


@pytest.fixture
def careful() -> str:
    return format_agent_tool_block(resolve_tool_set("full"), mode="careful")


@pytest.fixture
def generic() -> str:
    return format_agent_tool_block(resolve_tool_set("full"), mode="generic")


# ---------------------------------------------------------------------------
# Structural smoke
# ---------------------------------------------------------------------------


def test_careful_block_has_all_required_sections(careful: str) -> None:
    for tool_name in ("inspect_region", "get_text_layer", "layout_detect", "run_python"):
        assert f"### {tool_name}" in careful
    assert "Inputs:" in careful
    assert "Returns:" in careful
    assert "When to use:" in careful
    assert "Chains with:" in careful
    assert "Example call:" in careful


def test_bbox_norm_renders_as_array_of_4_numbers(careful: str) -> None:
    """The whole point of Phase 1+2: no more `bbox_norm: ?`."""
    assert "bbox_norm (array of 4 numbers" in careful
    assert "bbox_norm: ?" not in careful


def test_layout_detect_pixel_to_norm_chaining_visible(careful: str) -> None:
    """Coordinate-system mismatch is now in the prompt instead of silent."""
    layout_idx = careful.index("### layout_detect")
    layout_block = careful[layout_idx:]
    next_tool = layout_block.find("\n### ", 5)
    if next_tool >= 0:
        layout_block = layout_block[:next_tool]
    assert "pixel" in layout_block.lower()
    assert "image_width" in layout_block
    assert "bbox_norm" in layout_block


def test_run_python_chains_documented(careful: str) -> None:
    rp_idx = careful.index("### run_python")
    rp_block = careful[rp_idx:]
    assert "image_refs" in rp_block
    assert "save_image" in rp_block
    assert "new_image_refs" in rp_block


def test_inspect_region_post_feed_to_run_python_documented(careful: str) -> None:
    """crop_ref → run_python.image_refs is the post-feed chain."""
    ir_idx = careful.index("### inspect_region")
    ir_block = careful[ir_idx:]
    next_tool = ir_block.find("\n### ", 5)
    if next_tool >= 0:
        ir_block = ir_block[:next_tool]
    assert "run_python" in ir_block
    assert "image_refs" in ir_block


def test_generic_mode_is_substantially_shorter(careful: str, generic: str) -> None:
    """Generic skips Returns/When to use/Chains with/Example call."""
    assert "Returns:" not in generic
    assert "Chains with:" not in generic
    assert "Example call:" not in generic
    # Token-budget check: generic should be at most 25% of careful's size.
    assert len(generic) < len(careful) * 0.25


def test_minimal_tool_set_omits_layout_and_run_python() -> None:
    block = format_agent_tool_block(resolve_tool_set("minimal"), mode="careful")
    assert "### inspect_region" in block
    assert "### get_text_layer" in block
    assert "### layout_detect" not in block
    assert "### run_python" not in block


# ---------------------------------------------------------------------------
# The strongest contract test: examples validate against input models.
# ---------------------------------------------------------------------------


def test_each_worked_example_validates_against_input_model() -> None:
    """If we change a description and break an example, the build fails."""
    pairs = [
        (INSPECT_REGION_SPEC, "inspect_region"),
        (GET_TEXT_LAYER_SPEC, "get_text_layer"),
        (LAYOUT_DETECT_SPEC, "layout_detect"),
        (RUN_PYTHON_SPEC, "run_python"),
    ]
    from focusparse.tools import _EXAMPLE_CALLS as examples

    for spec, name in pairs:
        example = examples[name]
        # 1. Round-trip through JSON to mimic what the LLM sends back.
        round_tripped = json.loads(json.dumps(example))
        # 2. Must validate against the input model.
        spec.input_model.model_validate(round_tripped)


def test_example_call_action_field_matches_tool_name(careful: str) -> None:
    """Each rendered example contains the right `action` value."""
    for name in ("inspect_region", "get_text_layer", "layout_detect", "run_python"):
        idx = careful.index(f"### {name}")
        next_tool = careful.find("\n### ", idx + 5)
        block = careful[idx:next_tool] if next_tool >= 0 else careful[idx:]
        # The example block contains an indented JSON object; parse it back.
        ex_idx = block.index("Example call:")
        # Find the JSON block (lines starting with two spaces).
        rest = block[ex_idx + len("Example call:") :]
        json_lines = []
        for ln in rest.splitlines():
            if ln.startswith("  "):
                json_lines.append(ln[2:])
            elif json_lines:
                break
        parsed = json.loads("\n".join(json_lines))
        assert parsed["action"] == name


# ---------------------------------------------------------------------------
# Field-render smoke
# ---------------------------------------------------------------------------


def test_required_vs_default_marker_in_inputs(careful: str) -> None:
    """Required fields render as `(... required)`; defaulted fields show `default=...`."""
    # `doc_path` is required on inspect_region.
    assert "doc_path (string, required)" in careful
    # `mode` defaults to 'element' on inspect_region.
    assert "mode (one of: 'image', 'element', 'region', default='element')" in careful


def test_examples_appear_inline_with_fields(careful: str) -> None:
    """Each user-facing field with examples renders an `example: ...` line."""
    # `bbox_norm` example appears at least twice (inspect_region + get_text_layer).
    assert careful.count("example: [0.1, 0.2, 0.5, 0.6]") >= 2
