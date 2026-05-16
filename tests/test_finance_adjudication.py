from focusparse.evidence.packet import EvidencePacket, PacketProvenance
from focusparse.pipeline.finance_adjudication import (
    finance_answers_match,
    infer_finance_answer_from_evidence,
)


def _packet(packet_id: str, text: str) -> EvidencePacket:
    return EvidencePacket(
        packet_id=packet_id,
        page=1,
        bbox_norm=(0.0, 0.0, 1.0, 1.0),
        region_type="Table",
        page_thumbnail_ref=f"/tmp/{packet_id}.png",
        local_crop_ref=f"/tmp/{packet_id}.png",
        ocr_snippet=text,
        provenance=PacketProvenance(tool="test", args_hash=""),
    )


def test_infers_corresponding_finance_value_status_from_structured_rows() -> None:
    question = (
        "For the year in which 'Products' net sales reached their minimum among "
        "the three years shown, what was the corresponding 'Gross margin' value, "
        "and is this value also the minimum, typical, or maximum among the three "
        "years' gross margins?"
    )
    packet = _packet(
        "pkt_000",
        "Gemini structured extraction: kind=table\n"
        "headers: Years ended | September 27, 2025 | September 28, 2024 | "
        "September 30, 2023\n"
        "candidate_rows: Products | $ 307,003 | $ 294,866 | $ 298,085 | "
        "Gross margin | 195,201 | 180,683 | 169,148\n"
        "confidence=0.95",
    )

    adjudication = infer_finance_answer_from_evidence(
        question,
        [packet],
        answer_type="exact_match",
    )

    assert adjudication is not None
    assert adjudication.answer == "180,683; typical"
    assert finance_answers_match("180,683; typical", adjudication)
    assert not finance_answers_match("169,148; minimum", adjudication)


def test_infers_repurchase_dividend_ratio_from_two_regions() -> None:
    question = (
        "For the fiscal year 2025, calculate the ratio of total cash spent on "
        "share repurchases to the total dividends paid. Use the 'Total Amount' "
        "of share repurchases from one region and the 'Total Amount' of "
        "dividends paid from another region. Express your answer as a decimal "
        "rounded to two decimal places."
    )
    repurchases = _packet(
        "pkt_001",
        "Share repurchases (In millions) Year Ended June 30, First Quarter "
        "Second Quarter Third Quarter Fourth Quarter Total Shares Amount 2025 "
        "7 $ 2,800 8 3,500 8 3,500 8 3,200 31 $ 13,000 Shares Amount 2024 "
        "11 $ 3,560 7 2,800 7 2,800 7 2,800 32 $ 11,960",
    )
    dividends = _packet(
        "pkt_002",
        "Dividend Per Share Amount Fiscal Year 2025 September 16, 2024 "
        "December 3, 2024 March 11, 2025 June 10, 2025 Total Fiscal Year "
        "2024 September 19, 2023 November 28, 2023 March 12, 2024 June 12, "
        "2024 Total $ 0.83 0.83 0.83 0.83 3.32 0.75 0.75 0.75 0.75 3.00 "
        "(In millions) 6,170 6,169 6,169 6,170 24,678 5,574 5,573 5,574 "
        "5,574 22,295",
    )

    adjudication = infer_finance_answer_from_evidence(
        question,
        [repurchases, dividends],
        answer_type="numeric",
    )

    assert adjudication is not None
    assert adjudication.answer == "0.53"
    assert finance_answers_match("0.53", adjudication)
    assert not finance_answers_match("0.51", adjudication)
