"""Gold-free answer contract tests."""

from focusparse.pipeline.answer_contract import (
    answer_contract_failures,
    answer_contract_risks,
    build_answer_contract,
)


def test_min_typ_max_question_rejects_single_scalar() -> None:
    contract = build_answer_contract(
        "For the FB Error Comparator Threshold parameter, which value "
        "(min, typ, or max) should be used, and what is the corresponding voltage?",
        answer_type="exact_match",
        domain="datasheet",
        question_family="spec_table_cell_retrieval",
    )

    assert contract.requires_min_typ_max
    assert "missing_field" in answer_contract_failures("0.697", contract)


def test_min_typ_max_label_and_value_passes_contract() -> None:
    contract = build_answer_contract(
        "Which value (min, typ, or max) should be used and what voltage?",
        answer_type="exact_match",
        domain="datasheet",
    )

    assert answer_contract_failures("min: 0.697 V", contract) == []


def test_numeric_scalar_contract_does_not_force_secondary_yes_no_field() -> None:
    contract = build_answer_contract(
        "If +600 V exceeds the CDM rating, what maximum input current must be "
        "ensured according to the footnote?",
        answer_type="numeric",
        domain="datasheet",
    )

    assert not contract.requires_multi_field
    assert answer_contract_failures("10 mA", contract) == []


def test_value_question_rejects_row_label_without_value() -> None:
    contract = build_answer_contract(
        "Which value should be used when comparing the single pulse avalanche "
        "energy rating of this MOSFET?",
        answer_type="exact_match",
        domain="datasheet",
    )

    assert "label_value_mismatch" in answer_contract_failures(
        "Single Pulse Avalanche Energy (Thermally Limited)",
        contract,
    )


def test_visual_cue_question_rejects_label_only_answer() -> None:
    contract = build_answer_contract(
        "Which Y-axis label should you use, and how does the diagram visually "
        "indicate wireless supply? Explain the visual cues.",
        answer_type="exact_match",
        domain="datasheet",
    )

    assert "missing_field" in answer_contract_failures("Iwireless", contract)
    assert (
        answer_contract_failures(
            "I_wireless; Q1 is OFF and VOUT = 5V is supplied through the wireless path",
            contract,
        )
        == []
    )


def test_visual_cue_question_rejects_prose_without_visible_cue() -> None:
    contract = build_answer_contract(
        "Which DPD mode results in fewer coefficient updates, and how is this "
        "visually indicated in the chart?",
        answer_type="exact_match",
        domain="datasheet",
        question_family="chart_caption_binding",
    )

    assert "missing_field" in answer_contract_failures(
        "DPD_MODE1, there is no update between Update 1 and Update 2 because "
        "the RMS power is below the max power recorded.",
        contract,
    )
    assert (
        answer_contract_failures(
            "DPD_MODE1; the chart shows NO M-TABLE UPDATE regions when RMS "
            "power is less than the max power.",
            contract,
        )
        == []
    )


def test_visual_cue_question_allows_structured_file_size_answer() -> None:
    contract = build_answer_contract(
        "Which firmware file must be loaded first, and what is the listed size "
        "of this firmware file? Explain how the chart and table support it.",
        answer_type="exact_match",
        domain="datasheet",
        question_family="chart_table_cross_ref",
    )

    assert answer_contract_failures("ADRV9040_FW.bin, 641 kb", contract) == []


def test_wrong_row_cues_are_detected_without_forcing_failure() -> None:
    contract = build_answer_contract(
        "Among the visually similar part number rows, which package has the lowest value?",
        answer_type="exact_match",
        domain="datasheet",
    )

    assert set(contract.row_disambiguation_cues) >= {
        "among",
        "visually_similar",
        "part_number",
        "lowest",
        "value",
    }
    assert "wrong_row_risk" in answer_contract_risks(contract)
    assert answer_contract_failures("RTQ2510-QA, VDFN3x3-8", contract) == []


def test_corresponding_row_binding_detects_two_step_min_question() -> None:
    contract = build_answer_contract(
        "For the year in which Products net sales reached their minimum among the "
        "three years shown, what was the corresponding Gross margin value, and is "
        "this value also the minimum, typical, or maximum among the three years?",
        answer_type="exact_match",
        domain="finance",
        question_family="min_typ_max_disambiguation",
    )

    assert contract.requires_corresponding_row_binding
    assert "corresponding" in contract.row_disambiguation_cues
    assert "wrong_row_risk" in answer_contract_risks(contract)
    assert answer_contract_failures("180,683; typical", contract) == []


def test_checkbox_binding_detected_without_boolean_failure() -> None:
    contract = build_answer_contract(
        "Based on the check marks in the table, does the registrant qualify as a "
        "large accelerated filer and has it filed all required reports?",
        answer_type="boolean",
        domain="finance",
    )

    assert contract.checkbox_binding_required
    assert "checkbox_binding_risk" in answer_contract_risks(contract)
    assert answer_contract_failures("yes", contract) == []


def test_chart_binding_detected_from_family_without_chart_extraction() -> None:
    contract = build_answer_contract(
        "Which country experienced the largest increase between markers a and c?",
        answer_type="exact_match",
        domain="finance",
        question_family="legend_series_binding",
    )

    assert contract.chart_binding_required
    assert "legend_binding_risk" in answer_contract_risks(contract)
    assert answer_contract_failures("France", contract) == []
