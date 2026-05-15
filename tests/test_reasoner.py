"""Reasoner-side tests focused on multi-scale evidence packet handling.

The full end-to-end reasoner path is covered in test_workflow.py; this
file pins the contract that when EvidencePacket.multi_scale_crops is
populated, the LLM sees BOTH the tight and context crops as separate
image inputs (and is told so in the packet descriptor line).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from focusparse.evidence.packet import (
    CropRef,
    EvidencePacket,
    PacketProvenance,
)
from focusparse.models.base import ModelResponse
from focusparse.pipeline.events import EvidenceEvent, QuestionEvent
from focusparse.pipeline.reasoner import (
    _MAX_PACKET_TEXT_CHARS,
    _collect_packet_images,
    _format_hint,
    _parse_reasoner_response,
    _render_packet_line,
    answer_from_evidence,
)


def _packet(
    *,
    packet_id: str = "pkt_000",
    page: int = 3,
    bbox: tuple[float, float, float, float] = (0.1, 0.2, 0.5, 0.6),
    local_crop_ref: str = "/cache/crops/abc.png",
    page_thumbnail_ref: str = "/cache/pages/p3.png",
    region_type: str | None = None,
    multi_scale: list[CropRef] | None = None,
    linked_crop_refs: list[str] | None = None,
    linked_neighbor_types: list[str] | None = None,
    text_layer_snippet: str | None = None,
    ocr_snippet: str | None = None,
) -> EvidencePacket:
    return EvidencePacket(
        packet_id=packet_id,
        page=page,
        bbox_norm=bbox,
        region_type=region_type,
        page_thumbnail_ref=page_thumbnail_ref,
        local_crop_ref=local_crop_ref,
        multi_scale_crops=multi_scale or [],
        linked_crop_refs=linked_crop_refs or [],
        linked_neighbor_types=linked_neighbor_types or [],
        text_layer_snippet=text_layer_snippet,
        ocr_snippet=ocr_snippet,
        provenance=PacketProvenance(tool="t", args_hash=""),
    )


class _FakeReasonerClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def predict(
        self,
        prompt: str,
        images: list[Path] | None = None,
        system: str | None = None,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        self.calls.append({"prompt": prompt, "images": images, "system": system})
        return ModelResponse(text='{"answer":"0.697 V","citations":["pkt_000"],"confidence":0.8}')


# ---------------------------------------------------------------------------
# _collect_packet_images
# ---------------------------------------------------------------------------


def test_collect_packet_images_uses_local_crop_ref_when_no_multi_scale() -> None:
    ev = EvidenceEvent(packets=[_packet(local_crop_ref="/cache/a.png")])
    images = _collect_packet_images(ev)
    assert images == [Path("/cache/a.png")]


def test_collect_packet_images_falls_back_to_page_thumbnail() -> None:
    ev = EvidenceEvent(packets=[_packet(local_crop_ref="", page_thumbnail_ref="/cache/p.png")])
    images = _collect_packet_images(ev)
    assert images == [Path("/cache/p.png")]


def test_collect_packet_images_dedupes_repeated_refs() -> None:
    ev = EvidenceEvent(
        packets=[
            _packet(packet_id="pkt_000", local_crop_ref="/cache/same.png"),
            _packet(packet_id="pkt_001", local_crop_ref="/cache/same.png"),
        ]
    )
    images = _collect_packet_images(ev)
    assert images == [Path("/cache/same.png")]


def test_collect_packet_images_uses_multi_scale_when_present() -> None:
    """When multi_scale_crops is populated, both tight + context refs surface."""
    ev = EvidenceEvent(
        packets=[
            _packet(
                local_crop_ref="/cache/tight.png",
                multi_scale=[
                    CropRef(ref="/cache/tight.png", bbox_norm=(0.1, 0.2, 0.5, 0.6), scale="tight"),
                    CropRef(
                        ref="/cache/context.png", bbox_norm=(0.0, 0.0, 0.8, 0.9), scale="context"
                    ),
                ],
            )
        ]
    )
    images = _collect_packet_images(ev)
    assert images == [Path("/cache/tight.png"), Path("/cache/context.png")]


def test_collect_packet_images_dedupes_across_multi_scale() -> None:
    ev = EvidenceEvent(
        packets=[
            _packet(
                packet_id="pkt_000",
                multi_scale=[
                    CropRef(ref="/cache/A.png", bbox_norm=(0, 0, 1, 1), scale="tight"),
                    CropRef(ref="/cache/B.png", bbox_norm=(0, 0, 1, 1), scale="context"),
                ],
            ),
            _packet(
                packet_id="pkt_001",
                multi_scale=[
                    CropRef(ref="/cache/A.png", bbox_norm=(0, 0, 1, 1), scale="tight"),
                    CropRef(ref="/cache/C.png", bbox_norm=(0, 0, 1, 1), scale="context"),
                ],
            ),
        ]
    )
    images = _collect_packet_images(ev)
    # /cache/A.png is shared between the two packets and dedups; B and C add.
    assert images == [Path("/cache/A.png"), Path("/cache/B.png"), Path("/cache/C.png")]


def test_collect_packet_images_mixed_legacy_and_multi_scale() -> None:
    """One packet with multi_scale, one without — both contribute their refs."""
    ev = EvidenceEvent(
        packets=[
            _packet(
                packet_id="pkt_000",
                multi_scale=[
                    CropRef(ref="/cache/A.png", bbox_norm=(0, 0, 1, 1), scale="tight"),
                    CropRef(ref="/cache/B.png", bbox_norm=(0, 0, 1, 1), scale="context"),
                ],
            ),
            _packet(packet_id="pkt_001", local_crop_ref="/cache/legacy.png"),
        ]
    )
    images = _collect_packet_images(ev)
    assert images == [Path("/cache/A.png"), Path("/cache/B.png"), Path("/cache/legacy.png")]


# ---------------------------------------------------------------------------
# Path A (2026-05-06): linked_crop_refs reach the reasoner as images.
# Pre-Path-A this was dead code; the 2026-05-06 memory entry has the diagnosis.
# ---------------------------------------------------------------------------


def test_collect_packet_images_includes_linked_crop_refs() -> None:
    """A packet with 2 linked neighbor crops surfaces them after the primary."""
    ev = EvidenceEvent(
        packets=[
            _packet(
                local_crop_ref="/cache/primary.png",
                linked_crop_refs=["/cache/caption.png", "/cache/footnote.png"],
                linked_neighbor_types=["caption", "footnote"],
            )
        ]
    )
    images = _collect_packet_images(ev)
    # Order is primary → linked, so the reasoner reads "this is the focus,
    # then the context."
    assert images == [
        Path("/cache/primary.png"),
        Path("/cache/caption.png"),
        Path("/cache/footnote.png"),
    ]


def test_collect_packet_images_dedupes_neighbors_across_packets() -> None:
    """A neighbor ref shared between two packets appears once in the image list."""
    ev = EvidenceEvent(
        packets=[
            _packet(
                packet_id="pkt_000",
                local_crop_ref="/cache/a.png",
                linked_crop_refs=["/cache/shared_caption.png"],
                linked_neighbor_types=["caption"],
            ),
            _packet(
                packet_id="pkt_001",
                local_crop_ref="/cache/b.png",
                linked_crop_refs=["/cache/shared_caption.png", "/cache/footnote.png"],
                linked_neighbor_types=["caption", "footnote"],
            ),
        ]
    )
    images = _collect_packet_images(ev)
    assert images == [
        Path("/cache/a.png"),
        Path("/cache/shared_caption.png"),
        Path("/cache/b.png"),
        Path("/cache/footnote.png"),
    ]


def test_collect_packet_images_skips_empty_neighbor_refs() -> None:
    """Empty-string entries in linked_crop_refs are filtered out."""
    ev = EvidenceEvent(
        packets=[
            _packet(
                local_crop_ref="/cache/primary.png",
                linked_crop_refs=["", "/cache/real.png", ""],
                linked_neighbor_types=["caption", "footnote", "title"],
            )
        ]
    )
    images = _collect_packet_images(ev)
    assert images == [Path("/cache/primary.png"), Path("/cache/real.png")]


def test_collect_packet_images_neighbors_follow_multi_scale() -> None:
    """When BOTH multi_scale_crops AND linked_crop_refs are populated, the
    image order is: tight → context → linked. (Multi-scale primaries first,
    then expand_context's neighbors.)"""
    ev = EvidenceEvent(
        packets=[
            _packet(
                multi_scale=[
                    CropRef(ref="/cache/tight.png", bbox_norm=(0.1, 0.2, 0.5, 0.6), scale="tight"),
                    CropRef(ref="/cache/ctx.png", bbox_norm=(0.0, 0.0, 0.8, 0.9), scale="context"),
                ],
                linked_crop_refs=["/cache/caption.png"],
                linked_neighbor_types=["caption"],
            )
        ]
    )
    images = _collect_packet_images(ev)
    assert images == [
        Path("/cache/tight.png"),
        Path("/cache/ctx.png"),
        Path("/cache/caption.png"),
    ]


def test_collect_packet_images_skips_text_only_header_neighbors() -> None:
    """Header-like neighbors with extracted text stay in prompt text, not images."""
    ev = EvidenceEvent(
        packets=[
            _packet(
                local_crop_ref="/cache/primary.png",
                linked_crop_refs=["/cache/header.png", "/cache/caption.png"],
                linked_neighbor_types=["section-header", "caption"],
                text_layer_snippet=(
                    "Context [section-header]: Electrical Characteristics\n"
                    "Context [caption]: Figure 4. Load transient response"
                ),
            )
        ]
    )
    images = _collect_packet_images(ev)
    assert images == [Path("/cache/primary.png"), Path("/cache/caption.png")]


def test_collect_packet_images_keeps_header_neighbor_without_extracted_text() -> None:
    """Do not hide a header crop unless expand actually recovered its text."""
    ev = EvidenceEvent(
        packets=[
            _packet(
                local_crop_ref="/cache/primary.png",
                linked_crop_refs=["/cache/header.png"],
                linked_neighbor_types=["section-header"],
                text_layer_snippet="Main packet text only",
            )
        ]
    )
    images = _collect_packet_images(ev)
    assert images == [Path("/cache/primary.png"), Path("/cache/header.png")]


# ---------------------------------------------------------------------------
# _render_packet_line
# ---------------------------------------------------------------------------


def test_render_packet_line_legacy_packet() -> None:
    """No multi_scale → no scale annotation."""
    line = _render_packet_line(_packet(packet_id="pkt_000"))
    assert "pkt_000" in line
    assert "page 3" in line
    assert "image scales" not in line


def test_reasoner_prompt_uses_grouped_evidence_objects() -> None:
    client = _FakeReasonerClient()
    question = QuestionEvent(
        example_id="ex",
        question="Which value (min, typ, or max) should be used?",
        doc_id="doc",
        pages_available=1,
        domain="datasheet",
        answer_type="exact_match",
    )
    packet = _packet(
        region_type="Table",
        text_layer_snippet=(
            "Parameter Test Conditions Min Typ Max Unit\n"
            "FB Error Comparator Threshold DEM 0.697 0.704 0.711 V\n"
            "Context [caption_context]: Vcc = 5V"
        ),
    )

    asyncio.run(
        answer_from_evidence(
            question,
            EvidenceEvent(packets=[packet]),
            backend_client=client,
        )
    )

    prompt = client.calls[0]["prompt"]
    assert "Available grouped evidence objects" in prompt
    assert "group_pkt_000 [table]" in prompt
    assert "Packet-level descriptors for exact span reading" in prompt
    assert "Binding frame" in prompt
    assert "cite the primary packet ids, not group ids" in prompt


def test_render_packet_line_multi_scale_packet() -> None:
    """multi_scale → annotation tells reasoner how many crops it will see."""
    p = _packet(
        multi_scale=[
            CropRef(ref="/a.png", bbox_norm=(0, 0, 1, 1), scale="tight"),
            CropRef(ref="/b.png", bbox_norm=(0, 0, 1, 1), scale="context"),
        ]
    )
    line = _render_packet_line(p)
    assert "2 image scales in order" in line
    assert "tight [0.000, 0.000, 1.000, 1.000]" in line
    assert "context [0.000, 0.000, 1.000, 1.000]" in line


def test_render_packet_line_names_zoomed_scale() -> None:
    p = _packet(
        multi_scale=[
            CropRef(ref="/a.png", bbox_norm=(0.1, 0.2, 0.5, 0.6), scale="tight"),
            CropRef(ref="/b.png", bbox_norm=(0.1, 0.2, 0.5, 0.6), scale="zoomed"),
        ]
    )
    line = _render_packet_line(p)
    assert "zoomed [0.100, 0.200, 0.500, 0.600]" in line


def test_render_packet_line_names_chart_context_scale() -> None:
    """chart_context is a distinct wider crop, not a generic neighbor."""
    p = _packet(
        multi_scale=[
            CropRef(ref="/a.png", bbox_norm=(0.1, 0.2, 0.4, 0.5), scale="tight"),
            CropRef(
                ref="/b.png",
                bbox_norm=(0.0, 0.1, 0.6, 0.7),
                scale="chart_context",
            ),
        ]
    )
    line = _render_packet_line(p)
    assert "chart_context [0.000, 0.100, 0.600, 0.700]" in line
    assert "wider crop for axes, legends, and curve geometry" in line


def test_render_packet_line_single_scale_does_not_annotate() -> None:
    """Multi-scale list of length 1 is degenerate (just tight); no annotation."""
    p = _packet(
        multi_scale=[
            CropRef(ref="/a.png", bbox_norm=(0, 0, 1, 1), scale="tight"),
        ]
    )
    line = _render_packet_line(p)
    assert "image scales" not in line


def test_render_packet_line_includes_native_text_snippet() -> None:
    p = _packet(text_layer_snippet="VCC max 3.6 V\nConditions: TA = 25 C")
    line = _render_packet_line(p)
    assert "Extracted text" in line
    assert "VCC max 3.6 V Conditions: TA = 25 C" in line


def test_render_packet_line_falls_back_to_ocr_snippet() -> None:
    p = _packet(ocr_snippet="axis label: Gross margin")
    line = _render_packet_line(p)
    assert "axis label: Gross margin" in line


def test_render_packet_line_prefers_native_text_over_ocr() -> None:
    p = _packet(text_layer_snippet="native text", ocr_snippet="ocr text")
    line = _render_packet_line(p)
    assert "native text" in line
    assert "ocr text" not in line


def test_render_packet_line_truncates_long_text_snippet() -> None:
    p = _packet(text_layer_snippet="x" * (_MAX_PACKET_TEXT_CHARS + 20))
    line = _render_packet_line(p)
    assert ("x" * _MAX_PACKET_TEXT_CHARS) not in line
    assert "..." in line


def test_render_packet_line_focuses_long_table_text_on_question_terms() -> None:
    table_text = "\n".join(
        [
            "Part Number",
            "RT9187C 2.5 5.5 600 300 Enable Input Ultra-Low Noise SOT-23-5",
            "RT2519 2.2 6 1000 190 High PSRR Industrial Grade VDFN3x3-8A",
            "RTQ2510-QA 2.2 6 1000 190",
            "Enable Input Ultra-Low Noise High PSRR AEC-Q100",
            "VDFN3x3-8",
        ]
    )
    p = _packet(text_layer_snippet=table_text + "\n" + ("filler row\n" * 80))
    line = _render_packet_line(
        p,
        question_text=(
            "Which AEC-Q100 part with Enable Input, Ultra-Low Noise, "
            "and High PSRR has the lowest Iq, and what package is it?"
        ),
    )
    assert "RTQ2510-QA" in line
    assert "AEC-Q100" in line
    assert "VDFN3x3-8" in line
    assert "RT9187C" not in line


# ---------------------------------------------------------------------------
# Sprint Phase 3: chart_csv rendering in the prompt
# ---------------------------------------------------------------------------


def test_render_packet_line_includes_chart_csv_when_present() -> None:
    """Phase 3: chart_to_table CSV appears in a fenced code block."""
    p = _packet(
        local_crop_ref="/cache/chart.png",
    )
    p.chart_csv = "x_value,y_value\n0.0,2.5\n1.0,3.7"
    p.chart_extraction_confidence = 0.78
    line = _render_packet_line(p)
    assert "Chart extraction" in line
    assert "confidence=0.78" in line
    assert "```csv" in line
    assert "x_value,y_value" in line
    assert "0.0,2.5" in line


def test_render_packet_line_omits_chart_csv_when_none() -> None:
    p = _packet()
    line = _render_packet_line(p)
    assert "Chart extraction" not in line
    assert "```csv" not in line


def test_render_packet_line_chart_without_confidence_renders_advisory() -> None:
    p = _packet()
    p.chart_csv = "x_value,y_value\n5,10"
    p.chart_extraction_confidence = None
    line = _render_packet_line(p)
    assert "Chart extraction" in line
    assert "advisory" in line
    assert "confidence=" not in line


def test_numeric_format_hint_preserves_requested_units() -> None:
    hint = _format_hint("numeric")
    assert "single number" in hint
    assert "requested unit" in hint
    assert "% sign" in hint


def test_exact_match_format_hint_overrides_explain_wording() -> None:
    hint = _format_hint("exact_match")
    assert "only the final exact answer" in hint
    assert "Even if the question asks for an explanation" in hint
    assert "omit spaces around '='" in hint


def test_exact_match_format_hint_phase6a_tightening_rules_present() -> None:
    """Phase 6a (2026-05-11 evening): four extraction-format rules added
    based on the Phase 4 failure analysis. Each rule maps to a sampled
    failure pattern in the n=148 right-region-wrong bucket."""
    hint = _format_hint("exact_match")
    # Rule 1: no leading labels (Gross margin example)
    assert "Gross margin" in hint
    # Rule 2: no trailing descriptions (Reserved. RAZ. example)
    assert "Reserved" in hint
    # Rule 3: include all parts of multi-part answers (BLE / semicolons)
    assert "multi-part" in hint or "all parts" in hint.lower()
    # Rule 4: no conditional/alternative branches (HIVECS example)
    assert "conditional" in hint.lower() or "alternative" in hint.lower()
    # Existing bit-field rule preserved
    assert "[15:14]=b00" in hint


def test_exact_match_format_hint_default_is_datasheet_strict() -> None:
    """Phase 3a (2026-05-13 sprint): the default (no-domain) prompt stays on
    the datasheet-strict variant — back-compat for callers that haven't
    plumbed `domain` yet."""
    hint = _format_hint("exact_match")
    hint_datasheet = _format_hint("exact_match", domain="datasheet")
    hint_datasheet_enum = _format_hint("exact_match", domain="Domain.DATASHEET")
    assert hint == hint_datasheet == hint_datasheet_enum
    # Datasheet strict prompt: rule 1 says "Output ONLY the answer span"
    assert "Output ONLY the answer span" in hint
    # Tied-answer rule (Phase 3a addendum) is present in the datasheet prompt
    assert "tied" in hint.lower()


def test_exact_match_format_hint_finance_sentence_form_variant_fires_only_for_specific_families() -> (
    None
):
    """Phase 3a v2 (2026-05-13 sprint): the relaxed finance variant is gated
    on question_family. Sentence-form-prone families
    (`chart_caption_fusion`, `multi_chart_comparison`, etc.) get the relaxed
    prompt that allows descriptive clauses; everything else stays strict.

    Why: the v1 release blindly relaxed all finance prompts, which caused
    over-extraction on short-label finance golds (author names, ticker
    strings) — e.g. 'Stephanie Aliaga' became 'Stephanie Aliaga — her
    portrait is in the leftmost column'. v2 routes by question_family so
    short-label finance answers keep the strict datasheet prompt."""
    relaxed = _format_hint("exact_match", domain="finance", question_family="chart_caption_fusion")
    assert "descriptive sentence" in relaxed.lower() or "descriptive clause" in relaxed.lower()
    assert "Output ONLY the answer span" not in relaxed
    assert (
        "do not pad short answers" in relaxed.lower() or "favor a short answer" in relaxed.lower()
    )

    # Finance + non-sentence-form family -> strict datasheet variant
    strict = _format_hint("exact_match", domain="finance", question_family="direct_label_reading")
    assert "Output ONLY the answer span" in strict
    assert strict == _format_hint("exact_match", domain="datasheet")

    # Finance + None family -> falls back to strict (conservative)
    assert _format_hint("exact_match", domain="finance", question_family=None) == strict

    # Datasheet + ANY question_family -> always strict, regardless of family
    for fam in ("chart_caption_fusion", "spec_table_cell_retrieval", None):
        assert _format_hint("exact_match", domain="datasheet", question_family=fam) == strict


def test_exact_match_format_hint_unknown_domain_falls_back_to_datasheet() -> None:
    """Phase 3a (2026-05-13 sprint): unknown / None domain falls back to the
    datasheet strict prompt, which is what main-stack-run1 used."""
    assert _format_hint("exact_match", domain=None) == _format_hint(
        "exact_match", domain="datasheet"
    )
    assert _format_hint("exact_match", domain="unknown") == _format_hint(
        "exact_match", domain="datasheet"
    )


def test_parse_reasoner_response_canonicalizes_bit_assignments() -> None:
    answer, citations, confidence = _parse_reasoner_response(
        (
            '{"answer":"[15:14] = b00; [8:5] = b1111; [4:3] = b11",'
            '"citations":["pkt_000"],"confidence":0.98}'
        ),
        valid_packet_ids={"pkt_000"},
    )

    assert answer == "[15:14]=b00, [8:5]=b1111, [4:3]=b11"
    assert citations == ["pkt_000"]
    assert confidence == 0.98


def test_parse_reasoner_response_keeps_verbose_bit_prose_unchanged() -> None:
    answer, _citations, _confidence = _parse_reasoner_response(
        (
            '{"answer":"[15:14] = b00 because the table says secure or non-secure; '
            '[8:5] = b1111","citations":[],"confidence":0.5}'
        ),
        valid_packet_ids=set(),
    )

    assert "because" in answer


# ---------------------------------------------------------------------------
# Path A: linked_neighbor_types appear in the descriptor
# ---------------------------------------------------------------------------


def test_render_packet_line_lists_neighbor_types() -> None:
    """The reasoner sees which images that follow are context, by role."""
    p = _packet(
        linked_crop_refs=["/cache/cap.png", "/cache/foot.png"],
        linked_neighbor_types=["caption", "footnote"],
    )
    line = _render_packet_line(p)
    assert "Attached neighbor images (2)" in line
    assert "caption, footnote" in line


def test_render_packet_line_omits_neighbors_when_empty() -> None:
    p = _packet()  # no linked_neighbor_types
    line = _render_packet_line(p)
    assert "Attached neighbor" not in line


def test_render_packet_line_neighbor_count_matches_types() -> None:
    """Three image neighbors -> "Attached neighbor images (3)"."""
    p = _packet(
        linked_crop_refs=["/a", "/b", "/c"],
        linked_neighbor_types=["caption", "footnote", "section_header"],
    )
    line = _render_packet_line(p)
    assert "Attached neighbor images (3)" in line
    assert "section_header" in line


def test_render_packet_line_explains_context_window() -> None:
    """Verifier retry context windows are described as wider same-packet crops."""
    p = _packet(
        linked_crop_refs=["/cache/context.png"],
        linked_neighbor_types=["context_window"],
    )
    line = _render_packet_line(p)
    assert "Attached neighbor images (1): context_window" in line
    assert "wider crop around the same packet" in line
    assert "row/column headers" in line


def test_render_packet_line_lists_text_only_neighbor_context() -> None:
    p = _packet(
        linked_crop_refs=["/cache/section.png", "/cache/caption.png"],
        linked_neighbor_types=["section_header", "caption"],
        text_layer_snippet=(
            "Context [section_header]: Absolute Maximum Ratings\n"
            "Context [caption]: Figure 7. Output ripple"
        ),
    )
    line = _render_packet_line(p)
    assert "Attached neighbor images (1): caption" in line
    assert "Attached text-only context (1): section_header='Absolute Maximum Ratings'" in line


# ---------------------------------------------------------------------------
# Path A: system prompt explains the primary-vs-context layout
# ---------------------------------------------------------------------------


def test_system_prompt_explains_neighbor_layout() -> None:
    """The reasoner's system prompt tells the LLM that neighbor images
    means the images that follow are CONTEXT — not the primary focus."""
    from focusparse.pipeline.reasoner import _SYSTEM_PROMPT

    assert "Attached neighbor images" in _SYSTEM_PROMPT
    assert "Attached text-only context" in _SYSTEM_PROMPT
    assert "primary crop" in _SYSTEM_PROMPT
    assert "context_window" in _SYSTEM_PROMPT
    assert "zoomed" in _SYSTEM_PROMPT
    assert "context" in _SYSTEM_PROMPT.lower()


# ---------------------------------------------------------------------------
# Phase 3b (2026-05-14 sprint): K-sample self-consistency
# ---------------------------------------------------------------------------


def test_phase3b_sample_variant_addendum_empty_for_variant_zero() -> None:
    """Phase 3b: variant 0 is the back-compat default — no prompt change."""
    from focusparse.pipeline.reasoner import _sample_variant_addendum

    assert _sample_variant_addendum(0) == ""


def test_phase3b_sample_variant_addendum_variant_one_has_verbatim_grounding() -> None:
    """Phase 3b: variant 1 nudges the model to anchor its answer in the
    cited packet's verbatim wording. K=2 with same prompt on a low-temp
    model usually returns identical samples; this addendum gives variant
    1 a different angle so the K samples explore independent paths."""
    from focusparse.pipeline.reasoner import _sample_variant_addendum

    text = _sample_variant_addendum(1)
    assert "exact span" in text.lower()
    assert "cited packet" in text.lower() or "cited packets" in text.lower()


def test_phase3b_sample_variant_addendum_variant_two_has_skeptical_reread() -> None:
    """Phase 3b (2026-05-15 expansion for K=3): variant 2 asks the model
    to enumerate competing readings before picking the most concrete
    answer. Targets close-numeric estimation failures (`0.4 vs 0.5`
    chart reads) where the picker can't disambiguate from confidence
    alone. Distinct from variant 1's verbatim-grounding angle."""
    from focusparse.pipeline.reasoner import _sample_variant_addendum

    text = _sample_variant_addendum(2)
    # Variant 2 must be a non-empty distinct prompt from variants 0 and 1.
    assert text != ""
    assert text != _sample_variant_addendum(1)
    # The defining mechanism: enumerate competing readings, then pick the
    # most concrete / axis-anchored one.
    assert "enumerate" in text.lower() or "1-3" in text or "axis" in text.lower()


def test_phase3b_sample_variant_addendum_over_k_cycles_to_empty() -> None:
    """Phase 3b: variants 3+ fall back to the empty (variant-0)
    addendum so K>3 still works without unbounded prompt drift —
    additional samples just exploit model stochasticity."""
    from focusparse.pipeline.reasoner import _sample_variant_addendum

    assert _sample_variant_addendum(3) == ""
    assert _sample_variant_addendum(5) == ""


def test_phase3b_pick_best_answer_prefers_non_unanswerable() -> None:
    """Picker rule 1: any concrete answer beats `Unanswerable`."""
    from focusparse.pipeline.events import AnswerEvent
    from focusparse.pipeline.reasoner import pick_best_answer

    samples = [
        AnswerEvent(answer="Unanswerable", citations=["pkt_000"], confidence=0.9),
        AnswerEvent(answer="0x3FFFF8", citations=["pkt_000"], confidence=0.5),
    ]
    assert pick_best_answer(samples, answer_type="exact_match") == 1


def test_phase3b_pick_best_answer_prefers_more_citations() -> None:
    """Picker rule 2: more citations wins (citation count ranks before length
    and confidence)."""
    from focusparse.pipeline.events import AnswerEvent
    from focusparse.pipeline.reasoner import pick_best_answer

    samples = [
        AnswerEvent(answer="b0010", citations=["pkt_000"], confidence=0.9),
        AnswerEvent(answer="b0010", citations=["pkt_000", "pkt_001"], confidence=0.5),
    ]
    assert pick_best_answer(samples, answer_type="exact_match") == 1


def test_phase3b_pick_best_answer_prefers_shorter_for_exact_match() -> None:
    """Picker rule 3: for exact_match / numeric the format hints push for
    a concise span — a verbose sample is the model padding. Pick the
    shorter answer when citation counts are equal."""
    from focusparse.pipeline.events import AnswerEvent
    from focusparse.pipeline.reasoner import pick_best_answer

    samples = [
        AnswerEvent(
            answer="Stephanie Aliaga — her portrait is in the leftmost column",
            citations=["pkt_000"],
            confidence=0.7,
        ),
        AnswerEvent(answer="Stephanie Aliaga", citations=["pkt_000"], confidence=0.7),
    ]
    assert pick_best_answer(samples, answer_type="exact_match") == 1


def test_phase3b_pick_best_answer_higher_confidence_breaks_tie() -> None:
    """Picker rule 4: when non-Unanswerable, citation count, and length all
    tie, higher self-reported confidence wins."""
    from focusparse.pipeline.events import AnswerEvent
    from focusparse.pipeline.reasoner import pick_best_answer

    samples = [
        AnswerEvent(answer="70%", citations=["pkt_000"], confidence=0.4),
        AnswerEvent(answer="70%", citations=["pkt_000"], confidence=0.9),
    ]
    assert pick_best_answer(samples, answer_type="exact_match") == 1


def test_phase3b_pick_best_answer_index_zero_breaks_final_tie() -> None:
    """Picker rule 5: total tie → keep sample 0 (back-compat with k=1
    behavior)."""
    from focusparse.pipeline.events import AnswerEvent
    from focusparse.pipeline.reasoner import pick_best_answer

    samples = [
        AnswerEvent(answer="70%", citations=["pkt_000"], confidence=0.5),
        AnswerEvent(answer="70%", citations=["pkt_000"], confidence=0.5),
    ]
    assert pick_best_answer(samples, answer_type="exact_match") == 0


def test_phase3b_pick_best_answer_does_not_prefer_short_for_freeform() -> None:
    """For answer types without a concise-span format hint (None /
    unknown), shorter is NOT preferred — only citation count + confidence
    matter. This keeps the picker from arbitrarily truncating valid long
    answers."""
    from focusparse.pipeline.events import AnswerEvent
    from focusparse.pipeline.reasoner import pick_best_answer

    samples = [
        AnswerEvent(
            answer="A very long, detailed answer that is correct.",
            citations=["pkt_000"],
            confidence=0.5,
        ),
        AnswerEvent(answer="short wrong answer", citations=["pkt_000"], confidence=0.5),
    ]
    # No answer_type → no preference for shorter, so index 0 wins on tie.
    assert pick_best_answer(samples, answer_type=None) == 0


def test_phase3b_pick_best_answer_single_sample_returns_zero() -> None:
    """Picker on a single sample is a no-op."""
    from focusparse.pipeline.events import AnswerEvent
    from focusparse.pipeline.reasoner import pick_best_answer

    samples = [AnswerEvent(answer="x", citations=[], confidence=0.5)]
    assert pick_best_answer(samples, answer_type="exact_match") == 0


def test_phase3b_v2_consensus_wins_over_outlier_confidence() -> None:
    """Phase 3b v2 (2026-05-15): K=3 with majority-agreement should pick
    the consensus answer even when a high-confidence outlier disagrees.
    This is the lever for close-numeric chart reads where the model's
    spread is ['0.4', '0.4', '0.5'] — heuristic-only picker prefers
    confidence; consensus picker prefers the 2-vote answer."""
    from focusparse.pipeline.events import AnswerEvent
    from focusparse.pipeline.reasoner import pick_best_answer

    samples = [
        AnswerEvent(answer="0.4", citations=["pkt_000"], confidence=0.5),
        AnswerEvent(answer="0.4", citations=["pkt_000"], confidence=0.5),
        AnswerEvent(answer="0.5", citations=["pkt_000"], confidence=0.95),
    ]
    # Consensus is "0.4" (2/3). Picker should return index 0 or 1 (both
    # match), not index 2 (the high-confidence outlier).
    assert pick_best_answer(samples, answer_type="numeric") in (0, 1)


def test_phase3b_v2_consensus_normalizes_whitespace_and_case() -> None:
    """Phase 3b v2: consensus bucketing collapses whitespace and case
    so trivial formatting differences don't split the vote. Samples
    [' 0.4 ', '0.4', '0.5'] still vote as ['0.4', '0.4', '0.5'] =
    majority '0.4'."""
    from focusparse.pipeline.events import AnswerEvent
    from focusparse.pipeline.reasoner import pick_best_answer

    samples = [
        AnswerEvent(answer=" 0.4 ", citations=["pkt_000"], confidence=0.6),
        AnswerEvent(answer="0.4", citations=["pkt_000"], confidence=0.6),
        AnswerEvent(answer="0.5", citations=["pkt_000"], confidence=0.9),
    ]
    assert pick_best_answer(samples, answer_type="numeric") in (0, 1)


def test_phase3b_v2_no_consensus_falls_back_to_heuristic() -> None:
    """Phase 3b v2: when K=3 produces three distinct answers (no
    majority), the heuristic ordering takes over (citation count,
    confidence, length, index)."""
    from focusparse.pipeline.events import AnswerEvent
    from focusparse.pipeline.reasoner import pick_best_answer

    samples = [
        AnswerEvent(answer="A", citations=["pkt_000"], confidence=0.5),
        AnswerEvent(answer="B", citations=["pkt_000"], confidence=0.8),
        AnswerEvent(answer="C", citations=["pkt_000"], confidence=0.6),
    ]
    # No consensus → heuristic falls through to confidence; B wins.
    assert pick_best_answer(samples, answer_type="exact_match") == 1


def test_phase3b_v2_consensus_excludes_unanswerable() -> None:
    """Phase 3b v2: Unanswerable doesn't count toward consensus. With
    ['Unanswerable', 'Unanswerable', '42'] the picker should still
    prefer the concrete '42' over the abstention majority."""
    from focusparse.pipeline.events import AnswerEvent
    from focusparse.pipeline.reasoner import pick_best_answer

    samples = [
        AnswerEvent(answer="Unanswerable", citations=["pkt_000"], confidence=0.5),
        AnswerEvent(answer="Unanswerable", citations=["pkt_000"], confidence=0.5),
        AnswerEvent(answer="42", citations=["pkt_000"], confidence=0.7),
    ]
    # Consensus excludes Unanswerable → falls back to heuristic →
    # non-Unanswerable wins (rule 1).
    assert pick_best_answer(samples, answer_type="numeric") == 2


def test_phase3b_v2_k_equals_two_skips_consensus() -> None:
    """Phase 3b v2: K=2 doesn't use consensus (no majority possible from
    2 samples) and falls straight to the heuristic. Existing K=2
    behavior is preserved."""
    from focusparse.pipeline.events import AnswerEvent
    from focusparse.pipeline.reasoner import pick_best_answer

    samples = [
        AnswerEvent(answer="A", citations=["pkt_000"], confidence=0.4),
        AnswerEvent(answer="A", citations=["pkt_000"], confidence=0.9),
    ]
    # Both samples agree on "A", but K=2 skips consensus and uses
    # heuristic; higher confidence wins → index 1.
    assert pick_best_answer(samples, answer_type="exact_match") == 1


# ---------------------------------------------------------------------------
# 2026-05-15: scorer-compatible answer-shape normalization
# ---------------------------------------------------------------------------


def test_answer_shape_normalizes_finance_accounting_negative() -> None:
    from focusparse.pipeline.reasoner import _normalize_answer_shape

    assert (
        _normalize_answer_shape(
            "$(40) million",
            answer_type="numeric",
            domain="finance",
        )
        == "-40"
    )


def test_answer_shape_normalizes_verbose_finance_accounting_negative() -> None:
    from focusparse.pipeline.reasoner import _normalize_answer_shape

    assert (
        _normalize_answer_shape(
            "$(40) million; the bar is shown in parentheses in the financing section",
            answer_type="numeric",
            domain="finance",
        )
        == "-40"
    )


def test_answer_shape_leaves_datasheet_parentheses_alone() -> None:
    from focusparse.pipeline.reasoner import _normalize_answer_shape

    assert (
        _normalize_answer_shape(
            "(40) kΩ",
            answer_type="numeric",
            domain="datasheet",
        )
        == "(40) kΩ"
    )


def test_answer_shape_spaces_variable_value_units() -> None:
    from focusparse.pipeline.reasoner import _normalize_answer_shape

    assert (
        _normalize_answer_shape(
            "Vgs=2.9V",
            answer_type="exact_match",
            domain="datasheet",
        )
        == "Vgs = 2.9 V"
    )


def test_answer_shape_formats_page_reference() -> None:
    from focusparse.pipeline.reasoner import _normalize_answer_shape

    assert (
        _normalize_answer_shape(
            "Cache type register and TCM type register on page B3-10",
            answer_type="exact_match",
            domain="datasheet",
        )
        == "Cache type register and TCM type register; page B3-10"
    )


def test_answer_shape_formats_min_typ_max_list() -> None:
    from focusparse.pipeline.reasoner import _normalize_answer_shape

    assert (
        _normalize_answer_shape(
            "min=0.697V; typ=0.704V; max=0.711V",
            answer_type="exact_match",
            domain="datasheet",
        )
        == "min: 0.697 V, typ: 0.704 V, max: 0.711 V"
    )


def test_answer_shape_collapses_verbose_boolean_answers() -> None:
    from focusparse.pipeline.reasoner import _normalize_answer_shape

    assert (
        _normalize_answer_shape(
            "Yes; the referenced note shows the item is included.",
            answer_type="boolean",
            domain="finance",
        )
        == "yes"
    )
    assert (
        _normalize_answer_shape(
            "The answer is false because the row is not present.",
            answer_type="boolean",
            domain="datasheet",
        )
        == "no"
    )


def test_answer_shape_normalizes_label_prefixed_hex_span() -> None:
    from focusparse.pipeline.reasoner import _normalize_answer_shape

    assert (
        _normalize_answer_shape(
            "Serializer Lanes Enabled; OxFF (SERDINO to SERDIN7)",
            answer_type="exact_match",
            domain="datasheet",
        )
        == "0xFF (SERDIN0 to SERDIN7)"
    )


def test_answer_shape_collapses_leading_code_identifier_explanation() -> None:
    from focusparse.pipeline.reasoner import _normalize_answer_shape

    assert (
        _normalize_answer_shape(
            "DPD MODE1. The model is updated when the rms power exceeds the previous maximum.",
            answer_type="exact_match",
            domain="datasheet",
        )
        == "DPD_MODE1"
    )


def test_answer_shape_does_not_collapse_plain_sentence_explanation() -> None:
    from focusparse.pipeline.reasoner import _normalize_answer_shape

    assert (
        _normalize_answer_shape(
            "Primary mode. The table describes the setting.",
            answer_type="exact_match",
            domain="datasheet",
        )
        == "Primary mode. The table describes the setting."
    )


def test_answer_shape_keeps_parenthesized_hex_identifier_phrase() -> None:
    from focusparse.pipeline.reasoner import _normalize_answer_shape

    assert (
        _normalize_answer_shape(
            "r0 (0x5)",
            answer_type="exact_match",
            domain="datasheet",
        )
        == "r0 (0x5)"
    )


def test_answer_shape_does_not_parenthesize_tickers() -> None:
    from focusparse.pipeline.reasoner import _normalize_answer_shape

    assert (
        _normalize_answer_shape(
            "GOOG",
            answer_type="exact_match",
            domain="finance",
        )
        == "GOOG"
    )
