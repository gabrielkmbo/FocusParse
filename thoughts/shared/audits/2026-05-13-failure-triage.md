# Failure-mode triage — main-stack n=148 baseline

Source: `results/hf/sprint-2026-05-13/main-stack-run1/focusparse_focus_agentic_multi_page_333fe987/per_example.jsonl` (49.3%, 73/148).

Generated for the harness-60plus-iteration sprint Phase 1 (Task #3 in TaskList).


## Bucket summary

| Bucket | Total | Datasheet | Finance |
|--------|-------|-----------|---------|
| wrong_extraction_other | 45 | 30 | 15 |
| wrong_page | 13 | 7 | 6 |
| bad_layout | 9 | 5 | 4 |
| lazy_abstain | 4 | 2 | 2 |
| wrong_extraction_normalizable | 4 | 2 | 2 |


## Question-family distribution on wrong_extraction_other (the whale, 45 rows)


### datasheet
| family | count |
|--------|-------|
| distant_evidence_fusion | 12 |
| timing_diagram_reading | 4 |
| multi_chart_comparison | 3 |
| min_typ_max_disambiguation | 3 |
| chart_table_cross_ref | 2 |
| near_miss_distractor | 2 |
| schematic_value_lookup | 1 |
| None | 1 |
| spec_table_cell_retrieval | 1 |
| axis_value_interpolation | 1 |

### finance
| family | count |
|--------|-------|
| spec_table_cell_retrieval | 3 |
| multi_chart_comparison | 3 |
| distant_evidence_fusion | 1 |
| chart_table_cross_ref | 1 |
| chart_footnote_fusion | 1 |
| dual_axis_disambiguation | 1 |
| package_mechanical_reading | 1 |
| figure_caption_cross_ref | 1 |
| chart_caption_fusion | 1 |
| direct_label_reading | 1 |
| curve_axis_reading | 1 |

## Bucket definitions

- `wrong_page`: page_recall == 0 — router pointed somewhere else entirely.
- `bad_layout`: page_recall > 0 but bbox_iou < 0.3 — wrong region on the right page.
- `lazy_abstain`: pred is empty / 'Unanswerable' while gold is non-null.
- `wrong_extraction_normalizable`: pred is a substring of gold or vice versa (prompt/format fixable).
- `wrong_extraction_other`: right page + right region + acceptable IoU, but wrong value.

## Reading the per-example table

Columns: `bucket | example_id | domain | PR | IoU | family | chart_csv | tools | pred | gold | verdict`. 
`verdict` is filled by the golden-audit pass (Phase 2 / Task #4) with one of 
`harness_error / unanswerable / golden_incorrect / ambiguous`.


## Per-example detail

| bucket | example_id | dom | PR | IoU | family | csv | tools | pred | gold | verdict |
|--------|-----------|-----|----|----|--------|-----|-------|------|------|---------|
| bad_layout | dat-DS5091D-00-0002 | dat | 1.00 | 0.00 | axis_value_interpola | 1 | expan,inspe | 0 percentage points | Approximately 3% | TBD |
| bad_layout | dat-TTP223B-data-sheet-0058 | dat | 1.00 | 0.00 | pin_diagram_label | 0 | expan,inspe | 1 Q | Pin 1 (Q) is directly opposite to pin 6 (TOG). | TBD |
| bad_layout | dat-infineon-designing-with-power-mosfets-applicationnotes-en-0041 | dat | 1.00 | 0.00 | confusable_label | 0 | expan,inspe | When Q1 switches off, the inductor current is commutated thr... | The inductor current (I_L) increases when Q1 is ON and Q2 is... | TBD |
| bad_layout | dat-opa454-0018 | dat | 1.00 | 0.11 | axis_value_interpola | 2 | expan,react | -60 mV | -400 | TBD |
| bad_layout | dat-slvaer0b-0011 | dat | 0.33 | 0.00 | distant_evidence_fus | 0 | expan,inspe | loop 2. At the meantime, the area of the switching node SW1 ... | Loop #2; the recommended layout for this area is to place th... | TBD |
| lazy_abstain | dat-nRF24L01P_PS_v1.0.annot-0011 | dat | 1.00 | 1.00 | spec_table_cell_retr | 0 | expan,inspe | Unanswerable | VDD - 0.6 | TBD |
| lazy_abstain | dat-spruhm8k-0025 | dat | 1.00 | 1.00 | spec_table_cell_retr | 0 | expan,inspe | Unanswerable | 0x3FFFF8 | TBD |
| wrong_extraction_normalizable | dat-armv6-interrupts.annot-0024 | dat | 0.50 | 1.00 | distant_evidence_fus | 0 | expan,inspe | FIQ | FIQ exception has a higher priority than IRQ exception. | TBD |
| wrong_extraction_normalizable | dat-spruhm8k-0063 | dat | 1.00 | 1.00 | confusable_label | 0 | expan,inspe | 25.2.1 EMIF Clock Control...................................... | 2806 | TBD |
| wrong_extraction_other | dat-AN040_EN-0008 | dat | 1.00 | 1.00 | schematic_value_look | 0 | expan,inspe | Iwireless | I_wireless; The diagram shows Q1 (the adapter path) as OFF a... | TBD |
| wrong_extraction_other | dat-Arm_EE382N_4-0025 | dat | 1.00 | 1.00 | multi_chart_comparis | 0 | expan,inspe | Arithmetic Shift Right Sign bit shifted in | Arithmetic Shift Right shifts in the sign bit, as indicated ... | TBD |
| wrong_extraction_other | dat-Arm_EE382N_4-0028 | dat | 1.00 | 1.00 | multi_chart_comparis | 0 | expan,inspe | EXECUTE MEMORY WRITE | MEMORY; it occurs after EXECUTE and before WRITE. | TBD |
| wrong_extraction_other | dat-Arm_EE382N_4-0049 | dat | 1.00 | 1.00 | distant_evidence_fus | 0 | expan,inspe | BLE ; Signed integer comparison gave less than or equal | BLE; Signed integer comparison gave less than or equal | TBD |
| wrong_extraction_other | dat-BCM2835-ARM-timer-int.annot-0029 | dat | 1.00 | 1.00 | chart_table_cross_re | 0 | expan,inspe | The base address for the ARM timer register is 0x7E00B000. T... | The timer's 'Raw IRQ' register is mapped in a separate addre... | TBD |
| wrong_extraction_other | dat-BCM2835-ARM-timer-int.annot-0047 | dat | 0.67 | 1.00 | distant_evidence_fus | 0 | expan,inspe | The base address for the ARM interrupt register is 0x7E00B00... | 0x2000B218 | TBD |
| wrong_extraction_other | dat-DC_DC Converter Testing with Fast Load Transient _ Richtek Technology-0055 | dat | 1.00 | 1.00 | ? | 0 | expan,inspe | φm = 49° | φm ≈ 36° | TBD |
| wrong_extraction_other | dat-DS5091D-00-0011 | dat | 1.00 | 1.00 | spec_table_cell_retr | 0 | expan,inspe | Return the manufacturer ID number : 0x00h | 0x00h; the description explicitly states this as the returne... | TBD |
| wrong_extraction_other | dat-DS5091D-00-0013 | dat | 1.00 | 1.00 | timing_diagram_readi | 2 | expan,inspe | 400 μs | Approximately 500 μs | TBD |
| wrong_extraction_other | dat-DS8237AB-06-0017 | dat | 1.00 | 1.00 | min_typ_max_disambig | 0 | expan,inspe | 0.697 0.704 0.711 | min: 0.697 V, typ: 0.704 V, max: 0.711 V | TBD |
| wrong_extraction_other | dat-SG017_2022-0054 | dat | 1.00 | 1.00 | min_typ_max_disambig | 0 | expan,inspe | RT9187C SOT-23-5 | RTQ2510-QA, VDFN3x3-8 | TBD |
| wrong_extraction_other | dat-adrv9040-reference-manual-ug-2192-0032 | dat | 1.00 | 1.00 | distant_evidence_fus | 0 | expan,inspe | ADRV9040_FW.bin 641 kb | ADRV9040_FW.bin, 641 kb | TBD |
| wrong_extraction_other | dat-adrv9040-reference-manual-ug-2192-0041 | dat | 0.50 | 1.00 | multi_chart_comparis | 1 | expan,inspe | The DPD algorithm updates coefficients only when the RMS pow... | DPD_MODE1; this is visually indicated in the chart for DPD_M... | TBD |
| wrong_extraction_other | dat-adrv9040-reference-manual-ug-2192-0046 | dat | 1.00 | 1.00 | distant_evidence_fus | 0 | expan,inspe | adi_adrv904x_OrxAttenSet() Sets the desired attenuation in u... | adi_adrv904x_OrxAttenSet(), dB | TBD |
| wrong_extraction_other | dat-adrv9040-reference-manual-ug-2192-0052 | dat | 1.00 | 1.00 | near_miss_distractor | 0 | expan,inspe | LOGGING, 6 | LOGGING and MULTI-THREADING are tied at 7 functions each | TBD |
| wrong_extraction_other | dat-ads1299-0044 | dat | 1.00 | 1.00 | distant_evidence_fus | 0 | expan,inspe | b) Differential Input | Fully-differential input mode; this is shown in the circuit ... | TBD |
| wrong_extraction_other | dat-ads1299-0057 | dat | 1.00 | 1.00 | timing_diagram_readi | 0 | expan,inspe | 32 t_CLK | 16 | TBD |
| wrong_extraction_other | dat-aducm350_ug-587-0043 | dat | 1.00 | 1.00 | timing_diagram_readi | 0 | expan,inspe | 8 µs | 4 µs | TBD |
| wrong_extraction_other | dat-arm1176-ch13-debug-0012 | dat | 1.00 | 1.00 | distant_evidence_fus | 0 | expan,inspe | b11 = Either. | b11 (Either), because when context ID comparison and linking... | TBD |
| wrong_extraction_other | dat-arm1176-ch13-debug-0019 | dat | 1.00 | 1.00 | distant_evidence_fus | 0 | expan,inspe | DSMCR; b000 b1011 | DSMCR, Opcode_2: b000, CRm: b1011 | TBD |
| wrong_extraction_other | dat-arm1176-ch3-coproc.annot-0004 | dat | 1.00 | 1.00 | distant_evidence_fus | 0 | expan,inspe | Holds the base address. The reset value is 0. | 0 (reset value) | TBD |
| wrong_extraction_other | dat-arm1176-ch3-coproc.annot-0017 | dat | 1.00 | 1.00 | chart_table_cross_re | 0 | expan,inspe | [31:24]=0x41, [23:20]=0x0, [19:16]=0xF, [15:4]=0xB76, [3:0]=... | 0x410FB760; [19:16] Architecture | TBD |
| wrong_extraction_other | dat-arm1176-vm.annot-0022 | dat | 1.00 | 1.00 | distant_evidence_fus | 0 | expan,inspe | Outer Write-Through. Non-Shared Normal, Write-Back Cacheable | Non-Shared Normal, Write-Through Cacheable | TBD |
| wrong_extraction_other | dat-armv6.b3-coprocessor.annot-0002 | dat | 1.00 | 1.00 | distant_evidence_fus | 0 | expan,inspe | Cache type register Cache type register on page B3-10 / 0b01... | Cache type register and Tightly Coupled Memory (TCM) type re... | TBD |
| wrong_extraction_other | dat-armv6.b3-coprocessor.annot-0011 | dat | 1.00 | 1.00 | min_typ_max_disambig | 0 | expan,inspe | Use the TLB type register layout to identify ILsize as the i... | unanswerable | TBD |
| wrong_extraction_other | dat-infineon-applicationnote-linear-mode-operation-safe-operation-diagram-mosfets-applicationnotes-en-0006 | dat | 1.00 | 1.00 | axis_value_interpola | 1 | expan,inspe | 480 A | Approximately 520 A | TBD |
| wrong_extraction_other | dat-infineon-applicationnote-linear-mode-operation-safe-operation-diagram-mosfets-applicationnotes-en-0022 | dat | 1.00 | 1.00 | near_miss_distractor | 0 | expan,react | Vgs=2.9 V | Vgs = 2.9 V | TBD |
| wrong_extraction_other | dat-infineon-power-mosfet-avalanche-design-guidelines-applicationnotes-en-0047 | dat | 0.50 | 1.00 | distant_evidence_fus | 0 | expan,inspe | constant junction temperature energy values | 315 mJ | TBD |
| wrong_extraction_other | dat-spruhm8k-0009 | dat | 1.00 | 1.00 | timing_diagram_readi | 0 | expan,inspe | CEVT1 and CAP1 | CEVT4; CAP4 captures the new timestamp (t4, t8) at that even... | TBD |
| wrong_extraction_other | dat-spruhm8k-0019 | dat | 1.00 | 1.00 | distant_evidence_fus | 0 | expan,inspe | ADC_readPPBResult; ADC_setINLTrim; ADC_readResult | ADC_setINLTrim, ADC_readResult, ADC_readPPBResult | TBD |
| wrong_page | dat-AN040_EN-0010 | dat | 0.00 | 0.00 | ? | 0 | — |  | You should use IOUT (along with the voltage at OUT) to deter... | TBD |
| wrong_page | dat-Buck Converter Selection Criteria _ Richtek Technology-0030 | dat | 0.00 | 0.00 | ? | 0 | expan,inspe | Unanswerable | Yes, the photographed component matches the UQFN-14L 2x3 (FC... | TBD |
| wrong_page | dat-SG017_2022-0053 | dat | 0.00 | 0.00 | confusable_label | 0 | expan,inspe | Unanswerable | RTQ2532W or RTQ2532N (both list this feature set), Iout max ... | TBD |
| wrong_page | dat-aducm350_ug-587-0032 | dat | 0.00 | 0.00 | spec_table_cell_retr | 0 | expan,inspe | Unanswerable | b0010 | TBD |
| wrong_page | dat-arm1176-ch3-coproc.annot-0052 | dat | 0.00 | 0.00 | ? | 0 | — |  | Cache Operations Register | TBD |
| wrong_page | dat-infineon-applicationnote-linear-mode-operation-safe-operation-diagram-mosfets-applicationnotes-en-0019 | dat | 0.00 | 0.00 | ? | 0 | — |  | Vgs = 2.9 V | TBD |
| wrong_page | dat-infineon-applicationnote-mosfet-fast-switching-motivation--implementation-and-precautions-applicationnotes-en-0009 | dat | 0.00 | 0.00 | ? | 0 | — |  | The largest components labeled 'Infineon' are most likely th... | TBD |
| bad_layout | fin-10-K-0008 | fin | 1.00 | 0.00 | table_note_fusion | 0 | expan,inspe | (1)ppt | 0% | TBD |
| bad_layout | fin-bis_qr_2025_mar-0061 | fin | 1.00 | 0.28 | multi_chart_comparis | 4 | expan,inspe | US | United States (US) experienced both a noticeable increase in... | TBD |
| bad_layout | fin-bis_qr_2025_mar-0062 | fin | 1.00 | 0.29 | confusable_label | 4 | expan,inspe | US; Europe | Europe experienced a larger increase in its ten-year term pr... | TBD |
| bad_layout | fin-boj_fsr_2024_oct-0008 | fin | 1.00 | 0.00 | axis_value_interpola | 8 | expan,inspe | 0.6% | -0.6 | TBD |
| lazy_abstain | fin-10-K-0041 | fin | 1.00 | 1.00 | spec_table_cell_retr | 0 | expan,inspe | Unanswerable | The percentage decrease in technology-based intangible asset... | TBD |
| lazy_abstain | fin-imf_weo_2024_oct-0003 | fin | 1.00 | 1.00 | spec_table_cell_retr | 0 | expan,inspe | Unanswerable | None - no topic in the visible portion of the table appears ... | TBD |
| wrong_extraction_normalizable | fin-bis_qr_2024_sep-0063 | fin | 1.00 | 1.00 | legend_series_bindin | 4 | expan,inspe | FR | France (FR) experienced the largest percentage increase in C... | TBD |
| wrong_extraction_normalizable | fin-boj_fsr_2024_apr-0010 | fin | 1.00 | 1.00 | legend_series_bindin | 3 | expan,inspe | Home prefecture | Home prefecture contributed more to the total y/y % change i... | TBD |
| wrong_extraction_other | fin-10-K-0010 | fin | 1.00 | 1.00 | spec_table_cell_retr | 0 | expan,inspe | $(40) million | -40 | TBD |
| wrong_extraction_other | fin-10-K-0013 | fin | 1.00 | 1.00 | spec_table_cell_retr | 0 | expan,inspe | Balance Sheets 52 | Balance Sheets, page 52 | TBD |
| wrong_extraction_other | fin-10-K-0036 | fin | 1.00 | 1.00 | distant_evidence_fus | 0 | expan,inspe | 82% | 68% | TBD |
| wrong_extraction_other | fin-aapl-20250927-0009 | fin | 1.00 | 1.00 | spec_table_cell_retr | 0 | expan,inspe | No; Japan had the highest percentage increase at 15 % with 2... | No, the region with the highest percentage increase (Japan, ... | TBD |
| wrong_extraction_other | fin-aapl-20250927-0034 | fin | 1.00 | 1.00 | chart_table_cross_re | 1 | expan,inspe | September 2022 $ 136 $ 115 | 2022, $21 | TBD |
| wrong_extraction_other | fin-bis_qr_2024_sep-0050 | fin | 1.00 | 1.00 | chart_footnote_fusio | 4 | expan,inspe | D. FX loans | FX bonds | TBD |
| wrong_extraction_other | fin-bis_qr_2025_mar-0050 | fin | 0.67 | 1.00 | multi_chart_comparis | 2 | expan,inspe | EE | Latvia | TBD |
| wrong_extraction_other | fin-boe_fsr_2024_nov-0056 | fin | 1.00 | 1.00 | multi_chart_comparis | 3 | expan,inspe | UK | Germany | TBD |
| wrong_extraction_other | fin-ecb_fsr_2024_may-0057 | fin | 1.00 | 1.00 | multi_chart_comparis | 1 | expan,inspe | loans to micro firms | Micro firms show a more noticeable uptick in NPL ratios at t... | TBD |
| wrong_extraction_other | fin-fed_fsr_2023_apr-0063 | fin | 1.00 | 1.00 | dual_axis_disambigua | 2 | expan,inspe | 30-year (left scale) | 10-year Treasury security showed the highest market depth in... | TBD |
| wrong_extraction_other | fin-goog-20251231-0045 | fin | 1.00 | 1.00 | package_mechanical_r | 0 | expan,inspe | Class A Common Stock, $0.001 par value GOOGL | Class A Common Stock, $0.001 par value (GOOGL) | TBD |
| wrong_extraction_other | fin-jpm_gtm_us_daily-0049 | fin | 1.00 | 1.00 | figure_caption_cross | 0 | expan,inspe | Stephanie Aliaga New York | Lucia Gutierrez Mellado, Madrid | TBD |
| wrong_extraction_other | fin-jpm_ltcma-0032 | fin | 1.00 | 1.00 | chart_caption_fusion | 2 | expan,inspe | Exhibit 4A: Contributors to 2026 LTCMA trend DM GDP growth f... | Developed markets (DM); the chart matches the caption 'Exhib... | TBD |
| wrong_extraction_other | fin-vis-jpm_gtm_us_daily-0109 | fin | 1.00 | 1.00 | direct_label_reading | 0 | expan,inspe | 4 | 3 times | TBD |
| wrong_extraction_other | fin-vis-jpm_gtm_us_daily-0114 | fin | 1.00 | 1.00 | curve_axis_reading | 1 | expan,inspe | Feb 2020 to Jun 2022 | Feb 2020 to Apr 2020 | TBD |
| wrong_page | fin-aapl-20250927-0021 | fin | 0.00 | 0.00 | package_mechanical_r | 0 | expan,inspe | Unanswerable | Fiscal year end date: September 27, 2025; Classification: La... | TBD |
| wrong_page | fin-bis_ar_2024-0062 | fin | 0.00 | 0.00 | ? | 0 | — |  | Net income contributed more positively than Transfers by 202... | TBD |
| wrong_page | fin-boe_fsr_2024_jun-0060 | fin | 0.00 | 0.00 | ? | 0 | — |  | The US 10-year government bond yield is currently closest to... | TBD |
| wrong_page | fin-fed_fsr_2023_apr-0052 | fin | 0.00 | 0.00 | curve_axis_reading | 4 | expan,inspe | 5 | On April 19, 2023, the 10-year OTR market depth (blue line, ... | TBD |
| wrong_page | fin-jpm_gtm_us_daily-0014 | fin | 0.00 | 0.00 | ? | 0 | — |  | France, 49.9 | TBD |
| wrong_page | fin-jpm_gtm_us_daily-0023 | fin | 0.00 | 0.00 | distant_evidence_fus | 1 | expan,inspe | Unanswerable | Small cap has the highest proportion of value stocks by mark... | TBD |