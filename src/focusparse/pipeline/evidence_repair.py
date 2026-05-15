"""Same-evidence repair context for verifier-directed retries.

These helpers are deterministic and gold-free. They do not retrieve new
evidence; they only repackage the packets already available to the reasoner so
row, field, chart, and checkbox repairs have concrete candidate material.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from focusparse.evidence.packet import EvidencePacket
from focusparse.pipeline.events import AnswerEvent, EvidenceEvent, QuestionEvent

_WORD_RE = re.compile(r"[a-z0-9_]+", re.IGNORECASE)
_VALUE_RE = re.compile(r"0x[0-9a-f]+h?|b[01x]+|\$?\(?-?\d+(?:,\d{3})*(?:\.\d+)?\)?%?", re.I)
_CHECKBOX_RE = re.compile(
    r"\b(?:yes|no|checked|unchecked|check\s*mark|checkbox)\b|\[\s*x\s*\]|\b[xX]\b|[☑✓✔]",
    re.I,
)
_CHART_LINE_RE = re.compile(
    r"\b(?:legend|series|axis|axes|caption|figure|panel|line|bar|curve|footnote|marker)\b",
    re.IGNORECASE,
)
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "as",
        "at",
        "be",
        "by",
        "does",
        "for",
        "from",
        "has",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "the",
        "this",
        "to",
        "was",
        "were",
        "what",
        "which",
        "with",
    }
)
_WEAK_REPAIR_TOKENS = frozenset(
    {
        "among",
        "amount",
        "amounts",
        "compare",
        "corresponding",
        "highest",
        "lowest",
        "maximum",
        "minimum",
        "net",
        "row",
        "sales",
        "shown",
        "table",
        "three",
        "value",
        "values",
        "year",
        "years",
    }
)
_ROW_FAILURES = frozenset(
    {"wrong_row_risk", "missing_field", "label_value_mismatch", "checkbox_binding_risk"}
)
_MAX_LINES = 6
_MAX_LINE_CHARS = 240
_MAX_CHART_CSV_CHARS = 500


def build_same_evidence_repair_context(
    question: QuestionEvent,
    evidence: EvidenceEvent | None,
    answer: AnswerEvent,
    failures: Iterable[str],
) -> str:
    """Build a compact repair context from current packets only."""

    failure_set = {str(failure) for failure in failures}
    if not failure_set or evidence is None or not evidence.packets:
        return ""

    sections: list[str] = []
    if failure_set & _ROW_FAILURES:
        rows = _candidate_rows(
            evidence.packets,
            question_text=question.question,
            answer_text=answer.answer,
            cited_packet_ids=set(answer.citations or []),
            checkbox_mode="checkbox_binding_risk" in failure_set,
        )
        if rows:
            sections.append("Candidate rows/lines:\n" + "\n".join(f"- {row}" for row in rows))

    if "legend_binding_risk" in failure_set:
        chart_lines = _chart_binding_lines(
            evidence.packets,
            question_text=question.question,
            cited_packet_ids=set(answer.citations or []),
        )
        if chart_lines:
            sections.append(
                "Chart binding lines:\n" + "\n".join(f"- {line}" for line in chart_lines)
            )

    if not sections:
        return ""
    return (
        "Same-evidence repair context (derived only from current packets; not gold):\n"
        + "\n".join(sections)
    )


def _candidate_rows(
    packets: Iterable[EvidencePacket],
    *,
    question_text: str,
    answer_text: str,
    cited_packet_ids: set[str],
    checkbox_mode: bool,
) -> list[str]:
    question_tokens = _tokens(question_text)
    answer_tokens = _tokens(answer_text)
    answer_values = _values(answer_text)
    answer_word_tokens = {token for token in answer_tokens if not token.isdigit()}
    strong_question_tokens = question_tokens - _WEAK_REPAIR_TOKENS
    scored: list[tuple[int, int, str]] = []
    ordinal = 0
    for packet in packets:
        cited_bonus = 3 if packet.packet_id in cited_packet_ids else 0
        for line in _packet_lines(packet):
            line_tokens = _tokens(line)
            has_checkbox = checkbox_mode and bool(_CHECKBOX_RE.search(line))
            has_strong_cue = (
                bool(strong_question_tokens & line_tokens) or not strong_question_tokens
            )
            has_answer_cue = bool(answer_word_tokens & line_tokens) or bool(
                answer_values & _values(line)
            )
            if not (has_strong_cue or has_answer_cue or has_checkbox):
                continue
            score = _line_overlap_score(line, question_tokens, answer_tokens) + cited_bonus
            if checkbox_mode and _CHECKBOX_RE.search(line):
                score += 6
            if _VALUE_RE.search(line):
                score += 1
            if score <= 0:
                continue
            scored.append(
                (score, ordinal, f"[{packet.packet_id}] {_truncate(line, _MAX_LINE_CHARS)}")
            )
            ordinal += 1
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [line for _score, _ordinal, line in scored[:_MAX_LINES]]


def _chart_binding_lines(
    packets: Iterable[EvidencePacket],
    *,
    question_text: str,
    cited_packet_ids: set[str],
) -> list[str]:
    question_tokens = _tokens(question_text)
    scored: list[tuple[int, int, str]] = []
    ordinal = 0
    for packet in packets:
        cited_bonus = 3 if packet.packet_id in cited_packet_ids else 0
        if packet.chart_csv:
            line = _truncate(packet.chart_csv.replace("\n", " | "), _MAX_CHART_CSV_CHARS)
            scored.append((10 + cited_bonus, ordinal, f"[{packet.packet_id}] chart_csv={line}"))
            ordinal += 1
        for line in _packet_lines(packet):
            score = cited_bonus + _line_overlap_score(line, question_tokens, set())
            if _CHART_LINE_RE.search(line):
                score += 5
            if score <= 0:
                continue
            scored.append(
                (score, ordinal, f"[{packet.packet_id}] {_truncate(line, _MAX_LINE_CHARS)}")
            )
            ordinal += 1
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [line for _score, _ordinal, line in scored[:_MAX_LINES]]


def _packet_lines(packet: EvidencePacket) -> list[str]:
    text_parts = [packet.text_layer_snippet or "", packet.ocr_snippet or ""]
    lines: list[str] = []
    for text in text_parts:
        for raw_line in str(text or "").splitlines():
            line = " ".join(raw_line.strip().split())
            if line:
                lines.append(line)
    if not lines and packet.chart_csv:
        lines.append(packet.chart_csv.replace("\n", " | "))
    return _dedupe(lines)


def _line_overlap_score(line: str, question_tokens: set[str], answer_tokens: set[str]) -> int:
    line_tokens = _tokens(line)
    if not line_tokens:
        return 0
    score = min(8, len(question_tokens & line_tokens) * 2)
    score += min(4, len(answer_tokens & line_tokens) * 2)
    return score


def _tokens(text: str | None) -> set[str]:
    return {
        token
        for token in _WORD_RE.findall(str(text or "").lower())
        if len(token) > 1 and token not in _STOPWORDS
    }


def _values(text: str | None) -> set[str]:
    return {
        match.group(0).lower().strip("$()").replace(",", "")
        for match in _VALUE_RE.finditer(str(text or ""))
        if match.group(0)
    }


def _truncate(text: str, max_chars: int) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 3] + "..."


def _dedupe(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out
