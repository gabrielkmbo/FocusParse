"""Derived evidence groups for post-evidence reasoning.

EvidenceEvent stays a list of EvidencePacket objects for schema stability, but
reasoner/verifier prompts should not treat those packets as loose snippets.
This module builds a compact grouped view:

- datasheet tables: primary row/text + headers/units/conditions/notes/caption
- finance charts: plot/visual region + legend/series/axes/caption/footnote

The grouping is gold-free and inferred only from packet metadata/text.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

from focusparse.evidence.packet import EvidencePacket
from focusparse.pipeline.answer_contract import AnswerContract

EvidenceGroupKind = Literal["table", "chart", "visual", "text"]


@dataclass(frozen=True)
class EvidenceGroup:
    """Prompt-facing evidence object built from one primary packet."""

    group_id: str
    primary_packet_id: str
    page: int
    bbox_norm: tuple[float, float, float, float]
    group_kind: EvidenceGroupKind
    primary_region_type: str | None
    focus_text: str
    context_by_role: dict[str, tuple[str, ...]] = field(default_factory=dict)
    linked_neighbor_types: tuple[str, ...] = ()
    has_chart_csv: bool = False
    chart_csv: str | None = None


_CONTEXT_LINE_RE = re.compile(r"^Context\s+\[(?P<role>[^\]]+)\]:\s*(?P<text>.*)$", re.I)
_WORD_RE = re.compile(r"[a-z0-9_]+", re.I)
_PRIMARY_TEXT_MAX_CHARS = 900
_CONTEXT_TEXT_MAX_CHARS = 220
_CHART_CSV_MAX_CHARS = 500
_MAX_CONTEXT_ROLES = 8
_MAX_CONTEXT_VALUES_PER_ROLE = 2

_TABLE_REGION_TYPES = frozenset({"table", "table cell", "table_cell", "key-value region"})
_CHART_REGION_TYPES = frozenset(
    {
        "bar_chart",
        "candlestick",
        "chart",
        "curve",
        "figure",
        "line_chart",
        "plot",
    }
)
_VISUAL_REGION_TYPES = frozenset(
    {"diagram", "figure", "image", "picture", "plot", "screenshot", "visual"}
)
_ATTACHED_IMAGE_SENTINEL = "(attached image/crop)"


def build_evidence_groups(
    packets: Iterable[EvidencePacket],
    *,
    question_text: str | None = None,
    contract: AnswerContract | None = None,
) -> list[EvidenceGroup]:
    """Build one grouped evidence object per primary packet."""

    return [
        _build_group(packet, question_text=question_text, contract=contract) for packet in packets
    ]


def render_evidence_groups(
    groups: Iterable[EvidenceGroup],
    *,
    contract: AnswerContract | None = None,
    cited_packet_ids: set[str] | None = None,
) -> str:
    """Render groups as a compact prompt block."""

    rendered: list[str] = []
    for group in groups:
        cited = ""
        if cited_packet_ids is not None:
            cited = (
                f" cited_by_answer={'yes' if group.primary_packet_id in cited_packet_ids else 'no'}"
            )
        rendered.append(
            f"- {group.group_id} [{group.group_kind}] primary={group.primary_packet_id}"
            f" page={group.page} bbox={_format_bbox(group.bbox_norm)}"
            f" region={group.primary_region_type or 'unknown'}{cited}"
        )
        binding = _binding_frame(group.group_kind, contract)
        if binding:
            rendered.append(f"  Binding frame: {binding}")
        if group.focus_text:
            rendered.append(
                f"  Primary text: {_quote(_truncate(group.focus_text, _PRIMARY_TEXT_MAX_CHARS))}"
            )
        context = _render_context(group.context_by_role)
        if context:
            rendered.append(f"  Context roles: {context}")
        if group.chart_csv:
            rendered.append(
                "  Chart extraction: " + _quote(_truncate(group.chart_csv, _CHART_CSV_MAX_CHARS))
            )
    if not rendered:
        return "(no evidence groups)"
    return "\n".join(rendered)


def _build_group(
    packet: EvidencePacket,
    *,
    question_text: str | None,
    contract: AnswerContract | None,
) -> EvidenceGroup:
    raw_text = packet.text_layer_snippet or packet.ocr_snippet or ""
    primary_text, context_by_role = _split_primary_and_context(raw_text)
    linked_neighbor_types = tuple(_normalize_role(role) for role in packet.linked_neighbor_types)
    context_by_role = _merge_linked_neighbor_roles(context_by_role, linked_neighbor_types)
    focus_text = _focus_text(primary_text or raw_text, question_text=question_text)
    group_kind = _classify_group(packet, focus_text, contract=contract)
    return EvidenceGroup(
        group_id=f"group_{packet.packet_id}",
        primary_packet_id=packet.packet_id,
        page=packet.page,
        bbox_norm=packet.bbox_norm,
        group_kind=group_kind,
        primary_region_type=packet.region_type,
        focus_text=focus_text,
        context_by_role=context_by_role,
        linked_neighbor_types=linked_neighbor_types,
        has_chart_csv=bool(packet.chart_csv),
        chart_csv=packet.chart_csv,
    )


def _classify_group(
    packet: EvidencePacket,
    focus_text: str,
    *,
    contract: AnswerContract | None,
) -> EvidenceGroupKind:
    region = _normalize_region_type(packet.region_type)
    if packet.chart_csv or region in _CHART_REGION_TYPES:
        return "chart"
    if contract and contract.chart_binding_required and region in _VISUAL_REGION_TYPES:
        return "chart"
    if region in _TABLE_REGION_TYPES or _looks_like_table_text(focus_text):
        return "table"
    if region in _VISUAL_REGION_TYPES:
        return "visual"
    return "text"


def _binding_frame(group_kind: EvidenceGroupKind, contract: AnswerContract | None) -> str:
    if group_kind == "table":
        frame = "bind the answer to one table row, its row label, column headers, units, test conditions, and notes"
    elif group_kind == "chart":
        frame = "bind the answer to the plot area, legend/series style, axes/ticks, caption, and footnotes"
    elif group_kind == "visual":
        frame = (
            "bind the answer to the visual region plus any caption/header/nearby explanatory text"
        )
    else:
        frame = "bind the answer to the cited text and any attached context"

    contract_bits: list[str] = []
    if contract:
        if contract.requires_min_typ_max:
            contract_bits.append("preserve min/typ/max labels")
        if contract.requires_multi_field:
            contract_bits.append("complete all requested fields")
        if contract.requires_quantitative_value:
            contract_bits.append("return values, not just labels")
        if contract.chart_binding_required:
            contract_bits.append("check series/legend/axis binding")
        if contract.row_disambiguation_cues:
            contract_bits.append(
                "disambiguate row cues=" + ",".join(contract.row_disambiguation_cues)
            )
    if contract_bits:
        frame += "; contract: " + "; ".join(contract_bits)
    return frame


def _split_primary_and_context(text: str) -> tuple[str, dict[str, tuple[str, ...]]]:
    primary_lines: list[str] = []
    context: dict[str, list[str]] = {}
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _CONTEXT_LINE_RE.match(line)
        if match:
            role = _normalize_role(match.group("role"))
            value = _truncate(" ".join(match.group("text").split()), _CONTEXT_TEXT_MAX_CHARS)
            if value:
                context.setdefault(role, []).append(value)
        else:
            primary_lines.append(line)
    return "\n".join(primary_lines), {
        role: tuple(_dedupe(values)) for role, values in context.items()
    }


def _merge_linked_neighbor_roles(
    context_by_role: dict[str, tuple[str, ...]],
    linked_neighbor_types: tuple[str, ...],
) -> dict[str, tuple[str, ...]]:
    merged: dict[str, list[str]] = {role: list(values) for role, values in context_by_role.items()}
    for role in linked_neighbor_types:
        values = merged.setdefault(role, [])
        if not values:
            values.append(_ATTACHED_IMAGE_SENTINEL)
    return {role: tuple(_dedupe(values)) for role, values in merged.items()}


def _render_context(context_by_role: dict[str, tuple[str, ...]]) -> str:
    parts: list[str] = []
    for role in sorted(context_by_role)[:_MAX_CONTEXT_ROLES]:
        values = list(context_by_role[role])[:_MAX_CONTEXT_VALUES_PER_ROLE]
        if not values:
            continue
        joined = " | ".join(_quote(_truncate(value, _CONTEXT_TEXT_MAX_CHARS)) for value in values)
        parts.append(f"{role}={joined}")
    return "; ".join(parts)


def _focus_text(text: str, *, question_text: str | None) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= _PRIMARY_TEXT_MAX_CHARS or not question_text:
        return _truncate(normalized, _PRIMARY_TEXT_MAX_CHARS)

    lines = [line.strip() for line in str(text).splitlines() if line.strip()]
    proposed_answer = _extract_proposed_answer(question_text)
    if proposed_answer:
        answer_tokens = set(_WORD_RE.findall(proposed_answer.lower()))
        answer_norm = _normalize_match_text(proposed_answer)
        selected: set[int] = set()
        for idx, line in enumerate(lines):
            line_tokens = set(_WORD_RE.findall(line.lower()))
            line_norm = _normalize_match_text(line)
            if answer_norm in line_norm or (answer_tokens and answer_tokens <= line_tokens):
                selected.update({idx, idx + 1})
        if selected:
            chosen = " / ".join(lines[idx] for idx in sorted(selected) if 0 <= idx < len(lines))
            return _truncate(" ".join(chosen.split()), _PRIMARY_TEXT_MAX_CHARS)

    q_tokens = set(_WORD_RE.findall(str(question_text).lower()))
    if not q_tokens:
        return _truncate(normalized, _PRIMARY_TEXT_MAX_CHARS)

    scored: list[tuple[int, int]] = []
    for idx, line in enumerate(lines):
        overlap = len(q_tokens & set(_WORD_RE.findall(line.lower())))
        if overlap:
            scored.append((overlap, idx))
    if not scored:
        return _truncate(normalized, _PRIMARY_TEXT_MAX_CHARS)

    selected: set[int] = set()
    for _overlap, idx in sorted(scored, reverse=True)[:4]:
        selected.update({idx - 1, idx, idx + 1})
    chosen = " / ".join(lines[idx] for idx in sorted(selected) if 0 <= idx < len(lines))
    return _truncate(" ".join(chosen.split()), _PRIMARY_TEXT_MAX_CHARS)


def _extract_proposed_answer(focus_text: str | None) -> str:
    if not focus_text:
        return ""
    match = re.search(r"^Proposed answer:\s*(?P<answer>.+)$", str(focus_text), re.I | re.M)
    return match.group("answer").strip() if match else ""


def _normalize_match_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


def _normalize_role(role: str | None) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", str(role or "").lower()).strip("_")
    aliases = {
        "axis": "axis",
        "axis_label": "axis",
        "caption": "caption",
        "caption_context": "caption",
        "column_header": "column_header",
        "context_window": "context_window",
        "footnote": "footnote",
        "footer": "footer",
        "header": "header",
        "header_disambiguation": "header",
        "legend": "legend",
        "legend_binding": "legend",
        "page_footer": "footer",
        "page_header": "header",
        "row_header": "row_header",
        "section_header": "header",
        "table_cell_lookup": "table_context",
        "title": "title",
        "unit": "unit",
        "x_axis": "axis",
        "y_axis": "axis",
    }
    return aliases.get(key, key or "context")


def _normalize_region_type(region_type: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(region_type or "").lower()).strip("_")


def _looks_like_table_text(text: str) -> bool:
    lower = text.lower()
    if "|" in text:
        return True
    table_terms = {"parameter", "test", "condition", "unit", "min", "typ", "max"}
    return len(table_terms & set(_WORD_RE.findall(lower))) >= 3


def _truncate(text: str, max_chars: int) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _quote(text: str) -> str:
    return repr(text)


def _format_bbox(bbox: tuple[float, float, float, float]) -> str:
    return "[" + ", ".join(f"{value:.3f}" for value in bbox) + "]"


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out
