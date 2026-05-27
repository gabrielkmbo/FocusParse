# FocusParse Compute And Resource Disclosure

Date: 2026-05-25

Status: paper-checklist compute disclosure for the raw-verified seven-method
headline run. This records what the current result package proves and what
still needs author confirmation before a final venue checklist.

## Scope

This disclosure covers the full matched seven-method headline run:

```text
results/hf/paper/2026-05-24-paper-headline-v1/
```

It does not include all exploratory runs, failed/retried development runs,
qualitative figure generation, or the n=148 mechanism ablations unless stated
separately. Use this as the main-paper compute statement and add an appendix
row for extra ablations if the target venue asks for total project compute.

## Run Envelope

| Field | Value |
| --- | --- |
| Run slug | `2026-05-24-paper-headline-v1` |
| Created at | `2026-05-24T08:43:55.059326+00:00` |
| First method start | `2026-05-24T06:06:45+00:00` |
| Last method end | `2026-05-24T08:40:30+00:00` |
| Wall-clock envelope | 2.56 hours |
| Sum of per-method wall times | 4.54 method-hours |
| Max parallelism | 2 |
| Method specs | 7 |
| Examples per method | 148 |
| Total example-runs | 1,036 |
| Protocol | `agentic_multi_page` |
| Tier SHA | `0b139a04` |
| HF dataset revision | `3774c67f8b814392b6d04c939e904f749a3f52eb` |

The wall-clock envelope is shorter than the sum of per-method wall times
because the evaluation runner used parallelism up to 2.

## Local Host

Inspected on the current machine while preparing the paper package:

| Field | Value |
| --- | --- |
| OS | macOS 26.3.1, build `25D2128` |
| Kernel / architecture | Darwin `25.3.0`, `arm64` |
| Machine class | MacBook Pro, model identifier `Mac14,9` |
| Chip | Apple M2 Pro |
| CPU cores | 10 total: 6 performance, 4 efficiency |
| Memory | 16 GB |

The final submission should re-check this if the final rerun happens on a
different host. Do not include local serial numbers or hardware UUIDs in paper
artifacts.

## Model Providers And Roles

All seven headline method specs use the same resolved tier map:

| Role | Provider | Model | Limit / setting |
| --- | --- | --- | --- |
| Planner | Gemini | `gemini-2.5-flash` | `max_tokens=4096`, `thinking_budget=1024` |
| Router | Gemini | `gemini-2.5-flash` | `max_tokens=4096`, `thinking_budget=1024` |
| Localizer rerank | Anthropic | `claude-haiku-4-5` | `max_tokens=4096` |
| Schema extractor | Gemini | `gemini-3.1-pro-preview` | `max_tokens=8192`, `thinking_level=high`, `media_resolution=high` |
| Reasoner | OpenAI | `gpt-5.4` | `max_completion_tokens=8192` |
| Verifier | Anthropic | `claude-haiku-4-5` | `max_tokens=4096` |
| Inspector dispatch | Anthropic | `claude-haiku-4-5` | `max_tokens=4096` |

The table above is from the saved `resolved_tiers` payloads in the method
summary JSON files under the headline result directory.

## Reported Model Cost

Cost is computed by `src/focusparse/eval/pricing.py`, not by a provider invoice.
The pricing table records published list prices in USD per 1M tokens and is
version-commented as OpenAI/Anthropic 2026-04 list prices and Gemini 2026-05
API list prices. The headline run uses priced OpenAI, Anthropic, and Gemini
models from that table.

| Method | Wall min | Total USD | Mean latency / example |
| --- | ---: | ---: | ---: |
| Base VLM | 10.1 | $0.6650 | 2.52s |
| ReAct +2 tools | 42.5 | $3.6201 | 14.00s |
| ReAct +4 tools | 47.1 | $4.6701 | 14.40s |
| Agent baseline +2 tools | 17.1 | $1.5888 | 5.21s |
| Agent baseline +4 tools | 17.1 | $1.6302 | 5.25s |
| Our harness +2 tools | 59.1 | $2.5108 | 3.30s |
| Our harness +4 tools | 79.4 | $2.2591 | 3.20s |
| **Total headline sweep** | **272.2 method-min** | **$16.9441** | n/a |

Interpretation caveats:

- `Total USD` sums per-example model-call telemetry and should be treated as a
  point-in-time estimate.
- Mean latency is mean per-example latency from the result table, not the
  method's end-to-end wall time.
- Local CPU time, electricity, storage, Hugging Face hosting, Modal layout
  endpoint overhead, and source-PDF hydration are not monetized in this table.
- Exploratory runs, smoke runs, qualitative rendering, and mechanism ablations
  are not included in the `$16.9441` headline-sweep total.
- Provider retries are included only insofar as they are represented in the
  saved per-example model-call telemetry.

## Paper-Ready Checklist Answer

For a NeurIPS-style checklist, the current truthful answer is:

> The main seven-method headline sweep evaluated 7 method specifications over
> 148 examples each (1,036 example-runs) with maximum parallelism 2. The sweep
> ran from 2026-05-24 06:06:45 UTC to 08:40:30 UTC, a 2.56-hour wall-clock
> envelope and 4.54 summed method-hours. Reported model cost is computed from
> the repository pricing table, not a provider invoice, and totals $16.9441 for
> the headline sweep. The final run used OpenAI `gpt-5.4`, Anthropic
> `claude-haiku-4-5`, Gemini `gemini-2.5-flash`, and Gemini
> `gemini-3.1-pro-preview` through the FocusParse tier router. The local host
> inspected for packaging is a MacBook Pro (`Mac14,9`) with Apple M2 Pro,
> 10 CPU cores, 16 GB memory, and macOS 26.3.1.

Before final submission, rerun or refresh this disclosure if the final table is
regenerated, if provider pricing changes, or if the final run moves to another
machine.
