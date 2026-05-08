"""Mine per-example prediction JSONs to surface failure modes.

Reads `predictions/*.json` under one or more spec dirs and reports tool-error
rates by category, lazy-answer rates, premature-final rates (ReAct/baseline),
iteration histograms, and the most common `action_input` shapes per tool.

Used to falsify or confirm hypotheses about a comparator's failure mode (e.g.
the 2026-05-04 finding that ReAct's collapse is lazy answers, not path
hallucination).

Usage:

    uv run python scripts/diagnose_predictions.py \\
        --spec-dir results/hf/headline-v1 \\
        --output results/diagnostics/headline-v1/report.md

Pass `--spec-dir` once per spec dir, OR point at a parent dir whose immediate
children are spec dirs (the headline-eval layout).
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class SpecDiagnosis:
    """One spec's failure-mode breakdown."""

    spec_name: str
    n_examples: int
    n_steps: int = 0
    n_tool_calls: int = 0
    n_tool_errors: int = 0
    error_categories: Counter[str] = field(default_factory=Counter)
    lazy_answer_rate: float = 0.0  # examples with tool_calls == 0
    empty_citation_rate: float = 0.0  # examples with citations == []
    correct_but_no_citations_rate: float = 0.0
    premature_final_rate: float | None = None  # None for non-comparator specs
    iterations_used_hist: Counter[int] = field(default_factory=Counter)
    action_input_top: dict[str, list[tuple[str, int]]] = field(default_factory=dict)
    mean_tool_calls: float = 0.0
    mean_iterations: float = 0.0
    mean_usd: float = 0.0
    accuracy: float = 0.0
    answers_correct: int = 0
    retry_used_rate: float = 0.0
    evidence_retry_used_rate: float = 0.0
    mean_retries_used: float = 0.0
    mean_evidence_retries_used: float = 0.0
    loop_terminated: Counter[str] = field(default_factory=Counter)
    incorrect_loop_terminated: Counter[str] = field(default_factory=Counter)
    loop_retry_helped: Counter[str] = field(default_factory=Counter)
    verifier_unsupported_rate: float | None = None
    verifier_next_actions: Counter[str] = field(default_factory=Counter)
    verifier_unsupported_next_actions: Counter[str] = field(default_factory=Counter)
    incorrect_verifier_next_actions: Counter[str] = field(default_factory=Counter)
    expand_context_called_rate: float = 0.0
    mean_neighbors_attached: float = 0.0
    mean_neighbors_added: float = 0.0
    tool_sequence_top: list[tuple[str, int]] = field(default_factory=list)
    total_evidence_packets: int = 0
    packet_text_coverage_rate: float = 0.0
    packet_linked_context_rate: float = 0.0
    packet_chart_rate: float = 0.0
    packet_chart_attempt_rate: float = 0.0
    packet_chart_empty_rate: float = 0.0
    packet_chart_error_rate: float = 0.0
    failure_reasons: Counter[str] = field(default_factory=Counter)
    cited_packet_count: int = 0
    cited_packet_resolved_rate: float | None = None
    cited_packet_text_coverage_rate: float | None = None
    cited_packet_linked_context_rate: float | None = None
    cited_packet_chart_rate: float | None = None
    cited_packet_image_only_rate: float | None = None
    verifier_unsupported_cited_image_only_rate: float | None = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def diagnose_spec(spec_dir: Path) -> SpecDiagnosis:
    """Diagnose all predictions for one spec dir.

    Prefer `<spec_dir>/per_example.jsonl` when present because it is the
    official run manifest input and preserves raw example ids. Fall back to
    `<spec_dir>/predictions/*.json` for in-flight or older runs.
    """
    diag = SpecDiagnosis(spec_name=spec_dir.name, n_examples=0)
    records = list(_iter_prediction_records(spec_dir))
    if not records:
        return diag

    is_comparator = _is_comparator_spec(spec_dir.name)
    tool_input_samples: dict[str, Counter[str]] = {}
    tool_call_counts: list[int] = []
    iteration_counts: list[int] = []
    usd_values: list[float] = []
    retries_used_values: list[int] = []
    evidence_retries_used_values: list[int] = []
    verifier_unsupported_flags: list[bool] = []
    expand_context_called_flags: list[bool] = []
    neighbors_attached_values: list[int] = []
    neighbors_added_values: list[int] = []
    tool_sequence_counter: Counter[str] = Counter()
    packet_has_text_flags: list[bool] = []
    packet_has_context_flags: list[bool] = []
    packet_has_chart_flags: list[bool] = []
    packet_chart_attempt_flags: list[bool] = []
    packet_chart_empty_flags: list[bool] = []
    packet_chart_error_flags: list[bool] = []
    cited_resolved_flags: list[bool] = []
    cited_has_text_flags: list[bool] = []
    cited_has_context_flags: list[bool] = []
    cited_has_chart_flags: list[bool] = []
    unsupported_cited_image_only_flags: list[bool] = []

    for record in records:
        diag.n_examples += 1
        steps = (record.get("trace") or {}).get("steps") or []
        diag.n_steps += len(steps)

        answer_correct = record.get("answer_correct", 0.0) >= 1.0
        if answer_correct:
            diag.answers_correct += 1
        usd_values.append(float(record.get("usd") or 0.0))
        telemetry = record.get("telemetry") or {}
        retries_used = _as_int(telemetry.get("retries_used"), default=0)
        evidence_retries_used = _as_int(telemetry.get("evidence_retries_used"), default=0)
        retries_used_values.append(retries_used)
        evidence_retries_used_values.append(evidence_retries_used)
        loop_terminated = telemetry.get("loop_terminated")
        if loop_terminated:
            diag.loop_terminated[str(loop_terminated)] += 1
            if not answer_correct:
                diag.incorrect_loop_terminated[str(loop_terminated)] += 1
        if telemetry.get("loop_retry_helped") is not None:
            diag.loop_retry_helped[str(bool(telemetry["loop_retry_helped"])).lower()] += 1

        per_example_tool_calls = 0
        per_example_iterations = 0
        first_step_was_final = False
        per_example_tool_sequence: list[str] = []
        verifier_supported: bool | None = None
        verifier_next_action: str | None = None
        expand_context_called = False
        neighbors_attached = 0
        neighbors_added = 0
        evidence_snapshot = _debug_evidence_snapshot(record) or _evidence_snapshot(record)
        packet_by_id = {
            str(pkt.get("packet_id")): pkt
            for pkt in evidence_snapshot
            if isinstance(pkt, dict) and pkt.get("packet_id")
        }
        for pkt in evidence_snapshot:
            if not isinstance(pkt, dict):
                continue
            diag.total_evidence_packets += 1
            packet_has_text_flags.append(_packet_has_text(pkt))
            packet_has_context_flags.append(_packet_has_linked_context(pkt))
            packet_has_chart_flags.append(_packet_has_chart(pkt))
            packet_chart_attempt_flags.append(_packet_chart_attempted(pkt))
            packet_chart_empty_flags.append(_packet_chart_empty(pkt))
            packet_chart_error_flags.append(_packet_chart_error(pkt))

        for i, step in enumerate(steps):
            action = step.get("action") or ""
            tool = step.get("tool")
            stage = step.get("stage") or ""
            step_args = step.get("args") or {}

            if action == "tool_call":
                per_example_tool_calls += 1
                if tool:
                    per_example_tool_sequence.append(str(tool))
                tool_input_samples.setdefault(tool or "?", Counter())[
                    _shape_action_input(step_args)
                ] += 1
            if action == "tool_error":
                diag.n_tool_errors += 1
                err = step_args.get("error") or "unknown"
                diag.error_categories[str(err)] += 1
            if action != "final_answer" and action != "react_final":
                per_example_iterations += 1
            if i == 0 and stage == "react_final":
                first_step_was_final = True
            if stage == "verify" and "supported" in step_args:
                verifier_supported = bool(step_args.get("supported"))
            if stage == "verify" and step_args.get("next_action"):
                verifier_next_action = str(step_args["next_action"])
            if stage == "expand_context":
                expand_context_called = True
                with suppress(TypeError, ValueError):
                    neighbors_attached += int(step_args.get("n_neighbors_attached") or 0)
                with suppress(TypeError, ValueError):
                    neighbors_added += int(step_args.get("n_neighbors_added") or 0)

        diag.n_tool_calls += per_example_tool_calls
        tool_call_counts.append(per_example_tool_calls)
        iteration_counts.append(per_example_iterations)
        diag.iterations_used_hist[per_example_iterations] += 1
        expand_context_called_flags.append(expand_context_called)
        neighbors_attached_values.append(neighbors_attached)
        neighbors_added_values.append(neighbors_added)
        if verifier_supported is not None:
            verifier_unsupported_flags.append(verifier_supported is False)
        if verifier_next_action:
            diag.verifier_next_actions[verifier_next_action] += 1
            if verifier_supported is False:
                diag.verifier_unsupported_next_actions[verifier_next_action] += 1
            if not answer_correct:
                diag.incorrect_verifier_next_actions[verifier_next_action] += 1
        if per_example_tool_sequence:
            tool_sequence_counter[" -> ".join(per_example_tool_sequence)] += 1
        else:
            tool_sequence_counter["<none>"] += 1

        answer_citations = _answer_packet_citations(record)
        any_cited_image_only = False
        for citation in answer_citations:
            diag.cited_packet_count += 1
            pkt = packet_by_id.get(citation)
            resolved = pkt is not None
            cited_resolved_flags.append(resolved)
            if not resolved:
                continue
            has_text = _packet_has_text(pkt)
            has_context = _packet_has_linked_context(pkt)
            has_chart = _packet_has_chart(pkt)
            cited_has_text_flags.append(has_text)
            cited_has_context_flags.append(has_context)
            cited_has_chart_flags.append(has_chart)
            if not has_text and not has_chart:
                any_cited_image_only = True
        if verifier_supported is False and answer_citations:
            unsupported_cited_image_only_flags.append(any_cited_image_only)
        if not answer_correct:
            diag.failure_reasons[
                _classify_failure_reason(
                    record,
                    answer_citations=answer_citations,
                    any_cited_image_only=any_cited_image_only,
                    verifier_supported=verifier_supported,
                )
            ] += 1

        # lazy_answer_rate: harness already stamps `is_lazy` on the record
        # using tool_calls == 0 OR no predicted bboxes. Trust that flag.
        if int(record.get("is_lazy", 0)) == 1:
            diag.lazy_answer_rate += 1
        if not record.get("citations"):
            diag.empty_citation_rate += 1
            if record.get("answer_correct", 0.0) >= 1.0:
                diag.correct_but_no_citations_rate += 1
        # premature_final = comparator emitted final_answer at iter 0 with
        # no prior tool call. Tracks the dominant failure mode.
        if is_comparator and first_step_was_final and per_example_tool_calls == 0:
            if diag.premature_final_rate is None:
                diag.premature_final_rate = 0.0
            diag.premature_final_rate += 1

    n = max(diag.n_examples, 1)
    diag.lazy_answer_rate /= n
    diag.empty_citation_rate /= n
    diag.correct_but_no_citations_rate /= n
    if is_comparator:
        if diag.premature_final_rate is not None:
            diag.premature_final_rate /= n
        else:
            diag.premature_final_rate = 0.0
    diag.mean_tool_calls = statistics.mean(tool_call_counts) if tool_call_counts else 0.0
    diag.mean_iterations = statistics.mean(iteration_counts) if iteration_counts else 0.0
    diag.mean_usd = statistics.mean(usd_values) if usd_values else 0.0
    diag.accuracy = diag.answers_correct / n
    diag.mean_retries_used = statistics.mean(retries_used_values) if retries_used_values else 0.0
    diag.mean_evidence_retries_used = (
        statistics.mean(evidence_retries_used_values) if evidence_retries_used_values else 0.0
    )
    diag.retry_used_rate = (
        statistics.mean(value > 0 for value in retries_used_values) if retries_used_values else 0.0
    )
    diag.evidence_retry_used_rate = (
        statistics.mean(value > 0 for value in evidence_retries_used_values)
        if evidence_retries_used_values
        else 0.0
    )
    diag.verifier_unsupported_rate = (
        statistics.mean(verifier_unsupported_flags) if verifier_unsupported_flags else None
    )
    diag.expand_context_called_rate = (
        statistics.mean(expand_context_called_flags) if expand_context_called_flags else 0.0
    )
    diag.mean_neighbors_attached = (
        statistics.mean(neighbors_attached_values) if neighbors_attached_values else 0.0
    )
    diag.mean_neighbors_added = (
        statistics.mean(neighbors_added_values) if neighbors_added_values else 0.0
    )
    diag.tool_sequence_top = tool_sequence_counter.most_common(5)
    diag.packet_text_coverage_rate = (
        statistics.mean(packet_has_text_flags) if packet_has_text_flags else 0.0
    )
    diag.packet_linked_context_rate = (
        statistics.mean(packet_has_context_flags) if packet_has_context_flags else 0.0
    )
    diag.packet_chart_rate = (
        statistics.mean(packet_has_chart_flags) if packet_has_chart_flags else 0.0
    )
    diag.packet_chart_attempt_rate = (
        statistics.mean(packet_chart_attempt_flags) if packet_chart_attempt_flags else 0.0
    )
    diag.packet_chart_empty_rate = (
        statistics.mean(packet_chart_empty_flags) if packet_chart_empty_flags else 0.0
    )
    diag.packet_chart_error_rate = (
        statistics.mean(packet_chart_error_flags) if packet_chart_error_flags else 0.0
    )
    diag.cited_packet_resolved_rate = (
        statistics.mean(cited_resolved_flags) if cited_resolved_flags else None
    )
    diag.cited_packet_text_coverage_rate = (
        statistics.mean(cited_has_text_flags) if cited_has_text_flags else None
    )
    diag.cited_packet_linked_context_rate = (
        statistics.mean(cited_has_context_flags) if cited_has_context_flags else None
    )
    diag.cited_packet_chart_rate = (
        statistics.mean(cited_has_chart_flags) if cited_has_chart_flags else None
    )
    diag.cited_packet_image_only_rate = (
        statistics.mean(
            not has_text and not has_chart
            for has_text, has_chart in zip(cited_has_text_flags, cited_has_chart_flags, strict=True)
        )
        if cited_has_text_flags
        else None
    )
    diag.verifier_unsupported_cited_image_only_rate = (
        statistics.mean(unsupported_cited_image_only_flags)
        if unsupported_cited_image_only_flags
        else None
    )

    diag.action_input_top = {
        tool: counter.most_common(5) for tool, counter in tool_input_samples.items()
    }
    return diag


def render_markdown(diags: list[SpecDiagnosis]) -> str:
    """Render a markdown report comparable to headline_table.md."""
    lines: list[str] = []
    lines.append("# Predictions diagnostics")
    lines.append("")
    lines.append(f"_Specs analyzed: {len(diags)}_")
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append(
        "| Spec | n | accuracy | lazy_rate | empty_cite_rate "
        "| premature_final | verifier_unsupported | expand_called "
        "| mean_neighbors | mean_new_neighbors | tool_err_rate | mean_tool_calls | mean_usd "
        "| retry_rate | evidence_retry_rate | top_loop | top_failure "
        "| top_verifier_action | top_wrong_action |"
    )
    lines.append(
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"
    )
    for d in diags:
        tool_err_rate = d.n_tool_errors / max(d.n_steps, 1)
        prem = f"{d.premature_final_rate:.1%}" if d.premature_final_rate is not None else "—"
        verifier_unsupported = (
            f"{d.verifier_unsupported_rate:.1%}" if d.verifier_unsupported_rate is not None else "—"
        )
        top_loop = _fmt_top_counter(d.loop_terminated)
        top_failure = _fmt_top_counter(d.failure_reasons)
        top_verifier_action = _fmt_top_counter(d.verifier_next_actions)
        top_wrong_action = _fmt_top_counter(d.incorrect_verifier_next_actions)
        lines.append(
            f"| {d.spec_name} | {d.n_examples} | {d.accuracy:.1%} "
            f"| {d.lazy_answer_rate:.1%} | {d.empty_citation_rate:.1%} "
            f"| {prem} | {verifier_unsupported} "
            f"| {d.expand_context_called_rate:.1%} | {d.mean_neighbors_attached:.2f} "
            f"| {d.mean_neighbors_added:.2f} | {tool_err_rate:.1%} | {d.mean_tool_calls:.2f} "
            f"| ${d.mean_usd:.4f} | {d.retry_used_rate:.1%} "
            f"| {d.evidence_retry_used_rate:.1%} | {top_loop} | {top_failure} "
            f"| {top_verifier_action} | {top_wrong_action} |"
        )
    lines.append("")

    lines.append("## Evidence Packet Quality")
    lines.append("")
    lines.append(
        "| Spec | packets | packet_text | packet_context | packet_chart "
        "| chart_attempt | chart_empty | chart_error "
        "| cited_packets | cited_resolved | cited_text | cited_context "
        "| cited_chart | cited_image_only | unsupported_cited_image_only |"
    )
    lines.append(
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"
    )
    for d in diags:
        lines.append(
            f"| {d.spec_name} | {d.total_evidence_packets} "
            f"| {d.packet_text_coverage_rate:.1%} "
            f"| {d.packet_linked_context_rate:.1%} "
            f"| {d.packet_chart_rate:.1%} "
            f"| {d.packet_chart_attempt_rate:.1%} "
            f"| {d.packet_chart_empty_rate:.1%} "
            f"| {d.packet_chart_error_rate:.1%} "
            f"| {d.cited_packet_count} "
            f"| {_fmt_optional_pct(d.cited_packet_resolved_rate)} "
            f"| {_fmt_optional_pct(d.cited_packet_text_coverage_rate)} "
            f"| {_fmt_optional_pct(d.cited_packet_linked_context_rate)} "
            f"| {_fmt_optional_pct(d.cited_packet_chart_rate)} "
            f"| {_fmt_optional_pct(d.cited_packet_image_only_rate)} "
            f"| {_fmt_optional_pct(d.verifier_unsupported_cited_image_only_rate)} |"
        )
    lines.append("")

    for d in diags:
        lines.append(f"## {d.spec_name}")
        lines.append("")
        lines.append(f"- examples: **{d.n_examples}**, accuracy: **{d.accuracy:.1%}**")
        lines.append(
            f"- mean tool calls / example: **{d.mean_tool_calls:.2f}**, "
            f"mean iterations: **{d.mean_iterations:.2f}**, "
            f"mean usd: **${d.mean_usd:.4f}**"
        )
        lines.append(f"- lazy_answer_rate (no tool calls): **{d.lazy_answer_rate:.1%}**")
        lines.append(f"- empty_citation_rate (citations == []): **{d.empty_citation_rate:.1%}**")
        lines.append(f"- correct but no citations: **{d.correct_but_no_citations_rate:.1%}**")
        lines.append(
            f"- retry_used_rate: **{d.retry_used_rate:.1%}**, "
            f"mean retries: **{d.mean_retries_used:.2f}**"
        )
        lines.append(
            f"- evidence_retry_used_rate: **{d.evidence_retry_used_rate:.1%}**, "
            f"mean evidence retries: **{d.mean_evidence_retries_used:.2f}**"
        )
        if d.loop_terminated:
            lines.append("- loop_terminated counts:")
            for status, count in d.loop_terminated.most_common():
                lines.append(f"  - `{status}`: {count}")
        if d.incorrect_loop_terminated:
            lines.append("- incorrect-example loop_terminated counts:")
            for status, count in d.incorrect_loop_terminated.most_common():
                lines.append(f"  - `{status}`: {count}")
        if d.loop_retry_helped:
            lines.append("- loop_retry_helped counts:")
            for status, count in d.loop_retry_helped.most_common():
                lines.append(f"  - `{status}`: {count}")
        if d.verifier_unsupported_rate is not None:
            lines.append(f"- verifier unsupported rate: **{d.verifier_unsupported_rate:.1%}**")
        if d.verifier_next_actions:
            lines.append("- verifier next_action counts:")
            for action, count in d.verifier_next_actions.most_common():
                lines.append(f"  - `{action}`: {count}")
        if d.verifier_unsupported_next_actions:
            lines.append("- unsupported verifier next_action counts:")
            for action, count in d.verifier_unsupported_next_actions.most_common():
                lines.append(f"  - `{action}`: {count}")
        if d.incorrect_verifier_next_actions:
            lines.append("- incorrect-example verifier next_action counts:")
            for action, count in d.incorrect_verifier_next_actions.most_common():
                lines.append(f"  - `{action}`: {count}")
        lines.append(
            f"- evidence packet text / context / chart coverage: "
            f"**{d.packet_text_coverage_rate:.1%}** / "
            f"**{d.packet_linked_context_rate:.1%}** / **{d.packet_chart_rate:.1%}**"
        )
        lines.append(
            f"- chart_to_table attempt / empty / error rate: "
            f"**{d.packet_chart_attempt_rate:.1%}** / "
            f"**{d.packet_chart_empty_rate:.1%}** / **{d.packet_chart_error_rate:.1%}**"
        )
        lines.append(
            f"- cited packet text / context / chart coverage: "
            f"**{_fmt_optional_pct(d.cited_packet_text_coverage_rate)}** / "
            f"**{_fmt_optional_pct(d.cited_packet_linked_context_rate)}** / "
            f"**{_fmt_optional_pct(d.cited_packet_chart_rate)}**"
        )
        lines.append(
            f"- cited packet image-only rate: **{_fmt_optional_pct(d.cited_packet_image_only_rate)}**"
        )
        lines.append(
            f"- expand_context called: **{d.expand_context_called_rate:.1%}**, "
            f"mean neighbors attached: **{d.mean_neighbors_attached:.2f}**, "
            f"mean new neighbors: **{d.mean_neighbors_added:.2f}**"
        )
        if d.failure_reasons:
            lines.append("- incorrect-example failure reasons:")
            for reason, count in d.failure_reasons.most_common():
                lines.append(f"  - `{reason}`: {count}")
        if d.premature_final_rate is not None:
            lines.append(
                f"- premature_final_rate (final at iter 0, no tool call): "
                f"**{d.premature_final_rate:.1%}**"
            )
        if d.error_categories:
            lines.append("- tool_error categories:")
            for cat, count in d.error_categories.most_common():
                lines.append(f"  - `{cat}`: {count}")
        if d.iterations_used_hist:
            lines.append("- iterations histogram:")
            for k in sorted(d.iterations_used_hist.keys()):
                lines.append(f"  - {k}: {d.iterations_used_hist[k]}")
        if d.tool_sequence_top:
            lines.append("- top tool-call sequences:")
            for sequence, count in d.tool_sequence_top:
                lines.append(f"  - `{sequence}` × {count}")
        if d.action_input_top:
            lines.append("- top action_input shapes per tool:")
            for tool, top in d.action_input_top.items():
                lines.append(f"  - **{tool}**:")
                for shape, count in top:
                    lines.append(f"    - `{shape}` × {count}")
        lines.append("")

    return "\n".join(lines)


def to_json(diags: list[SpecDiagnosis]) -> dict[str, Any]:
    return {
        "specs": [
            {
                "spec_name": d.spec_name,
                "n_examples": d.n_examples,
                "n_steps": d.n_steps,
                "n_tool_calls": d.n_tool_calls,
                "n_tool_errors": d.n_tool_errors,
                "error_categories": dict(d.error_categories),
                "lazy_answer_rate": d.lazy_answer_rate,
                "empty_citation_rate": d.empty_citation_rate,
                "correct_but_no_citations_rate": d.correct_but_no_citations_rate,
                "premature_final_rate": d.premature_final_rate,
                "iterations_used_hist": dict(d.iterations_used_hist),
                "action_input_top": d.action_input_top,
                "mean_tool_calls": d.mean_tool_calls,
                "mean_iterations": d.mean_iterations,
                "mean_usd": d.mean_usd,
                "accuracy": d.accuracy,
                "retry_used_rate": d.retry_used_rate,
                "evidence_retry_used_rate": d.evidence_retry_used_rate,
                "mean_retries_used": d.mean_retries_used,
                "mean_evidence_retries_used": d.mean_evidence_retries_used,
                "loop_terminated": dict(d.loop_terminated),
                "incorrect_loop_terminated": dict(d.incorrect_loop_terminated),
                "loop_retry_helped": dict(d.loop_retry_helped),
                "verifier_unsupported_rate": d.verifier_unsupported_rate,
                "verifier_next_actions": dict(d.verifier_next_actions),
                "verifier_unsupported_next_actions": dict(d.verifier_unsupported_next_actions),
                "incorrect_verifier_next_actions": dict(d.incorrect_verifier_next_actions),
                "expand_context_called_rate": d.expand_context_called_rate,
                "mean_neighbors_attached": d.mean_neighbors_attached,
                "mean_neighbors_added": d.mean_neighbors_added,
                "tool_sequence_top": d.tool_sequence_top,
                "total_evidence_packets": d.total_evidence_packets,
                "packet_text_coverage_rate": d.packet_text_coverage_rate,
                "packet_linked_context_rate": d.packet_linked_context_rate,
                "packet_chart_rate": d.packet_chart_rate,
                "packet_chart_attempt_rate": d.packet_chart_attempt_rate,
                "packet_chart_empty_rate": d.packet_chart_empty_rate,
                "packet_chart_error_rate": d.packet_chart_error_rate,
                "failure_reasons": dict(d.failure_reasons),
                "cited_packet_count": d.cited_packet_count,
                "cited_packet_resolved_rate": d.cited_packet_resolved_rate,
                "cited_packet_text_coverage_rate": d.cited_packet_text_coverage_rate,
                "cited_packet_linked_context_rate": d.cited_packet_linked_context_rate,
                "cited_packet_chart_rate": d.cited_packet_chart_rate,
                "cited_packet_image_only_rate": d.cited_packet_image_only_rate,
                "verifier_unsupported_cited_image_only_rate": (
                    d.verifier_unsupported_cited_image_only_rate
                ),
            }
            for d in diags
        ]
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_comparator_spec(spec_name: str) -> bool:
    return "_react_" in spec_name or "_agent_baseline_" in spec_name


def _shape_action_input(args: dict[str, Any] | None) -> str:
    """Render an action_input shape as a stable string for top-N counting.

    We don't print full values (they're per-example noisy). Instead we record
    the field set and field types: {'doc_path': str, 'page': int, ...}.
    """
    if not args:
        return "{}"
    inner = (args.get("action_input") if isinstance(args, dict) else None) or {}
    if not isinstance(inner, dict) or not inner:
        return "{}"
    parts = []
    for k in sorted(inner.keys()):
        v = inner[k]
        parts.append(f"{k}:{type(v).__name__}")
    return "{" + ", ".join(parts) + "}"


def _evidence_snapshot(record: dict[str, Any]) -> list[dict[str, Any]]:
    snapshot = (record.get("trace") or {}).get("evidence_snapshot") or []
    return [pkt for pkt in snapshot if isinstance(pkt, dict)]


def _debug_evidence_snapshot(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the latest evidence packet debug payload when present.

    Newer traces expose provenance args such as `chart_to_table:empty` only in
    debug packet payloads, not in the compact final evidence snapshot.
    Prefer the latest inspect/expand event so diagnostics can distinguish
    "chart extraction attempted and empty" from "chart extraction never routed."
    """
    latest: list[dict[str, Any]] = []
    for event in (record.get("trace") or {}).get("debug_events") or []:
        if event.get("stage") not in {"inspect", "expand_context"}:
            continue
        payload = event.get("payload") or {}
        packets = payload.get("packets") or []
        if isinstance(packets, list):
            latest = [pkt for pkt in packets if isinstance(pkt, dict)]
    return latest


def _answer_packet_citations(record: dict[str, Any]) -> list[str]:
    """Return packet-id citations emitted by the answer step.

    Scored records resolve citations to parser-bench page/bbox dicts, so the
    packet ids needed for evidence-quality analysis live in the answer step's
    JSON observation.
    """
    citations: list[str] = []
    for event in (record.get("trace") or {}).get("debug_events") or []:
        if event.get("stage") != "answer":
            continue
        payload = event.get("payload") or {}
        for citation in payload.get("citations") or []:
            if isinstance(citation, str):
                citations.append(citation)
            elif isinstance(citation, dict) and citation.get("packet_id"):
                citations.append(str(citation["packet_id"]))
    if citations:
        return citations

    for step in (record.get("trace") or {}).get("steps") or []:
        if step.get("stage") != "answer":
            continue
        parsed = _parse_jsonish(step.get("obs_summary"))
        for citation in parsed.get("citations") or []:
            if isinstance(citation, str):
                citations.append(citation)
            elif isinstance(citation, dict) and citation.get("packet_id"):
                citations.append(str(citation["packet_id"]))
    return citations


def _parse_jsonish(text: str | None) -> dict[str, Any]:
    if not text:
        return {}
    raw = text.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.lstrip().startswith("json"):
            raw = raw.lstrip()[4:]
    else:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            raw = raw[start : end + 1]
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _packet_has_text(packet: dict[str, Any]) -> bool:
    return bool((packet.get("text_layer_snippet") or "").strip()) or bool(
        (packet.get("ocr_snippet") or "").strip()
    )


def _packet_has_linked_context(packet: dict[str, Any]) -> bool:
    return bool(packet.get("linked_crop_refs") or packet.get("linked_neighbor_types"))


def _packet_has_chart(packet: dict[str, Any]) -> bool:
    return bool((packet.get("chart_csv") or "").strip())


def _packet_chart_attempted(packet: dict[str, Any]) -> bool:
    return "chart_to_table:attempt" in str(packet.get("provenance_args_hash") or "")


def _packet_chart_empty(packet: dict[str, Any]) -> bool:
    return "chart_to_table:empty" in str(packet.get("provenance_args_hash") or "")


def _packet_chart_error(packet: dict[str, Any]) -> bool:
    return "chart_to_table:error" in str(packet.get("provenance_args_hash") or "")


def _classify_failure_reason(
    record: dict[str, Any],
    *,
    answer_citations: list[str],
    any_cited_image_only: bool,
    verifier_supported: bool | None,
) -> str:
    """Single primary bucket for an incorrect example.

    The buckets are intentionally coarse and ordered by actionability for the
    inspect/expand research loop: first path/pathology failures, then evidence
    visibility, then verifier/reasoner extraction.
    """
    if int(record.get("is_lazy", 0)) == 1:
        return "lazy_or_no_bbox"
    if not answer_citations and not record.get("citations"):
        return "empty_citation"

    loc = (record.get("stages") or {}).get("localization") or {}
    region_recall = _as_float_or_none(loc.get("region_recall"))
    bbox_iou = _as_float_or_none(loc.get("bbox_iou_max"))
    if region_recall is not None:
        if region_recall <= 0.0:
            return "localization_miss"
        if region_recall < 1.0:
            return "partial_localization"
    elif bbox_iou is not None and bbox_iou <= 0.1:
        return "localization_miss"

    answer_pred = str(record.get("answer_pred") or "").strip().lower()
    loop = (record.get("stages") or {}).get("loop") or {}
    if answer_pred == "unanswerable" or loop.get("loop_terminated") == "abstained":
        return "abstained"
    if any_cited_image_only:
        return "cited_image_only"
    if verifier_supported is False:
        return "verifier_unsupported"
    return "reasoning_or_extraction"


def _as_float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _fmt_optional_pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.1%}"


def _fmt_top_counter(counter: Counter[str]) -> str:
    if not counter:
        return "—"
    reason, count = counter.most_common(1)[0]
    return f"`{reason}` ({count})"


def _iter_prediction_records(spec_dir: Path) -> Iterable[dict[str, Any]]:
    per_example = spec_dir / "per_example.jsonl"
    if per_example.is_file():
        for line in per_example.read_text().splitlines():
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue
        return

    pred_dir = spec_dir / "predictions"
    if not pred_dir.is_dir():
        return
    for path in sorted(pred_dir.glob("*.json")):
        try:
            yield json.loads(path.read_text())
        except json.JSONDecodeError:
            continue


def _resolve_spec_dirs(roots: Iterable[Path]) -> list[Path]:
    """Expand `--spec-dir` arguments. A root that contains `predictions/`
    directly is itself a spec dir; otherwise its immediate children are."""
    resolved: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        if (root / "per_example.jsonl").is_file() or (root / "predictions").is_dir():
            resolved.append(root)
            continue
        for child in sorted(root.iterdir()):
            if child.is_dir() and (
                (child / "per_example.jsonl").is_file() or (child / "predictions").is_dir()
            ):
                resolved.append(child)
    return resolved


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--spec-dir",
        action="append",
        type=Path,
        required=True,
        help="A spec dir (with predictions/) OR a parent of spec dirs. Pass multiple.",
    )
    ap.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Markdown report path. JSON sibling is written next to it.",
    )
    args = ap.parse_args()

    spec_dirs = _resolve_spec_dirs(args.spec_dir)
    if not spec_dirs:
        raise SystemExit("No spec dirs found under the supplied --spec-dir args.")

    diags = [diagnose_spec(d) for d in spec_dirs]
    md = render_markdown(diags)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(md)
    json_path = args.output.with_suffix(".json")
    json_path.write_text(json.dumps(to_json(diags), indent=2))
    print(f"wrote {args.output} and {json_path}")


if __name__ == "__main__":
    main()
