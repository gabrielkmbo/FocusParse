# Citation Map

This file records why each starter citation is in the paper draft and what
claim it should support.

Companion file: `docs/research/paper-draft/related-work-failure-matrix.md`
groups these citations by the failure mode each family leaves open for
FocusParse.

Live external-source checks are recorded in
`docs/research/paper-draft/external-source-audit.md`.

| Key | Source | Use in FocusParse paper | Notes |
| --- | --- | --- | --- |
| `agenticocr2026` | AgenticOCR | Query-conditioned, on-demand visual parsing; page-level chunking can overload attention and dilute salient evidence. | Closest "parse only what you need" related work. Contrast with FocusParse typed evidence packets, linked context expansion, and citation-required scoring. |
| `doclens2025` | DocLens | Evidence localization for long visual documents; navigate from document to pages/elements before answer adjudication. | Closest agentic long-doc system. Contrast with FocusParse stage machine, packet contract, and parser-bench evidence-localization metrics. |
| `parsebench2026` | RunLlama ParseBench | Agent-facing document parsing needs semantic correctness, grounding, chart/table fidelity. | Verified as arXiv v3 with public HF/GitHub artifacts and HF card. Important related benchmark but distinct from Gabriel's `parser-bench`: parsing output benchmark versus citation-required QA benchmark. |
| `mpdocbenchparse2026` | MPDocBench-Parse | Multi-page parsing benchmark context: semantic continuity, hierarchy recovery, reading order, table merging, and visual-content preservation. | New arXiv paper from 2026-05-21; useful because it validates the multi-page parsing motivation while still leaving query-conditioned QA evidence selection as the FocusParse gap. |
| `omnidocbench2025` | OmniDocBench | Broad PDF parsing benchmark with fine-grained annotations. | Use in benchmark-related-work section. |
| `doclaynet2022` | DocLayNet | Layout detection and document-layout analysis foundations. | FocusParse uses layout as a stage, not as the final task. |
| `gtefintabnet2021` | GTE / FinTabNet | Financial table structure recognition and detailed table annotations. | Use to position financial tables as related but narrower than grounded QA. |
| `docvqa2021` | DocVQA | Document visual question answering over document images. | Use as the general document-VQA foundation. |
| `infographicvqa2021` | InfographicVQA | Visual/layout/text/data-visualization reasoning over infographics. | Useful bridge to chart-like documents but not long finance/datasheet PDFs. |
| `mmlongbenchdoc2024` | MMLongBench-Doc | Long-context multimodal document understanding with cross-page evidence. | Good long-document benchmark contrast. |
| `finragbenchv2025` | FinRAGBench-V | Multimodal financial RAG with visual citations. | Very close domain/citation motivation; contrast parser-bench's region-level QA slice. |
| `finqa2021` | FinQA | Numerical reasoning over financial reports. | Use for finance reasoning lineage. |
| `tatqa2021` | TAT-QA | Hybrid financial table-text QA. | Use for table+text reasoning lineage. |
| `financebench2023` | FinanceBench | Open-book financial QA over SEC-style filings. | Use to motivate enterprise financial QA difficulty. |
| `react2023` | ReAct | Generic reasoning/action loop used by tool agents. | Use to cite the comparator family and explain why FocusParse is not just ReAct with tools. |
| `chartqa2022` | ChartQA | Chart QA with visual and logical reasoning. | Use to motivate chart reasoning; contrast with full-document evidence routing and citations. |
| `plotqa2020` | PlotQA | Real-valued plot QA and OOV answer challenge. | Use for chart/plot QA history. |
| `pubtabnet2020` | PubTabNet | Image-based table recognition and HTML structure metrics. | Use for table parsing lineage. |
| `focusparse2026` | FocusParse repo | Harness implementation. | GitHub connector resolves the private repo on `main`; replace moving URL with archival URL/commit before submission. |
| `parserbench_gabrielbo2026` | HF dataset | Dataset citation. | HF card and connector verified; current paper package uses pinned revision `3774c67f8b814392b6d04c939e904f749a3f52eb`. Replace or augment with DOI before submission. |

## Missing Citation Work

- Zotero local search is still unavailable because the local Zotero API at
  `127.0.0.1:23119` refuses connections and `open -a Zotero` cannot find a
  Zotero application on this machine. Install/start Zotero Desktop on this
  profile, then export a fuller bibliography.
- Verify final venue-preferred BibTeX metadata once Zotero is available.
- Add a small number of tool-use / agent citations beyond ReAct only if the
  final related-work section needs them.
- Add citations for the exact VLM baselines used in the final table if venue
  norms require model cards or technical reports.
