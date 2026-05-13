# Parser-Bench Golden QA Audit

Dataset: `gabrielbo/parser-bench`
Requested revision: `3774c67f8b814392b6d04c939e904f749a3f52eb`
Splits audited: `train, validation, test`
Rows loaded: `590`

## Result

### Publishability

| key | count |
| --- | ---: |
| publishable | 537 |
| fix_required | 53 |

### Splits

| key | count |
| --- | ---: |
| train | 96 |
| validation | 219 |
| test | 275 |

### Stress Types

| key | count |
| --- | ---: |
| none | 404 |
| downscale | 123 |
| spatial_separation | 63 |

The deterministic audit found `404` canonical rows and `186` stress rows. FocusParse's current `src/focusparse/eval/hf_loader.py` filters non-`none` stress rows before headline evals, so the canonical headline-eval surface is `404` rows when all public splits are loaded.

## Method

- Loaded row metadata through Hugging Face Dataset Viewer `/rows`, pinned with `revision` and checked against embedded cached-asset revisions.
- Checked schema, split mapping, answer type/tolerance consistency, page-image metadata, evidence bbox geometry, multi-region markers, duplicate ids/questions, and unanswerable consistency.
- Emitted review packets for visual adjudication. This automated pass can find structural and scorer-facing blockers; it does not independently remeasure every chart/image value by eye.

## Pipeline Implications

- `scripts/run_hf_eval.py` defaults to HF `validation`, which is parser-bench local `test`, not local `dev`.
- `src/focusparse/eval/hf_loader.py` filters stress rows, while the raw public dataset keeps them for stress analysis.
- `src/focusparse/eval/scoring.py` extracts the first numeric token for numeric answers and applies absolute tolerance when present; bad or missing tolerances directly affect headline accuracy.
- `src/focusparse/eval/harness.py` caches predictions by example id only, so any gold-question or gold-answer edits require a fresh output directory.

## Artifacts

- Row audit: `results/audits/parser-bench-golden-audit-2026-05-11/audit_rows.jsonl`
- Patch candidates: `results/audits/parser-bench-golden-audit-2026-05-11/patch_candidates.jsonl`
- Golden/scorer fix candidates: `results/audits/parser-bench-golden-audit-2026-05-11/golden_fix_candidates.jsonl`
- Review packets: `results/audits/parser-bench-golden-audit-2026-05-11/review_packets.jsonl`
- Summary: `results/audits/parser-bench-golden-audit-2026-05-11/summary.json`

## Issue Counts

### Issues

| key | count |
| --- | ---: |
| stress_variant | 186 |
| duplicate_question | 146 |
| bbox_without_image_dims | 42 |
| page_image_supporting_page_count_mismatch | 27 |
| duplicate_id | 20 |
| numeric_wording_with_non_numeric_type | 16 |
| non_numeric_tolerance | 8 |
| tolerance_mismatch | 5 |
| estimate_with_zero_tolerance | 4 |
| numeric_ratio_prose_answer | 3 |
| numeric_symbolic_expression_answer | 2 |
| numeric_multi_field_answer | 2 |
| numeric_prose_prefix_answer | 1 |
| numeric_formula_answer | 1 |
| numeric_range_answer | 1 |
| answer_unit_mismatch | 1 |
| numeric_missing_tolerance | 1 |
| numeric_hex_answer | 1 |

## Golden Answer / Scorer Fixes

`36` rows have high-confidence gold answer, answer_type, unit, or tolerance fixes. These are the rows most likely to make an otherwise correct model answer score incorrectly.

| id | split | status | issue codes | proposed answer/question fix |
| --- | --- | --- | --- | --- |
| dat-DS8204L-04-0020 | train | fix_required | tolerance_mismatch | Keep gold answer `Approximately 75 mV`, but set tolerance to `25`. |
| dat-TTP223B-data-sheet-0001 | train | fix_required | numeric_wording_with_non_numeric_type | Keep question and gold answer `0.10 ± 0.06`, but change answer_type to numeric with an explicit unit/tolerance, or rewrite the question to request exact text. |
| dat-DC_DC Converter Testing with Fast Load Transient _ Richtek Technology-0007 | train | fix_required | tolerance_mismatch | Keep gold answer `Approximately 45°`, but set tolerance to `10`. |
| dat-adrv9008-1-w-9008-2-w-9009-w-hardware-reference-manual-ug-1295-0018 | train | fix_required | numeric_prose_prefix_answer | Use scalar numeric gold `35`; keep label/context numbers in rationale. |
| dat-adrv9008-1-w-9008-2-w-9009-w-hardware-reference-manual-ug-1295-0032 | train | fix_required | numeric_wording_with_non_numeric_type | Keep question and gold answer `19:12`, but change answer_type to numeric with an explicit unit/tolerance, or rewrite the question to request exact text. |
| dat-opa454-0061 | train | fix_required | numeric_wording_with_non_numeric_type | Keep question and gold answer `±50 mA`, but change answer_type to numeric with an explicit unit/tolerance, or rewrite the question to request exact text. |
| fin-ecb_fsr_2024_nov-0056 | train | fix_required | numeric_formula_answer | Use scalar numeric gold `0.351` and move the equation/explanation to rationale. |
| fin-vis-ecb_fsr_2024_nov-0034 | train | fix_required | numeric_range_answer | Range gold `0.6 to 0.8` is not a single scalar. Split into lower/upper-bound questions, ask for a midpoint, or use exact/structured scoring. |
| fin-boj_fsr_2024_apr-0020 | train | fix_required | numeric_wording_with_non_numeric_type | Keep question and gold answer `Fiscal 2024; the footnote states 2024 values are estimates, and the chart shows...`, but change answer_type to numeric with an explicit unit/tolerance, or rewrite the question to request exact text. |
| fin-imf_weo_2024_oct-0031 | train | fix_required | numeric_wording_with_non_numeric_type | Keep question and gold answer `Knowledge and effect of policies; no, the difference is approximately 15-16 uni...`, but change answer_type to numeric with an explicit unit/tolerance, or rewrite the question to request exact text. |
| dat-Arm_EE382N_4-0014 | validation | fix_required | estimate_with_zero_tolerance | Keep gold answer `2`; set a non-zero absolute tolerance matching the question wording, or rewrite the question as an exact lookup. |
| dat-DS5091D-00-0013 | validation | fix_required | tolerance_mismatch | Keep gold answer `Approximately 500 μs`, but set tolerance to `25`. |
| fin-aapl-20250927-0034 | validation | fix_required | numeric_wording_with_non_numeric_type | Keep question and gold answer `2022, $21`, but change answer_type to numeric with an explicit unit/tolerance, or rewrite the question to request exact text. |
| dat-spruhm8k-0002 | validation | fix_required | estimate_with_zero_tolerance | Keep gold answer `3`; set a non-zero absolute tolerance matching the question wording, or rewrite the question as an exact lookup. |
| dat-DS5091D-00-0043_spatial | validation | fix_required | answer_unit_mismatch, duplicate_id, stress_variant, tolerance_mismatch | Keep gold answer `0.2`, but set answer_unit to `V` and tolerance to `0.05`. |
| fin-fed_fsr_2023_apr-0052 | validation | fix_required | numeric_ratio_prose_answer | Use scalar ratio gold `1`; keep dates/series values in rationale only. |
| dat-nRF24L01P_PS_v1.0.annot-0011 | validation | fix_required | duplicate_question, numeric_symbolic_expression_answer | Gold answer `VDD - 0.6` is symbolic, not scalar. Rewrite the question as symbolic/exact-match, or provide a concrete numeric value if the document defines the missing variable. |
| fin-bis_qr_2024_sep-0034_ds50 | validation | fix_required | numeric_wording_with_non_numeric_type, stress_variant | Keep question and gold answer `China (CN) and the United States (US), as indicated by the darkest red cell at...`, but change answer_type to numeric with an explicit unit/tolerance, or rewrite the question to request exact text. |
| fin-boj_fsr_2024_apr-0020_ds50 | validation | fix_required | duplicate_question, numeric_wording_with_non_numeric_type, stress_variant | Keep question and gold answer `Fiscal 2024; the footnote states 2024 values are estimates, and the chart shows...`, but change answer_type to numeric with an explicit unit/tolerance, or rewrite the question to request exact text. |
| fin-boj_fsr_2024_apr-0020_spatial | validation | fix_required | duplicate_question, numeric_wording_with_non_numeric_type, stress_variant | Keep question and gold answer `Fiscal 2024; the footnote states 2024 values are estimates, and the chart shows...`, but change answer_type to numeric with an explicit unit/tolerance, or rewrite the question to request exact text. |
| fin-ecb_fsr_2024_may-0041_ds50 | validation | fix_required | duplicate_question, numeric_wording_with_non_numeric_type, stress_variant | Keep question and gold answer `The Inflation Surprise Index for the United States experienced a larger absolut...`, but change answer_type to numeric with an explicit unit/tolerance, or rewrite the question to request exact text. |
| fin-ecb_fsr_2024_may-0041_spatial | validation | fix_required | duplicate_question, numeric_wording_with_non_numeric_type, stress_variant | Keep question and gold answer `The Inflation Surprise Index for the United States experienced a larger absolut...`, but change answer_type to numeric with an explicit unit/tolerance, or rewrite the question to request exact text. |
| dat-nRF24L01P_PS_v1.0.annot-0011_ds50 | validation | fix_required | duplicate_question, numeric_symbolic_expression_answer, stress_variant | Gold answer `VDD - 0.6` is symbolic, not scalar. Rewrite the question as symbolic/exact-match, or provide a concrete numeric value if the document defines the missing variable. |
| dat-Chapter3-0009 | test | fix_required | estimate_with_zero_tolerance | Keep gold answer `2`; set a non-zero absolute tolerance matching the question wording, or rewrite the question as an exact lookup. |
| dat-DS8237AB-06-0011 | test | fix_required | numeric_multi_field_answer | Compound gold `The DEM and CCM efficiency curves intersect at approximately 2 A load current,...` should not use scalar numeric scoring. Split the question into one scored scalar, or convert the row to exact/structured scoring. |
| dat-DUI0203-0012 | test | fix_required | numeric_hex_answer, numeric_missing_tolerance | Change answer_type to exact_match and use gold answer `0x27FC0000`, or add a hex-aware scorer before publishing. |
| dat-Lecture8-0003 | test | fix_required | estimate_with_zero_tolerance | Keep gold answer `24`; set a non-zero absolute tolerance matching the question wording, or rewrite the question as an exact lookup. |
| dat-Buck Converter Selection Criteria _ Richtek Technology-0005 | test | fix_required | duplicate_id, numeric_multi_field_answer | Compound gold `RT7241A, 12A, 23V` should not use scalar numeric scoring. Split the question into one scored scalar, or convert the row to exact/structured scoring. |
| fin-nvda-20260125-0041 | test | fix_required | numeric_wording_with_non_numeric_type | Keep question and gold answer `The combined total is 3,984 + 500,000 = 503,984 shares if you ignore the footno...`, but change answer_type to numeric with an explicit unit/tolerance, or rewrite the question to request exact text. |
| fin-fed_fsr_2024_nov-0029 | test | fix_required | tolerance_mismatch | Keep gold answer `Approximately 5 percentage points`, but set tolerance to `10`. |
| fin-ecb_fsr_2024_may-0041 | test | fix_required | numeric_wording_with_non_numeric_type | Keep question and gold answer `The Economic Surprise Index for the Euro area experienced a larger absolute cha...`, but change answer_type to numeric with an explicit unit/tolerance, or rewrite the question to request exact text. |
| fin-fed_fsr_2023_apr-0052_ds50 | test | fix_required | duplicate_question, numeric_ratio_prose_answer, stress_variant | Use scalar ratio gold `1`; keep dates/series values in rationale only. |
| fin-fed_fsr_2023_apr-0052_spatial | test | fix_required | bbox_without_image_dims, duplicate_question, numeric_ratio_prose_answer, page_image_supporting_page_count_mismatch, stress_variant | Use scalar ratio gold `1`; keep dates/series values in rationale only. |
| fin-imf_weo_2024_oct-0031_ds50 | test | fix_required | duplicate_question, numeric_wording_with_non_numeric_type, stress_variant | Keep question and gold answer `Knowledge and effect of policies; no, the difference is approximately 15-16 uni...`, but change answer_type to numeric with an explicit unit/tolerance, or rewrite the question to request exact text. |
| fin-imf_weo_2024_oct-0031_spatial | test | fix_required | duplicate_question, numeric_wording_with_non_numeric_type, stress_variant | Keep question and gold answer `Knowledge and effect of policies; no, the difference is approximately 15-16 uni...`, but change answer_type to numeric with an explicit unit/tolerance, or rewrite the question to request exact text. |
| dat-DS5091D-00-0043_spatial | test | fix_required | bbox_without_image_dims, duplicate_id, numeric_wording_with_non_numeric_type, page_image_supporting_page_count_mismatch, stress_variant | Keep question and gold answer `0.2`, but change answer_type to numeric with an explicit unit/tolerance, or rewrite the question to request exact text. |

## Patch-Ready Findings

| id | split | status | issue codes | proposed answer/question fix |
| --- | --- | --- | --- | --- |
| dat-DS8204L-04-0020 | train | fix_required | tolerance_mismatch | Keep gold answer `Approximately 75 mV`, but set tolerance to `25`. |
| dat-TTP223B-data-sheet-0001 | train | fix_required | numeric_wording_with_non_numeric_type | Keep question and gold answer `0.10 ± 0.06`, but change answer_type to numeric with an explicit unit/tolerance, or rewrite the question to request exact text. |
| dat-TTP223B-data-sheet-0017 | train | fix_required | duplicate_id | No answer rewrite indicated; assign a unique id such as `dat-TTP223B-data-sheet-0017__train_6` or remove the duplicate row after choosing the intended split/stress variant. |
| dat-TTP223B-data-sheet-0020 | train | fix_required | duplicate_id, duplicate_question | No answer rewrite indicated; assign a unique id such as `dat-TTP223B-data-sheet-0020__train_7` or remove the duplicate row after choosing the intended split/stress variant. |
| dat-DC_DC Converter Testing with Fast Load Transient _ Richtek Technology-0007 | train | fix_required | tolerance_mismatch | Keep gold answer `Approximately 45°`, but set tolerance to `10`. |
| dat-adrv9008-1-w-9008-2-w-9009-w-hardware-reference-manual-ug-1295-0018 | train | fix_required | numeric_prose_prefix_answer | Use scalar numeric gold `35`; keep label/context numbers in rationale. |
| dat-adrv9008-1-w-9008-2-w-9009-w-hardware-reference-manual-ug-1295-0032 | train | fix_required | numeric_wording_with_non_numeric_type | Keep question and gold answer `19:12`, but change answer_type to numeric with an explicit unit/tolerance, or rewrite the question to request exact text. |
| dat-opa454-0061 | train | fix_required | numeric_wording_with_non_numeric_type | Keep question and gold answer `±50 mA`, but change answer_type to numeric with an explicit unit/tolerance, or rewrite the question to request exact text. |
| fin-ecb_fsr_2024_nov-0056 | train | fix_required | numeric_formula_answer | Use scalar numeric gold `0.351` and move the equation/explanation to rationale. |
| fin-vis-ecb_fsr_2024_nov-0034 | train | fix_required | numeric_range_answer | Range gold `0.6 to 0.8` is not a single scalar. Split into lower/upper-bound questions, ask for a midpoint, or use exact/structured scoring. |
| dat-TTP223B-data-sheet-0020_ds50 | train | fix_required | duplicate_id, duplicate_question, stress_variant | No answer rewrite indicated; assign a unique id such as `dat-TTP223B-data-sheet-0020_ds50__train_55` or remove the duplicate row after choosing the intended split/stress variant. |
| dat-TTP223B-data-sheet-0020_spatial | train | fix_required | duplicate_id, duplicate_question, stress_variant | No answer rewrite indicated; assign a unique id such as `dat-TTP223B-data-sheet-0020_spatial__train_56` or remove the duplicate row after choosing the intended split/stress variant. |
| fin-boj_fsr_2024_apr-0020 | train | fix_required | numeric_wording_with_non_numeric_type | Keep question and gold answer `Fiscal 2024; the footnote states 2024 values are estimates, and the chart shows...`, but change answer_type to numeric with an explicit unit/tolerance, or rewrite the question to request exact text. |
| fin-imf_weo_2024_oct-0031 | train | fix_required | numeric_wording_with_non_numeric_type | Keep question and gold answer `Knowledge and effect of policies; no, the difference is approximately 15-16 uni...`, but change answer_type to numeric with an explicit unit/tolerance, or rewrite the question to request exact text. |
| dat-Buck Converter Selection Criteria _ Richtek Technology-0005 | train | fix_required | duplicate_id | No answer rewrite indicated; assign a unique id such as `dat-Buck Converter Selection Criteria _ Richtek Technology-0005__train_62` or remove the duplicate row after choosing the intended split/stress variant. |
| dat-TTP223B-data-sheet-0017 | train | fix_required | duplicate_id | No answer rewrite indicated; assign a unique id such as `dat-TTP223B-data-sheet-0017__train_66` or remove the duplicate row after choosing the intended split/stress variant. |
| dat-Arm_EE382N_4-0014 | validation | fix_required | estimate_with_zero_tolerance | Keep gold answer `2`; set a non-zero absolute tolerance matching the question wording, or rewrite the question as an exact lookup. |
| dat-DS5091D-00-0013 | validation | fix_required | tolerance_mismatch | Keep gold answer `Approximately 500 μs`, but set tolerance to `25`. |
| dat-DS5091D-00-0016 | validation | fix_required | duplicate_id | No answer rewrite indicated; assign a unique id such as `dat-DS5091D-00-0016__validation_43` or remove the duplicate row after choosing the intended split/stress variant. |
| dat-DS5091D-00-0043 | validation | fix_required | duplicate_id | No answer rewrite indicated; assign a unique id such as `dat-DS5091D-00-0043__validation_45` or remove the duplicate row after choosing the intended split/stress variant. |
| fin-aapl-20250927-0034 | validation | fix_required | numeric_wording_with_non_numeric_type | Keep question and gold answer `2022, $21`, but change answer_type to numeric with an explicit unit/tolerance, or rewrite the question to request exact text. |
| dat-infineon-power-mosfet-avalanche-design-guidelines-applicationnotes-en-0047 | validation | fix_required | duplicate_id, duplicate_question | No answer rewrite indicated; assign a unique id such as `dat-infineon-power-mosfet-avalanche-design-guidelines-applicationnotes-en-0047__validation_94` or remove the duplicate row after choosing the intended split/stress variant. |
| dat-spruhm8k-0002 | validation | fix_required | estimate_with_zero_tolerance | Keep gold answer `3`; set a non-zero absolute tolerance matching the question wording, or rewrite the question as an exact lookup. |
| dat-DS5091D-00-0043_spatial | validation | fix_required | answer_unit_mismatch, duplicate_id, stress_variant, tolerance_mismatch | Keep gold answer `0.2`, but set answer_unit to `V` and tolerance to `0.05`. |
| dat-infineon-power-mosfet-avalanche-design-guidelines-applicationnotes-en-0047_spatial | validation | fix_required | bbox_without_image_dims, duplicate_id, duplicate_question, page_image_supporting_page_count_mismatch, stress_variant | No answer rewrite indicated; assign a unique id such as `dat-infineon-power-mosfet-avalanche-design-guidelines-applicationnotes-en-0047_spatial__validation_107` or remove the duplicate row after choosing the intended split/stress variant. |
| fin-fed_fsr_2023_apr-0052 | validation | fix_required | numeric_ratio_prose_answer | Use scalar ratio gold `1`; keep dates/series values in rationale only. |
| dat-DS5091D-00-0016 | validation | fix_required | duplicate_id | No answer rewrite indicated; assign a unique id such as `dat-DS5091D-00-0016__validation_133` or remove the duplicate row after choosing the intended split/stress variant. |
| dat-nRF24L01P_PS_v1.0.annot-0011 | validation | fix_required | duplicate_question, numeric_symbolic_expression_answer | Gold answer `VDD - 0.6` is symbolic, not scalar. Rewrite the question as symbolic/exact-match, or provide a concrete numeric value if the document defines the missing variable. |
| fin-bis_qr_2024_sep-0034_ds50 | validation | fix_required | numeric_wording_with_non_numeric_type, stress_variant | Keep question and gold answer `China (CN) and the United States (US), as indicated by the darkest red cell at...`, but change answer_type to numeric with an explicit unit/tolerance, or rewrite the question to request exact text. |
| fin-boj_fsr_2024_apr-0020_ds50 | validation | fix_required | duplicate_question, numeric_wording_with_non_numeric_type, stress_variant | Keep question and gold answer `Fiscal 2024; the footnote states 2024 values are estimates, and the chart shows...`, but change answer_type to numeric with an explicit unit/tolerance, or rewrite the question to request exact text. |
| fin-boj_fsr_2024_apr-0020_spatial | validation | fix_required | duplicate_question, numeric_wording_with_non_numeric_type, stress_variant | Keep question and gold answer `Fiscal 2024; the footnote states 2024 values are estimates, and the chart shows...`, but change answer_type to numeric with an explicit unit/tolerance, or rewrite the question to request exact text. |
| fin-ecb_fsr_2024_may-0041_ds50 | validation | fix_required | duplicate_question, numeric_wording_with_non_numeric_type, stress_variant | Keep question and gold answer `The Inflation Surprise Index for the United States experienced a larger absolut...`, but change answer_type to numeric with an explicit unit/tolerance, or rewrite the question to request exact text. |
| fin-ecb_fsr_2024_may-0041_spatial | validation | fix_required | duplicate_question, numeric_wording_with_non_numeric_type, stress_variant | Keep question and gold answer `The Inflation Surprise Index for the United States experienced a larger absolut...`, but change answer_type to numeric with an explicit unit/tolerance, or rewrite the question to request exact text. |
| dat-TTP223B-data-sheet-0020_ds50 | validation | fix_required | duplicate_id, stress_variant | No answer rewrite indicated; assign a unique id such as `dat-TTP223B-data-sheet-0020_ds50__validation_195` or remove the duplicate row after choosing the intended split/stress variant. |
| dat-infineon-power-mosfet-avalanche-design-guidelines-applicationnotes-en-0047_spatial | validation | fix_required | duplicate_id, stress_variant | No answer rewrite indicated; assign a unique id such as `dat-infineon-power-mosfet-avalanche-design-guidelines-applicationnotes-en-0047_spatial__validation_211` or remove the duplicate row after choosing the intended split/stress variant. |
| dat-nRF24L01P_PS_v1.0.annot-0011_ds50 | validation | fix_required | duplicate_question, numeric_symbolic_expression_answer, stress_variant | Gold answer `VDD - 0.6` is symbolic, not scalar. Rewrite the question as symbolic/exact-match, or provide a concrete numeric value if the document defines the missing variable. |
| dat-Chapter3-0009 | test | fix_required | estimate_with_zero_tolerance | Keep gold answer `2`; set a non-zero absolute tolerance matching the question wording, or rewrite the question as an exact lookup. |
| dat-DS8237AB-06-0011 | test | fix_required | numeric_multi_field_answer | Compound gold `The DEM and CCM efficiency curves intersect at approximately 2 A load current,...` should not use scalar numeric scoring. Split the question into one scored scalar, or convert the row to exact/structured scoring. |
| dat-DUI0203-0012 | test | fix_required | numeric_hex_answer, numeric_missing_tolerance | Change answer_type to exact_match and use gold answer `0x27FC0000`, or add a hex-aware scorer before publishing. |
| dat-Lecture8-0003 | test | fix_required | estimate_with_zero_tolerance | Keep gold answer `24`; set a non-zero absolute tolerance matching the question wording, or rewrite the question as an exact lookup. |
| dat-Buck Converter Selection Criteria _ Richtek Technology-0005 | test | fix_required | duplicate_id, numeric_multi_field_answer | Compound gold `RT7241A, 12A, 23V` should not use scalar numeric scoring. Split the question into one scored scalar, or convert the row to exact/structured scoring. |
| fin-nvda-20260125-0041 | test | fix_required | numeric_wording_with_non_numeric_type | Keep question and gold answer `The combined total is 3,984 + 500,000 = 503,984 shares if you ignore the footno...`, but change answer_type to numeric with an explicit unit/tolerance, or rewrite the question to request exact text. |
| fin-fed_fsr_2024_nov-0029 | test | fix_required | tolerance_mismatch | Keep gold answer `Approximately 5 percentage points`, but set tolerance to `10`. |
| fin-ecb_fsr_2024_may-0041 | test | fix_required | numeric_wording_with_non_numeric_type | Keep question and gold answer `The Economic Surprise Index for the Euro area experienced a larger absolute cha...`, but change answer_type to numeric with an explicit unit/tolerance, or rewrite the question to request exact text. |
| dat-DS5091D-00-0043 | test | fix_required | duplicate_id | No answer rewrite indicated; assign a unique id such as `dat-DS5091D-00-0043__test_153` or remove the duplicate row after choosing the intended split/stress variant. |
| dat-TTP223B-data-sheet-0020 | test | fix_required | duplicate_id, duplicate_question | No answer rewrite indicated; assign a unique id such as `dat-TTP223B-data-sheet-0020__test_165` or remove the duplicate row after choosing the intended split/stress variant. |
| dat-infineon-power-mosfet-avalanche-design-guidelines-applicationnotes-en-0047 | test | fix_required | duplicate_id, duplicate_question | No answer rewrite indicated; assign a unique id such as `dat-infineon-power-mosfet-avalanche-design-guidelines-applicationnotes-en-0047__test_178` or remove the duplicate row after choosing the intended split/stress variant. |
| fin-fed_fsr_2023_apr-0052_ds50 | test | fix_required | duplicate_question, numeric_ratio_prose_answer, stress_variant | Use scalar ratio gold `1`; keep dates/series values in rationale only. |
| fin-fed_fsr_2023_apr-0052_spatial | test | fix_required | bbox_without_image_dims, duplicate_question, numeric_ratio_prose_answer, page_image_supporting_page_count_mismatch, stress_variant | Use scalar ratio gold `1`; keep dates/series values in rationale only. |
| fin-imf_weo_2024_oct-0031_ds50 | test | fix_required | duplicate_question, numeric_wording_with_non_numeric_type, stress_variant | Keep question and gold answer `Knowledge and effect of policies; no, the difference is approximately 15-16 uni...`, but change answer_type to numeric with an explicit unit/tolerance, or rewrite the question to request exact text. |
| fin-imf_weo_2024_oct-0031_spatial | test | fix_required | duplicate_question, numeric_wording_with_non_numeric_type, stress_variant | Keep question and gold answer `Knowledge and effect of policies; no, the difference is approximately 15-16 uni...`, but change answer_type to numeric with an explicit unit/tolerance, or rewrite the question to request exact text. |
| dat-DS5091D-00-0043_spatial | test | fix_required | bbox_without_image_dims, duplicate_id, numeric_wording_with_non_numeric_type, page_image_supporting_page_count_mismatch, stress_variant | Keep question and gold answer `0.2`, but change answer_type to numeric with an explicit unit/tolerance, or rewrite the question to request exact text. |
| dat-TTP223B-data-sheet-0020_spatial | test | fix_required | duplicate_id, duplicate_question, stress_variant | No answer rewrite indicated; assign a unique id such as `dat-TTP223B-data-sheet-0020_spatial__test_249` or remove the duplicate row after choosing the intended split/stress variant. |