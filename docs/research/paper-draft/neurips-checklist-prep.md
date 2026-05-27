# FocusParse NeurIPS-Style Checklist Prep

Date: 2026-05-24

Status: draft answers and evidence map for a NeurIPS-style paper checklist. This
is not the final submitted checklist because the target workshop/conference,
template, anonymity policy, and artifact policy are not selected yet.

## Source Policy Read

Official pages checked on 2026-05-24:

```text
https://nips.cc/public/guides/PaperChecklist
https://neurips.cc/Conferences/2026/MainTrackHandbook
https://nips.cc/public/guides/CodeSubmissionPolicy
```

Submission-policy facts to preserve:

- The checklist is part of the submitted PDF and should not be removed.
- A NeurIPS-style submission PDF orders the paper, optional technical appendix,
  and checklist in one file.
- Checklist answers are visible to reviewers and can use `yes`, `no`, or
  `n/a` with short justifications and section references.
- Reproducibility can be supported through code/data release, detailed run
  instructions, hosted resources, or another verifiable path.
- Code/data submitted for review should be anonymized when double-blind policy
  applies; camera-ready artifacts can be de-anonymized.
- If a dataset is a main contribution, the paper should document access,
  persistence, metadata, license, restrictions, and limitations.
- LLM/agent use that is part of the method or experimental setup should be
  described in the paper.

## Draft Checklist Answers

| Area | Draft answer | Current evidence | Remaining gate |
| --- | --- | --- | --- |
| Claims | Yes. The draft uses the raw-verified 61.5% FocusParse +4 result and confines claims to the 148-row finance/datasheet slice. | `focusparse-submission-draft.md`, `latex/main.tex`, `final-headline-run-summary.md` | Re-check after venue-template conversion so the abstract, Results, and Conclusion still match. |
| Limitations | Yes. The draft has a Limitations section covering slice size, finance n=47, raw-missing 66.9% checkpoint, draft figure styling, Zotero blocker, and research-harness scope. | `focusparse-submission-draft.md`, `objective-completion-audit.md` | Carry limitations into the official template and keep the answer-shape negative-control caveat. |
| Theory / proofs | N/A. This is an empirical benchmark-and-harness paper, not a theorem/proof paper. | Paper draft structure | Keep any future formal claims out of the main argument unless proved. |
| Experimental reproducibility | Yes, with an artifact caveat. The package includes the pinned HF revision, benchmark SHA, source-PDF readiness, config snapshot, runbook, seven method `run.json` files, seven `per_example.jsonl` files, diagnostics, and manifest checksums. | `final-results-rerun-runbook.md`, `pinned-dataset-provenance.md`, `source-pdf-readiness.md`, `submission-review-package.md` | Commit or externally archive the exact dirty-worktree code/docs/results used for submission. |
| Open access to code/data | Partially yes. Public FocusParse/parser-bench/HF identities are recorded, and the slim package is locally reproducible. | `external-source-audit.md`, `pinned-dataset-provenance.md`, `submission-review-package.md` | Decide anonymized review artifact versus de-anonymized public URL/DOI after the target policy is known. |
| Experimental details | Yes. The docs specify the `agentic_multi_page` protocol, method specs, model tier SHA, dataset revision, source-PDF root, and rerun commands. | `final-headline-run-summary.md`, `final-results-rerun-runbook.md`, `configs/default.yaml` | Condense the essential settings into the venue paper or appendix. |
| Statistical significance | Yes for headline accuracy/cost. The rendered headline table includes 95% percentile-bootstrap confidence intervals with 1000 resamples and seed 42. | `final-headline-run-summary.md`, `headline/headline_table.md` | Ensure the CI method and uncertainty table survive venue formatting; optionally add a final FocusParse replicate if page budget allows. |
| Compute resources | Yes for the headline sweep. The compute disclosure records model providers, local host, max parallelism, wall-clock envelope, summed method-hours, total reported model-call cost, and exclusions. | `compute-resource-disclosure.md`, `final-headline-run-summary.md`, method `run.json` files, `manifest.json` | Refresh if the final table is rerun, provider pricing changes, or execution moves to another host. |
| Code of ethics | Pending author confirmation. The paper appears low human-subject risk, but final authors should explicitly confirm compliance. | `submission-readiness-checklist.md`, `venue-template-conversion-audit.md` | Author must review the target venue code of ethics before submission. |
| Broader impacts | Partially. The limitation docs note that FocusParse is a research harness and not a production parser; likely risks are over-trusting finance/document QA outputs and hallucinated citations. | `focusparse-submission-draft.md`, `objective-completion-audit.md` | Add a short broader-impact paragraph or checklist justification in the final template. |
| Safeguards | N/A for model release. The paper does not release a pretrained model with high misuse risk. | Current scope docs | If releasing a hosted demo, add usage limits and non-production disclaimers. |
| Licenses | Partially. FocusParse is Apache-2.0 and parser-bench submodule is MIT. External ParseBench is recorded as Apache-2.0. The source-PDF and derived-image release audit is now documented, but per-PDF source URLs/terms are not complete. | `README.md`, `third_party/parser-bench/README.md`, `external-source-audit.md`, `source-pdf-and-asset-license-audit.md` | Complete final source-PDF/third-party asset URL and terms audit before public artifact release. |
| New assets | Yes, with persistence caveat. The paper releases or references parser-bench, FocusParse code, result package, traces/figures, and review artifacts. | `pinned-dataset-provenance.md`, `dataset-characterization.md`, `submission-review-package.md` | Add persistent identifier or archive DOI, plus anonymized URL if double-blind review requires it. |
| Crowdsourcing / human subjects | N/A based on current docs. No crowdsourcing or human-subject experiment is described in the FocusParse draft. | Paper draft and dataset docs | If parser-bench used paid annotation or third-party human verification outside current docs, add instructions, compensation, and consent details. |
| IRB / participant risks | N/A based on current docs. The paper evaluates public/company PDF documents and model outputs, not human subjects. | Paper draft and dataset docs | Reconfirm with dataset creation notes before submission. |
| Declaration of LLM usage | Yes. LLMs are central to the evaluated systems and FocusParse harness, including planner/router/reasoner/verifier roles and baseline agents. | `methods-and-dataset-code-audit.md`, `configs/default.yaml`, `latex/main.tex` | Add final target-policy-compliant disclosure for method LLMs and any writing/coding assistance. |

## Ready-To-Port Justification Snippets

Claims:

> The abstract and introduction state the empirical scope directly: a pinned
> 148-row parser-bench slice of high-resolution datasheet and finance PDFs.
> The paper uses the raw-verified 61.5% FocusParse +4 result as the headline
> and treats the older 66.9% checkpoint as historical until raw artifacts are
> recovered or rerun.

Reproducibility:

> We provide the HF dataset revision, benchmark JSONL checksum, source-PDF
> readiness record, code/config snapshot, rerun commands, per-method run
> metadata, per-example predictions, diagnostics, qualitative assets, and
> manifest checksums. The remaining submission gate is to publish or anonymize
> the exact code/result archive according to the target venue policy.

Experimental details:

> All reported methods use the same pinned parser-bench materialization,
> `agentic_multi_page` protocol, source-PDF cache, and model tier SHA. The
> headline table compares Base VLM, ReAct +2/+4, generic Agent +2/+4, and
> FocusParse +2/+4 under one result package.

Compute:

> The experiments primarily use external LLM/VLM API calls plus local PDF
> staging, layout/cache reads, and result aggregation. The table reports
> per-method latency and USD-per-correct; final submission should also state the
> local host type, max parallelism, total wall-clock, and whether preliminary
> or failed exploratory runs are excluded from the compute total.

Updated headline-sweep compute answer:

> The main seven-method headline sweep evaluated 7 method specifications over
> 148 examples each (1,036 example-runs) with maximum parallelism 2. The sweep
> ran over a 2.56-hour wall-clock envelope and 4.54 summed method-hours.
> Reported model cost is computed from the repository pricing table, not a
> provider invoice, and totals $16.9441 for the headline sweep. The final run
> used OpenAI `gpt-5.4`, Anthropic `claude-haiku-4-5`, Gemini
> `gemini-2.5-flash`, and Gemini `gemini-3.1-pro-preview` through the
> FocusParse tier router. The local host inspected for packaging is a MacBook
> Pro (`Mac14,9`) with Apple M2 Pro, 10 CPU cores, 16 GB memory, and macOS
> 26.3.1.

Broader impact:

> FocusParse is a research harness for evidence-grounded document QA, not a
> production finance or engineering decision system. The main risks are
> over-trusting answers on dense documents, treating localized evidence as
> proof when a model has selected the wrong region, and deploying a
> research-grade sandbox against untrusted inputs.

LLM usage:

> LLMs and VLMs are the objects of study and are used as core components of the
> evaluated systems: planning, routing, answer generation, verification, and
> generic tool-agent baselines. The final submission should also follow the
> selected venue policy for disclosing AI assistance in writing, coding, or
> formatting.

## Before Final Submission

1. Convert these draft answers into the selected venue's checklist form.
2. Add section references after the official template page numbers are stable.
3. Decide anonymous versus public artifact URLs.
4. Refresh `compute-resource-disclosure.md` from the selected result package
   and port its final paragraph into the target checklist.
5. Complete the per-PDF source URL/terms fields identified in
   `source-pdf-and-asset-license-audit.md` and decide the archive DOI/release
   mode.
6. Re-run Zotero bibliography reconciliation or explicitly document a
   primary-source bibliography waiver.
