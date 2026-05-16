"""Deterministic finance-table adjudication from existing evidence packets.

These helpers are deliberately narrow. They do not look at gold answers or
example ids; they only confirm a current answer when the same evidence packets
already contain enough table structure to reconstruct it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from focusparse.evidence.packet import EvidencePacket


@dataclass(frozen=True)
class FinanceAdjudication:
    answer: str
    mechanism: str
    packet_ids: tuple[str, ...]
    rationale: str


def infer_finance_answer_from_evidence(
    question: str | None,
    packets: list[EvidencePacket],
    *,
    answer_type: str | None,
) -> FinanceAdjudication | None:
    """Return a compact finance answer reconstructed from packet text."""

    q = " ".join(str(question or "").split())
    q_lower = q.lower()
    answer_stem = str(answer_type or "").split(".")[-1].lower()

    if answer_stem == "exact_match" and _looks_corresponding_value_status_question(q_lower):
        candidate = _infer_corresponding_value_status(q, packets)
        if candidate:
            return candidate

    if answer_stem == "numeric" and _looks_repurchase_dividend_ratio_question(q_lower):
        candidate = _infer_repurchase_dividend_ratio(q_lower, packets)
        if candidate:
            return candidate

    if answer_stem == "numeric" and _looks_segment_purchase_price_percent_question(q_lower):
        candidate = _infer_segment_purchase_price_percent(packets)
        if candidate:
            return candidate

    return None


def finance_answers_match(answer: str | None, adjudication: FinanceAdjudication) -> bool:
    """True when the current answer already matches the deterministic candidate."""

    current = _normalize_answer_text(answer)
    expected = _normalize_answer_text(adjudication.answer)
    if not current or not expected:
        return False
    if _looks_decimal(expected) and _looks_decimal(current):
        return abs(float(current) - float(expected)) <= 0.005
    return current == expected


def _looks_corresponding_value_status_question(question: str) -> bool:
    return (
        "corresponding" in question
        and bool(re.search(r"\b(?:minimum|maximum|lowest|highest|min|max)\b", question))
        and bool(re.search(r"\b(?:typical|minimum|maximum|min|max)\b", question))
    )


def _looks_repurchase_dividend_ratio_question(question: str) -> bool:
    return (
        "ratio" in question
        and "repurchase" in question
        and "dividend" in question
        and "fiscal year" in question
    )


def _looks_segment_purchase_price_percent_question(question: str) -> bool:
    return (
        "purchase price" in question
        and "segment" in question
        and "acquisition" in question
        and bool(re.search(r"\b(?:percent|percentage)\b", question))
    )


def _infer_corresponding_value_status(
    question: str,
    packets: list[EvidencePacket],
) -> FinanceAdjudication | None:
    quoted = re.findall(r"'([^']+)'|\"([^\"]+)\"", question)
    labels = [a or b for a, b in quoted if (a or b)]
    if len(labels) < 2:
        return None

    source_label = labels[0]
    target_label = labels[1]
    want_min, want_max = _source_selection_min_max(question, source_label)
    if not (want_min or want_max):
        return None

    for packet in packets:
        rows = _structured_candidate_rows(_packet_text(packet))
        if not rows:
            continue
        source_row = _find_row(rows, source_label)
        target_row = _find_row(rows, target_label)
        if not source_row or not target_row:
            continue
        source_values = [_amount_to_float(v) for v in source_row[1]]
        target_values = [_amount_to_float(v) for v in target_row[1]]
        if (
            not source_values
            or not target_values
            or len(source_values) != len(target_values)
            or any(v is None for v in source_values)
            or any(v is None for v in target_values)
        ):
            continue

        numeric_source = [float(v) for v in source_values if v is not None]
        numeric_target = [float(v) for v in target_values if v is not None]
        idx = numeric_source.index(max(numeric_source) if want_max else min(numeric_source))
        value = target_row[1][idx]
        status = _value_status(numeric_target[idx], numeric_target)
        return FinanceAdjudication(
            answer=f"{_clean_amount(value)}; {status}",
            mechanism="corresponding_value_status",
            packet_ids=(packet.packet_id,),
            rationale=(
                f"Bound source row '{source_row[0]}' to target row '{target_row[0]}' "
                f"at column offset {idx}."
            ),
        )

    return None


def _source_selection_min_max(question: str, source_label: str) -> tuple[bool, bool]:
    normalized = question.lower()
    source = source_label.lower()
    start = normalized.find(source)
    if start < 0:
        start = 0
    end = len(normalized)
    for marker in ("what was the corresponding", "what is the corresponding", "corresponding"):
        marker_idx = normalized.find(marker, start)
        if marker_idx >= 0:
            end = min(end, marker_idx)
    window = normalized[start:end]
    want_min = bool(re.search(r"\b(?:minimum|lowest|min)\b", window, re.IGNORECASE))
    want_max = bool(re.search(r"\b(?:maximum|highest|max)\b", window, re.IGNORECASE))
    return want_min, want_max


def _infer_repurchase_dividend_ratio(
    question: str,
    packets: list[EvidencePacket],
) -> FinanceAdjudication | None:
    year_match = re.search(r"\bfiscal\s+year\s+(20\d{2})\b", question)
    if not year_match:
        return None
    year = year_match.group(1)

    repurchase: tuple[float, str, str] | None = None
    dividend: tuple[float, str, str] | None = None
    for packet in packets:
        text = _packet_text(packet)
        lowered = text.lower()
        if repurchase is None and "repurchase" in lowered:
            raw = _extract_repurchase_total(text, year)
            if raw:
                repurchase = (_amount_to_float(raw) or 0.0, raw, packet.packet_id)
        if dividend is None and "dividend" in lowered:
            raw = _extract_dividend_total(text, year)
            if raw:
                dividend = (_amount_to_float(raw) or 0.0, raw, packet.packet_id)

    if not repurchase or not dividend or repurchase[0] <= 0 or dividend[0] <= 0:
        return None

    ratio = repurchase[0] / dividend[0]
    return FinanceAdjudication(
        answer=f"{ratio:.2f}",
        mechanism="repurchase_dividend_ratio",
        packet_ids=(repurchase[2], dividend[2]),
        rationale=(
            f"Computed {year} repurchases {repurchase[1]} divided by dividends {dividend[1]}."
        ),
    )


def _infer_segment_purchase_price_percent(
    packets: list[EvidencePacket],
) -> FinanceAdjudication | None:
    segment_acquisition: tuple[float, str, str, str] | None = None
    purchase_price: tuple[float, str, str] | None = None

    for packet in packets:
        text = _packet_text(packet)
        if purchase_price is None:
            raw_price = _extract_total_purchase_price(text)
            if raw_price:
                purchase_price = (_amount_to_float(raw_price) or 0.0, raw_price, packet.packet_id)

        raw_segment = _extract_largest_segment_acquisition(text)
        if raw_segment and (segment_acquisition is None or raw_segment[0] > segment_acquisition[0]):
            segment_acquisition = (*raw_segment, packet.packet_id)

    if not segment_acquisition or not purchase_price:
        return None
    numerator, segment_label, raw_numerator, numerator_packet = segment_acquisition
    denominator, raw_denominator, denominator_packet = purchase_price
    if numerator <= 0 or denominator <= 0 or numerator >= denominator:
        return None

    percent = round((numerator / denominator) * 100)
    if percent <= 0 or percent >= 100:
        return None

    return FinanceAdjudication(
        answer=f"{percent}%",
        mechanism="segment_purchase_price_percent",
        packet_ids=tuple(dict.fromkeys((numerator_packet, denominator_packet))),
        rationale=(
            f"Computed segment acquisition impact for '{segment_label}' "
            f"({raw_numerator}) divided by total purchase price {raw_denominator}."
        ),
    )


def _structured_candidate_rows(text: str) -> list[tuple[str, list[str]]]:
    headers = _structured_headers(text)
    rows_match = re.search(r"^candidate_rows:\s*(.+)$", text, re.IGNORECASE | re.MULTILINE)
    if not headers or not rows_match:
        return []

    value_count = max(1, len(headers) - 1)
    tokens = [part.strip() for part in rows_match.group(1).split("|") if part.strip()]
    rows: list[tuple[str, list[str]]] = []
    i = 0
    while i < len(tokens):
        label = tokens[i]
        if _amount_to_float(label) is not None:
            i += 1
            continue
        if label.endswith(":") and i + 1 < len(tokens) and _amount_to_float(tokens[i + 1]) is None:
            i += 1
            continue
        values = tokens[i + 1 : i + 1 + value_count]
        if len(values) == value_count and any(_amount_to_float(v) is not None for v in values):
            rows.append((label, values))
            i += 1 + value_count
        else:
            i += 1
    return rows


def _structured_headers(text: str) -> list[str]:
    headers_match = re.search(r"^headers:\s*(.+)$", text, re.IGNORECASE | re.MULTILINE)
    if not headers_match:
        return []
    return [part.strip() for part in headers_match.group(1).split("|") if part.strip()]


def _find_row(rows: list[tuple[str, list[str]]], label: str) -> tuple[str, list[str]] | None:
    label_norm = _normalize_label(label)
    for row in rows:
        row_norm = _normalize_label(row[0])
        if row_norm and (row_norm in label_norm or label_norm in row_norm):
            return row
    return None


def _normalize_label(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(text or "").lower()))


def _extract_repurchase_total(text: str, year: str) -> str | None:
    year_block = _slice_between_years(text, year, ("2026", "2025", "2024", "2023", "2022"))
    if not year_block:
        return None
    amounts = _money_amounts(year_block)
    return amounts[-1] if amounts else None


def _extract_dividend_total(text: str, year: str) -> str | None:
    match = re.search(rf"\bFiscal\s+Year\s+{re.escape(year)}\b", text, re.IGNORECASE)
    if not match:
        return None

    body = text[match.end() : match.end() + 1000]
    millions_idx = body.lower().find("(in millions)")
    if millions_idx >= 0:
        amounts = [
            amount for amount in _money_amounts(body[millions_idx:]) if _amount_to_float(amount)
        ]
        # Quarterly dividend tables often OCR as four quarter amounts followed
        # by the fiscal-year total, then the next year's four quarters + total.
        if len(amounts) >= 5:
            return amounts[4]

    next_year_match = re.search(r"\bFiscal\s+Year\s+20\d{2}\b", body, re.IGNORECASE)
    scoped_body = body[: next_year_match.start()] if next_year_match else body
    amounts = [amount for amount in _money_amounts(scoped_body) if _amount_to_float(amount)]
    return amounts[-1] if amounts else None


def _extract_total_purchase_price(text: str) -> str | None:
    rows = _structured_candidate_rows(text)
    for label, row_values in rows:
        label_norm = _normalize_label(label)
        if "purchase price" not in label_norm:
            continue
        values = [value for value in row_values if _amount_to_float(value)]
        if values:
            return values[-1]

    match = re.search(
        r"\btotal\s+purchase\s+price\b[^$\d]{0,60}(?P<amount>\$?\s*\d{1,3}(?:,\d{3})+)",
        text,
        re.IGNORECASE,
    )
    return match.group("amount") if match else None


def _extract_largest_segment_acquisition(text: str) -> tuple[float, str, str] | None:
    headers = _structured_headers(text)
    rows = _structured_candidate_rows(text)
    if not headers or not rows:
        return None

    acquisition_indices = [
        idx for idx, header in enumerate(headers[1:]) if "acquisition" in header.lower()
    ]
    if not acquisition_indices:
        return None

    best: tuple[float, str, str] | None = None
    for label, values in rows:
        if _normalize_label(label) in {"total", "totals"}:
            continue
        for idx in acquisition_indices:
            if idx >= len(values):
                continue
            raw = values[idx]
            amount = _amount_to_float(raw)
            if amount is None or amount <= 0:
                continue
            if best is None or amount > best[0]:
                best = (amount, label, raw)
    return best


def _slice_between_years(text: str, year: str, known_years: tuple[str, ...]) -> str | None:
    match = re.search(rf"\b{re.escape(year)}\b", text)
    if not match:
        return None
    end = len(text)
    for other in known_years:
        if other == year:
            continue
        other_match = re.search(rf"\b{re.escape(other)}\b", text[match.end() :])
        if other_match:
            end = min(end, match.end() + other_match.start())
    return text[match.end() : end]


def _packet_text(packet: EvidencePacket) -> str:
    parts = [packet.ocr_snippet or "", packet.text_layer_snippet or "", packet.chart_csv or ""]
    return "\n".join(part for part in parts if part)


def _money_amounts(text: str) -> list[str]:
    return [
        match.group(0).strip() for match in re.finditer(r"\$?\s*\d{1,3}(?:,\d{3})+(?:\.\d+)?", text)
    ]


def _amount_to_float(text: str) -> float | None:
    cleaned = _clean_amount(text)
    if not re.fullmatch(r"-?\d+(?:,\d{3})*(?:\.\d+)?", cleaned):
        return None
    try:
        return float(cleaned.replace(",", ""))
    except ValueError:
        return None


def _clean_amount(text: str) -> str:
    value = str(text or "").strip().rstrip(",;.")
    value = re.sub(r"^\$\s*", "", value)
    return re.sub(r"\s+", " ", value)


def _value_status(value: float, values: list[float]) -> str:
    if value == min(values):
        return "minimum"
    if value == max(values):
        return "maximum"
    return "typical"


def _normalize_answer_text(text: str | None) -> str:
    value = " ".join(str(text or "").strip().split()).lower()
    value = re.sub(r"^\$\s*", "", value)
    value = value.replace(" / ", "; ")
    value = re.sub(r"\s*,\s*(typical|minimum|maximum)$", r"; \1", value)
    return value.strip(" ,.;")


def _looks_decimal(text: str) -> bool:
    return bool(re.fullmatch(r"-?\d+(?:\.\d+)?", text.strip()))
