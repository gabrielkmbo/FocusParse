# Benchmark golden audit — main-stack n=148 failure set

Source: 75 wrong rows from `results/hf/sprint-2026-05-13/main-stack-run1`.

Companion to `2026-05-13-failure-triage.md`.


## Verdict definitions

- `harness_error`: gold is correct and unambiguous; harness produced a wrong / lazy answer. Counts against us.
- `unanswerable`: document does not contain a determinate answer. Gold should be 'Unanswerable' or revised. Upstream-fix candidate.
- `golden_incorrect`: gold is demonstrably wrong. Upstream-fix candidate.
- `ambiguous`: multiple reasonable answers exist or question scope is unclear. Partial harness fault.


## Initial verdict distribution (pre-PDF-review heuristic)

| Verdict | Count |
|---------|-------|
| harness_error | 74 |
| ambiguous | 1 |


## Per-bucket verdict summary

| Bucket | Total | harness_error | ambiguous | TBD |
|--------|-------|----------------|-----------|-----|
| bad_layout | 9 | 9 | 0 | 0 |
| lazy_abstain | 4 | 3 | 1 | 0 |
| wrong_extraction_normalizable | 4 | 4 | 0 | 0 |
| wrong_extraction_other | 45 | 45 | 0 | 0 |
| wrong_page | 13 | 13 | 0 | 0 |

## Notes on patterns observed

- **All 12 `is_lazy=1` rows have concrete non-null gold answers**, so these are 100% harness errors (the model said Unanswerable when the answer was present). This is the lazy_abstain bucket plus the cases in wrong_page where the router missed the page and the model downstream gave up.

- **Finance sentence-form golds**: `fin-bis_qr_2024_sep-0063` ('France (FR) experienced...'), `fin-boj_fsr_2024_apr-0010` ('Home prefecture contributed more...'), `fin-jpm_ltcma-0032` ('Developed markets (DM)...'), `fin-aapl-20250927-0009` (No-region explanation), and a handful more are sentence-form. Phase 3a (per-domain prompt routing) addresses these directly.

- **Datasheet tied-answer**: `dat-adrv9040-reference-manual-ug-2192-0052` (LOGGING vs LOGGING+MULTI-THREADING tied at 7) is a single-pick error on a tied condition. Phase 3a datasheet variant rule 5 addresses this.

- **No golden_incorrect candidates flagged automatically** — patterns in the failure set don't show obvious gold errors. A manual PDF-source audit is the gate before claiming any benchmark fix. Upstream (parser-bench) fix proposals must be submitted as a separate PR.


## Per-example verdicts (heuristic; refine via manual PDF review)

| example_id | bucket | verdict | pred | gold | rationale |
|-----------|--------|---------|------|------|-----------|
| dat-DS5091D-00-0002 | bad_layout | harness_error | 0 percentage points | Approximately 3% | model produced wrong answer; verify against source PDF befor... |
| dat-TTP223B-data-sheet-0058 | bad_layout | harness_error | 1 Q | Pin 1 (Q) is directly opposite to pin 6 (TOG). | model produced wrong answer; verify against source PDF befor... |
| dat-infineon-designing-with-power-mosfets-applicationnotes-en-0041 | bad_layout | harness_error | When Q1 switches off, the inductor current is commutate... | The inductor current (I_L) increases when Q1 is ON and ... | model produced wrong answer; verify against source PDF befor... |
| dat-opa454-0018 | bad_layout | harness_error | -60 mV | -400 | model produced wrong answer; verify against source PDF befor... |
| dat-slvaer0b-0011 | bad_layout | harness_error | loop 2. At the meantime, the area of the switching node... | Loop #2; the recommended layout for this area is to pla... | model produced wrong answer; verify against source PDF befor... |
| fin-10-K-0008 | bad_layout | harness_error | (1)ppt | 0% | model produced wrong answer; verify against source PDF befor... |
| fin-bis_qr_2025_mar-0061 | bad_layout | harness_error | US | United States (US) experienced both a noticeable increa... | pred is partial extraction; gold is sentence-form (Phase 3a ... |
| fin-bis_qr_2025_mar-0062 | bad_layout | harness_error | US; Europe | Europe experienced a larger increase in its ten-year te... | model produced wrong answer; verify against source PDF befor... |
| fin-boj_fsr_2024_oct-0008 | bad_layout | harness_error | 0.6% | -0.6 | model produced wrong answer; verify against source PDF befor... |
| dat-nRF24L01P_PS_v1.0.annot-0011 | lazy_abstain | harness_error | Unanswerable | VDD - 0.6 | model abstained / returned null on a question whose gold ans... |
| dat-spruhm8k-0025 | lazy_abstain | harness_error | Unanswerable | 0x3FFFF8 | model abstained / returned null on a question whose gold ans... |
| fin-10-K-0041 | lazy_abstain | harness_error | Unanswerable | The percentage decrease in technology-based intangible ... | model abstained / returned null on a question whose gold ans... |
| fin-imf_weo_2024_oct-0003 | lazy_abstain | ambiguous | Unanswerable | None - no topic in the visible portion of the table app... | model said Unanswerable; gold says 'None - no topic...' (als... |
| dat-armv6-interrupts.annot-0024 | wrong_extraction_normalizable | harness_error | FIQ | FIQ exception has a higher priority than IRQ exception. | pred is partial extraction; gold is sentence-form (Phase 3a ... |
| dat-spruhm8k-0063 | wrong_extraction_normalizable | harness_error | 25.2.1 EMIF Clock Control................................. | 2806 | pred over-extracted; gold is the precise span |
| fin-bis_qr_2024_sep-0063 | wrong_extraction_normalizable | harness_error | FR | France (FR) experienced the largest percentage increase... | pred is partial extraction; gold is sentence-form (Phase 3a ... |
| fin-boj_fsr_2024_apr-0010 | wrong_extraction_normalizable | harness_error | Home prefecture | Home prefecture contributed more to the total y/y % cha... | pred is partial extraction; gold is sentence-form (Phase 3a ... |
| dat-AN040_EN-0008 | wrong_extraction_other | harness_error | Iwireless | I_wireless; The diagram shows Q1 (the adapter path) as ... | model produced wrong answer; verify against source PDF befor... |
| dat-Arm_EE382N_4-0025 | wrong_extraction_other | harness_error | Arithmetic Shift Right Sign bit shifted in | Arithmetic Shift Right shifts in the sign bit, as indic... | model produced wrong answer; verify against source PDF befor... |
| dat-Arm_EE382N_4-0028 | wrong_extraction_other | harness_error | EXECUTE MEMORY WRITE | MEMORY; it occurs after EXECUTE and before WRITE. | model produced wrong answer; verify against source PDF befor... |
| dat-Arm_EE382N_4-0049 | wrong_extraction_other | harness_error | BLE ; Signed integer comparison gave less than or equal | BLE; Signed integer comparison gave less than or equal | model produced wrong answer; verify against source PDF befor... |
| dat-BCM2835-ARM-timer-int.annot-0029 | wrong_extraction_other | harness_error | The base address for the ARM timer register is 0x7E00B0... | The timer's 'Raw IRQ' register is mapped in a separate ... | model produced wrong answer; verify against source PDF befor... |
| dat-BCM2835-ARM-timer-int.annot-0047 | wrong_extraction_other | harness_error | The base address for the ARM interrupt register is 0x7E... | 0x2000B218 | model produced wrong answer; verify against source PDF befor... |
| dat-DC_DC Converter Testing with Fast Load Transient _ Richtek Technology-0055 | wrong_extraction_other | harness_error | φm = 49° | φm ≈ 36° | model produced wrong answer; verify against source PDF befor... |
| dat-DS5091D-00-0011 | wrong_extraction_other | harness_error | Return the manufacturer ID number : 0x00h | 0x00h; the description explicitly states this as the re... | model produced wrong answer; verify against source PDF befor... |
| dat-DS5091D-00-0013 | wrong_extraction_other | harness_error | 400 μs | Approximately 500 μs | model produced wrong answer; verify against source PDF befor... |
| dat-DS8237AB-06-0017 | wrong_extraction_other | harness_error | 0.697 0.704 0.711 | min: 0.697 V, typ: 0.704 V, max: 0.711 V | model produced wrong answer; verify against source PDF befor... |
| dat-SG017_2022-0054 | wrong_extraction_other | harness_error | RT9187C SOT-23-5 | RTQ2510-QA, VDFN3x3-8 | model produced wrong answer; verify against source PDF befor... |
| dat-adrv9040-reference-manual-ug-2192-0032 | wrong_extraction_other | harness_error | ADRV9040_FW.bin 641 kb | ADRV9040_FW.bin, 641 kb | model produced wrong answer; verify against source PDF befor... |
| dat-adrv9040-reference-manual-ug-2192-0041 | wrong_extraction_other | harness_error | The DPD algorithm updates coefficients only when the RM... | DPD_MODE1; this is visually indicated in the chart for ... | model produced wrong answer; verify against source PDF befor... |
| dat-adrv9040-reference-manual-ug-2192-0046 | wrong_extraction_other | harness_error | adi_adrv904x_OrxAttenSet() Sets the desired attenuation... | adi_adrv904x_OrxAttenSet(), dB | model produced wrong answer; verify against source PDF befor... |
| dat-adrv9040-reference-manual-ug-2192-0052 | wrong_extraction_other | harness_error | LOGGING, 6 | LOGGING and MULTI-THREADING are tied at 7 functions eac... | model produced wrong answer; verify against source PDF befor... |
| dat-ads1299-0044 | wrong_extraction_other | harness_error | b) Differential Input | Fully-differential input mode; this is shown in the cir... | model produced wrong answer; verify against source PDF befor... |
| dat-ads1299-0057 | wrong_extraction_other | harness_error | 32 t_CLK | 16 | model produced wrong answer; verify against source PDF befor... |
| dat-aducm350_ug-587-0043 | wrong_extraction_other | harness_error | 8 µs | 4 µs | model produced wrong answer; verify against source PDF befor... |
| dat-arm1176-ch13-debug-0012 | wrong_extraction_other | harness_error | b11 = Either. | b11 (Either), because when context ID comparison and li... | model produced wrong answer; verify against source PDF befor... |
| dat-arm1176-ch13-debug-0019 | wrong_extraction_other | harness_error | DSMCR; b000 b1011 | DSMCR, Opcode_2: b000, CRm: b1011 | model produced wrong answer; verify against source PDF befor... |
| dat-arm1176-ch3-coproc.annot-0004 | wrong_extraction_other | harness_error | Holds the base address. The reset value is 0. | 0 (reset value) | model produced wrong answer; verify against source PDF befor... |
| dat-arm1176-ch3-coproc.annot-0017 | wrong_extraction_other | harness_error | [31:24]=0x41, [23:20]=0x0, [19:16]=0xF, [15:4]=0xB76, [... | 0x410FB760; [19:16] Architecture | model produced wrong answer; verify against source PDF befor... |
| dat-arm1176-vm.annot-0022 | wrong_extraction_other | harness_error | Outer Write-Through. Non-Shared Normal, Write-Back Cach... | Non-Shared Normal, Write-Through Cacheable | model produced wrong answer; verify against source PDF befor... |
| dat-armv6.b3-coprocessor.annot-0002 | wrong_extraction_other | harness_error | Cache type register Cache type register on page B3-10 /... | Cache type register and Tightly Coupled Memory (TCM) ty... | model produced wrong answer; verify against source PDF befor... |
| dat-armv6.b3-coprocessor.annot-0011 | wrong_extraction_other | harness_error | Use the TLB type register layout to identify ILsize as ... | unanswerable | model produced wrong answer; verify against source PDF befor... |
| dat-infineon-applicationnote-linear-mode-operation-safe-operation-diagram-mosfets-applicationnotes-en-0006 | wrong_extraction_other | harness_error | 480 A | Approximately 520 A | model produced wrong answer; verify against source PDF befor... |
| dat-infineon-applicationnote-linear-mode-operation-safe-operation-diagram-mosfets-applicationnotes-en-0022 | wrong_extraction_other | harness_error | Vgs=2.9 V | Vgs = 2.9 V | model produced wrong answer; verify against source PDF befor... |
| dat-infineon-power-mosfet-avalanche-design-guidelines-applicationnotes-en-0047 | wrong_extraction_other | harness_error | constant junction temperature energy values | 315 mJ | model produced wrong answer; verify against source PDF befor... |
| dat-spruhm8k-0009 | wrong_extraction_other | harness_error | CEVT1 and CAP1 | CEVT4; CAP4 captures the new timestamp (t4, t8) at that... | model produced wrong answer; verify against source PDF befor... |
| dat-spruhm8k-0019 | wrong_extraction_other | harness_error | ADC_readPPBResult; ADC_setINLTrim; ADC_readResult | ADC_setINLTrim, ADC_readResult, ADC_readPPBResult | model produced wrong answer; verify against source PDF befor... |
| fin-10-K-0010 | wrong_extraction_other | harness_error | $(40) million | -40 | model produced wrong answer; verify against source PDF befor... |
| fin-10-K-0013 | wrong_extraction_other | harness_error | Balance Sheets 52 | Balance Sheets, page 52 | model produced wrong answer; verify against source PDF befor... |
| fin-10-K-0036 | wrong_extraction_other | harness_error | 82% | 68% | model produced wrong answer; verify against source PDF befor... |
| fin-aapl-20250927-0009 | wrong_extraction_other | harness_error | No; Japan had the highest percentage increase at 15 % w... | No, the region with the highest percentage increase (Ja... | model produced wrong answer; verify against source PDF befor... |
| fin-aapl-20250927-0034 | wrong_extraction_other | harness_error | September 2022 $ 136 $ 115 | 2022, $21 | model produced wrong answer; verify against source PDF befor... |
| fin-bis_qr_2024_sep-0050 | wrong_extraction_other | harness_error | D. FX loans | FX bonds | model produced wrong answer; verify against source PDF befor... |
| fin-bis_qr_2025_mar-0050 | wrong_extraction_other | harness_error | EE | Latvia | model produced wrong answer; verify against source PDF befor... |
| fin-boe_fsr_2024_nov-0056 | wrong_extraction_other | harness_error | UK | Germany | model produced wrong answer; verify against source PDF befor... |
| fin-ecb_fsr_2024_may-0057 | wrong_extraction_other | harness_error | loans to micro firms | Micro firms show a more noticeable uptick in NPL ratios... | model produced wrong answer; verify against source PDF befor... |
| fin-fed_fsr_2023_apr-0063 | wrong_extraction_other | harness_error | 30-year (left scale) | 10-year Treasury security showed the highest market dep... | model produced wrong answer; verify against source PDF befor... |
| fin-goog-20251231-0045 | wrong_extraction_other | harness_error | Class A Common Stock, $0.001 par value GOOGL | Class A Common Stock, $0.001 par value (GOOGL) | model produced wrong answer; verify against source PDF befor... |
| fin-jpm_gtm_us_daily-0049 | wrong_extraction_other | harness_error | Stephanie Aliaga New York | Lucia Gutierrez Mellado, Madrid | model produced wrong answer; verify against source PDF befor... |
| fin-jpm_ltcma-0032 | wrong_extraction_other | harness_error | Exhibit 4A: Contributors to 2026 LTCMA trend DM GDP gro... | Developed markets (DM); the chart matches the caption '... | model produced wrong answer; verify against source PDF befor... |
| fin-vis-jpm_gtm_us_daily-0109 | wrong_extraction_other | harness_error | 4 | 3 times | model produced wrong answer; verify against source PDF befor... |
| fin-vis-jpm_gtm_us_daily-0114 | wrong_extraction_other | harness_error | Feb 2020 to Jun 2022 | Feb 2020 to Apr 2020 | model produced wrong answer; verify against source PDF befor... |
| dat-AN040_EN-0010 | wrong_page | harness_error |  | You should use IOUT (along with the voltage at OUT) to ... | model abstained / returned null on a question whose gold ans... |
| dat-Buck Converter Selection Criteria _ Richtek Technology-0030 | wrong_page | harness_error | Unanswerable | Yes, the photographed component matches the UQFN-14L 2x... | model abstained / returned null on a question whose gold ans... |
| dat-SG017_2022-0053 | wrong_page | harness_error | Unanswerable | RTQ2532W or RTQ2532N (both list this feature set), Iout... | model abstained / returned null on a question whose gold ans... |
| dat-aducm350_ug-587-0032 | wrong_page | harness_error | Unanswerable | b0010 | model abstained / returned null on a question whose gold ans... |
| dat-arm1176-ch3-coproc.annot-0052 | wrong_page | harness_error |  | Cache Operations Register | model abstained / returned null on a question whose gold ans... |
| dat-infineon-applicationnote-linear-mode-operation-safe-operation-diagram-mosfets-applicationnotes-en-0019 | wrong_page | harness_error |  | Vgs = 2.9 V | model abstained / returned null on a question whose gold ans... |
| dat-infineon-applicationnote-mosfet-fast-switching-motivation--implementation-and-precautions-applicationnotes-en-0009 | wrong_page | harness_error |  | The largest components labeled 'Infineon' are most like... | model abstained / returned null on a question whose gold ans... |
| fin-aapl-20250927-0021 | wrong_page | harness_error | Unanswerable | Fiscal year end date: September 27, 2025; Classificatio... | model abstained / returned null on a question whose gold ans... |
| fin-bis_ar_2024-0062 | wrong_page | harness_error |  | Net income contributed more positively than Transfers b... | model abstained / returned null on a question whose gold ans... |
| fin-boe_fsr_2024_jun-0060 | wrong_page | harness_error |  | The US 10-year government bond yield is currently close... | model abstained / returned null on a question whose gold ans... |
| fin-fed_fsr_2023_apr-0052 | wrong_page | harness_error | 5 | On April 19, 2023, the 10-year OTR market depth (blue l... | pred is partial extraction; gold is sentence-form (Phase 3a ... |
| fin-jpm_gtm_us_daily-0014 | wrong_page | harness_error |  | France, 49.9 | model abstained / returned null on a question whose gold ans... |
| fin-jpm_gtm_us_daily-0023 | wrong_page | harness_error | Unanswerable | Small cap has the highest proportion of value stocks by... | model abstained / returned null on a question whose gold ans... |