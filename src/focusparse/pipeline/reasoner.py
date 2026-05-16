"""ANSWER stage — frontier-tier reasoner sees ONLY EvidencePackets.

Never the full document. The reasoner is handed one image per packet plus a
prompt that enumerates packet ids; it emits `{answer, citations, confidence}`
where citations are packet-id strings the verifier can look up.

Phase 2 skeleton: single-shot call. Sub-phase 2f adds K=2 self-consistency
sampling + escalation wiring.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from focusparse.models.base import ModelClient, ModelResponse
from focusparse.pipeline.answer_contract import build_answer_contract, render_answer_contract
from focusparse.pipeline.events import AnswerEvent, EvidenceEvent, QuestionEvent
from focusparse.pipeline.evidence_groups import build_evidence_groups, render_evidence_groups

_SYSTEM_PROMPT = (
    "You are answering a question about a document using the provided evidence packets. "
    "Each packet shows a page region with a packet_id (e.g. pkt_000). "
    "Evidence groups summarize how a packet should be bound to nearby headers, "
    "units, captions, legends, axes, and footnotes; packet descriptors preserve "
    "the citation-level text and image-order details. "
    "When a packet's descriptor lists image scales, the packet images appear in that "
    "listed order. `tight` is the target region; `context` and `chart_context` are "
    "wider crops for nearby labels, axes, legends, and curve geometry; `zoomed` "
    "is a readable upsampled copy of the same tight crop. "
    "When a packet's descriptor lists 'Attached neighbor images', the images that follow "
    "the packet crop images are CONTEXT (caption, footnote, section header, etc.). "
    "'Attached text-only context' has already been extracted from neighboring regions; "
    "use that text directly and do not expect a separate image for it. "
    "`context_window` is a wider crop around the same cited packet, useful for "
    "reading surrounding axes, gridlines, row/column headers, and labels. "
    "Use the primary crop to ground the answer; consult the neighbor crops only "
    "when the answer requires reading text or labels around the primary region. "
    "For chart readings, use the question-target scale when a packet text calls one out. "
    "Return strict JSON with keys `answer`, `citations`, and `confidence`. "
    "`answer` is the answer string (or the literal word 'Unanswerable'). "
    "`citations` is a list of packet_id strings that directly support the answer. "
    "`confidence` is a float in [0,1]. Do not add extra keys."
)

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_CONTEXT_LINE_RE = re.compile(r"^Context\s+\[(?P<role>[^\]]+)\]:\s*(?P<text>.+)$")
_BIT_ASSIGNMENT_RE = re.compile(r"\[\s*(?P<bits>\d+(?::\d+)?)\s*\]\s*=\s*(?P<value>b[01xX]+)")
_MAX_PACKET_TEXT_CHARS = 240
_MAX_TEXT_ONLY_CONTEXT_CHARS = 120
_TEXT_ONLY_NEIGHBOR_TYPES = frozenset(
    {
        "header-disambiguation",
        "page-footer",
        "page-header",
        "section-header",
        "title",
    }
)
_FOCUS_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "the",
        "to",
        "with",
        "what",
        "which",
    }
)


_DATASHEET_EXACT_MATCH_HINT = (
    "Answer with the exact label, identifier, or phrase from the document. "
    "Quote the document verbatim — do not paraphrase, abbreviate, or add "
    "explanation text that isn't present in the document. Match the "
    "document's exact punctuation, case, and spacing. Even if the question "
    "asks for an explanation, put only the final exact answer in the "
    "`answer` field.\n\n"
    "Formatting rules (Phase 6a tightening):\n"
    "1. Output ONLY the answer span. Do NOT prefix the value with a "
    "label or category name from the document (e.g., if the gold "
    "answer is '180,683; typical', do not write 'Gross margin "
    "180,683, typical').\n"
    "2. Do NOT append a description, definition, or trailing context "
    "after the value (e.g., if the gold answer is '[31:16]', do not "
    "write '[31:16] - Reserved. RAZ.').\n"
    "3. When the answer is a multi-part phrase joined by punctuation "
    "(e.g., 'A; B' or 'A and B'), include ALL parts in the exact "
    "form they appear in the document — do not truncate to the first "
    "part and do not reorder the parts.\n"
    "4. Do NOT return alternative or conditional answers ('if X then "
    "A; if Y then B'). Select the single value that matches the "
    "question's specified condition.\n"
    "5. When the question asks which item has the maximum/minimum/most "
    "frequent property AND the visible evidence shows two or more items "
    "tied at that value, list ALL tied items joined by ' and ' (e.g. "
    "'LOGGING and MULTI-THREADING are tied at 7 functions each'). Do not "
    "arbitrarily pick one.\n\n"
    "For register bit-field assignments, omit spaces around '=' and "
    "separate assignments with comma+space, e.g. [15:14]=b00, "
    "[8:5]=b1111."
)

# Phase 3a v2 (2026-05-13 sprint): finance documents diverge from
# datasheets, but the divergence is concentrated in a SPECIFIC set of
# question_families where the gold is a sentence-form claim about a
# chart (e.g. 'Micro firms show a more noticeable uptick in NPL
# ratios...'). For short-label finance golds (author names, ticker
# strings, '$(40) million'), the original Phase 6a strict prompt is
# the better choice — relaxing it on those examples causes
# over-extraction ('Stephanie Aliaga — her portrait and caption are
# directly above Grant Papa in the leftmost Americas New York
# column' instead of the gold 'Stephanie Aliaga').
#
# So the relaxed variant is gated on (domain == finance) AND
# (question_family in _SENTENCE_FORM_FAMILIES). Everything else
# falls back to the strict datasheet prompt.
_SENTENCE_FORM_FAMILIES: frozenset[str] = frozenset(
    {
        # Finance families whose gold answers are frequently sentence-form
        # claims about chart/figure contents (per the n=148 failure triage).
        "chart_caption_fusion",
        "chart_footnote_fusion",
        "multi_chart_comparison",
        "chart_table_cross_ref",
        "dual_axis_disambiguation",
        "figure_caption_cross_ref",
        # `distant_evidence_fusion` on finance also tends sentence-form
        # (synthesized claims spanning regions), though on datasheet it
        # is typically a short label — so we filter by domain too.
        "distant_evidence_fusion",
    }
)


_FINANCE_SENTENCE_FORM_EXACT_MATCH_HINT = (
    "Answer with the exact label, identifier, phrase, or short descriptive "
    "clause from the document. Quote the document verbatim where possible "
    "and preserve its exact wording, punctuation, units, currency symbols, "
    "and parenthesization.\n\n"
    "Formatting rules (finance sentence-form variant; applies because the "
    "question_family is one that often has a sentence-form gold answer):\n"
    "1. When the document presents the answer as a descriptive sentence or "
    "clause about a chart, trend, comparison, or relationship between "
    "regions / categories / time periods, include the full clause as it "
    "appears — do not collapse to a single tag (e.g. if the gold answer "
    "is 'Micro firms show a more noticeable uptick in NPL ratios at the "
    "end of the period', do NOT answer 'loans to micro firms').\n"
    "2. When the document presents the answer as a short label or single "
    "value, keep it short — match the granularity of the document's own "
    "phrasing. Do not pad short answers with explanatory clauses (e.g. if "
    "the gold answer is the name 'Stephanie Aliaga', do NOT add '— her "
    "portrait is in the leftmost column'). When in doubt about length, "
    "favor a SHORT answer matching the most direct span in the document.\n"
    "3. When the answer is a multi-part phrase joined by punctuation, "
    "include ALL parts in the exact form they appear in the document — do "
    "not truncate to the first part and do not reorder the parts.\n"
    "4. Do NOT return alternative or conditional answers ('if X then A; "
    "if Y then B'). Select the single value that matches the question's "
    "specified condition.\n"
    "5. For chart readings: state the value at the labelled axis tick "
    "closest to the curve / bar / point being asked about. If the document "
    "uses a country, region, or category name in its own legend / label, "
    "answer with that full name (e.g. 'Latvia', not the 2-letter ISO "
    "code 'LV')."
)


def _is_finance_domain(domain: str | None) -> bool:
    return bool(domain) and "finance" in domain.lower()


def _format_hint(
    answer_type: str | None,
    *,
    domain: str | None = None,
    question_family: str | None = None,
) -> str:
    """Mirror of `workflow._format_hint`. Kept local to avoid a workflow import
    cycle (reasoner is imported by workflow). Type-aware nudges so the model
    emits scorer-compliant output instead of prose.

    Phase 3a v2 (2026-05-13 sprint): exact_match prompt routes by
    (domain, question_family). The strict datasheet prompt is the
    default; the relaxed finance sentence-form variant fires ONLY when
    domain == finance AND question_family is known to often have a
    sentence-form gold. This avoids over-extraction on short-label
    finance answers (author names, ticker strings, etc.).
    """
    if not answer_type:
        return ""
    s = str(answer_type)
    stem = s.split(".")[-1].lower() if "." in s else s.lower()
    if stem == "numeric":
        return (
            "Answer with a single number, including the requested unit or % sign "
            "when the question explicitly asks for one. Do not add explanations "
            "or extra units beyond what the question asks for."
        )
    if stem == "exact_match":
        # Phase 3a v2: relaxed variant fires ONLY for finance examples
        # whose question_family is known to often have a sentence-form
        # gold answer. All other examples (including most of finance —
        # author names, ticker strings, short cell values) get the strict
        # datasheet prompt to avoid over-extraction.
        fam = (question_family or "").lower()
        if _is_finance_domain(domain) and fam in _SENTENCE_FORM_FAMILIES:
            return _FINANCE_SENTENCE_FORM_EXACT_MATCH_HINT
        return _DATASHEET_EXACT_MATCH_HINT
    if stem == "boolean":
        return "Answer 'yes' or 'no'."
    if stem == "multiple_choice":
        return "Answer with the letter of the correct choice (A, B, C, ...)."
    if stem == "unanswerable":
        return "If the document does not contain the answer, reply 'Unanswerable'."
    return ""


async def answer_from_evidence(
    question: QuestionEvent,
    evidence: EvidenceEvent,
    *,
    backend_client: ModelClient,
    escalation_hint: str | None = None,
    question_family: str | None = None,
    sample_variant: int = 0,
) -> tuple[AnswerEvent, ModelResponse]:
    """One VLM call over the packet images. Returns parsed answer + raw response.

    The raw `ModelResponse` comes back alongside the `AnswerEvent` so the
    workflow can attribute tokens and cost to the reasoner step.

    `escalation_hint`, when provided, is prepended to the prompt as the
    verifier's reason for rejecting the previous answer. This is how the
    `verifier→retry→escalate_reasoner` control-flow loop tells the
    reasoner "your last try was unsupported; here's why" without changing
    the evidence packets. Pass it from the workflow's retry handler; pass
    None for first-attempt and routine answer calls.

    `question_family`, when provided, routes the exact_match format hint
    to a domain × family-specific variant (Phase 3a v2). The workflow
    passes `plan.question_family`; tests / direct callers can omit.

    `sample_variant` (Phase 3b, 2026-05-14 sprint) selects a prompt
    variant when running K=2 self-consistency. Variant 0 is the default
    prompt (back-compat). Variant 1 adds a verbatim-grounding nudge — a
    different angle so K=2 isn't just sampling-noise on the same prompt.
    """
    packet_list = "\n".join(
        _render_packet_line(p, question_text=question.question) for p in evidence.packets
    )
    hint_block = ""
    if escalation_hint:
        hint_block = (
            "Your previous answer was rejected by the verifier with this reason:\n"
            f"{escalation_hint}\n\n"
            "Re-read the evidence packets carefully and produce an answer that "
            "addresses the verifier's concern. Keep the answer field concise "
            "and scorer-compliant: do not add explanations, qualifiers, or "
            "copied verifier language.\n\n"
        )
    format_hint = _format_hint(
        question.answer_type,
        domain=question.domain,
        question_family=question_family,
    )
    answer_contract = build_answer_contract(
        question.question,
        answer_type=question.answer_type,
        domain=question.domain,
        question_family=question_family,
    )
    contract_block = render_answer_contract(answer_contract)
    evidence_group_block = render_evidence_groups(
        build_evidence_groups(
            evidence.packets,
            question_text=question.question,
            contract=answer_contract,
        ),
        contract=answer_contract,
    )
    format_block = f"\n{format_hint}\n" if format_hint else ""
    variant_block = _sample_variant_addendum(sample_variant)
    prompt = (
        f"{hint_block}"
        f"Question: {question.question}\n\n"
        f"Question answer contract:\n{contract_block}\n\n"
        "Available grouped evidence objects "
        "(cite the primary packet ids, not group ids):\n"
        f"{evidence_group_block}\n\n"
        f"Packet-level descriptors for exact span reading:\n{packet_list}\n\n"
        "Use the grouped evidence to choose the correct row/entity/series, "
        "and use packet descriptors to read the exact answer span. "
        "Do not answer Unanswerable when a cited packet already contains the "
        f"requested value or label.{format_block}{variant_block}"
    )
    images = _collect_packet_images(evidence)

    response = await backend_client.predict(
        prompt=prompt,
        images=images,
        system=_SYSTEM_PROMPT,
    )

    answer, citations, confidence = _parse_reasoner_response(
        response.text,
        valid_packet_ids={p.packet_id for p in evidence.packets},
    )
    answer = _normalize_answer_shape(
        answer,
        answer_type=question.answer_type,
        domain=question.domain,
    )
    return (
        AnswerEvent(
            answer=answer,
            citations=citations,
            confidence=confidence,
            reasoning_summary=None,
        ),
        response,
    )


def _sample_variant_addendum(sample_variant: int) -> str:
    """Phase 3b (2026-05-14 sprint): per-sample prompt diversification.

    K-sample self-consistency on a low-temperature model often returns
    the same answer multiple times — no diversity, no gain. Each sample
    beyond variant 0 appends a short addendum that pushes the model to
    consider the question from a different angle, so the K samples land
    on genuinely independent reasoning paths.

    Variants (2026-05-15 expansion for K=3):
      0: baseline (no addendum)
      1: verbatim-grounding nudge — locate the exact span in a cited
         packet, match punctuation/spacing/units character-for-character.
      2: skeptical re-read — ask the model to articulate its
         confidence-bearing reasoning before answering, and to default
         to the more conservative (shorter / more concrete) value when
         two competing readings exist. Targets close-numeric
         estimation failures where the 'best guess' over multiple
         interpretations is the most concrete match.
      3+: cycles back to variant 0 (over-K just gets model stochasticity).
    """
    if sample_variant == 1:
        return (
            "\nBefore finalizing your answer, locate the exact span of text "
            "in at least one cited packet that supports your answer. If the "
            "exact span is not present, revise your answer to match the "
            "document's wording. Match the document's punctuation, spacing, "
            "and units verbatim.\n"
        )
    if sample_variant == 2:
        return (
            "\nBefore finalizing your answer, briefly enumerate the 1-3 "
            "concrete values you can read from the cited packets that "
            "could plausibly answer the question. Then pick the value "
            "that most directly satisfies the question's exact phrasing "
            "(matching units, time period, category, and any "
            "qualifiers). When two readings of a chart point are both "
            "plausible (e.g. '0.4' vs '0.5'), prefer the value closer "
            "to a labelled axis tick over the interpolated guess. "
            "Preserve the document's exact wording in your final "
            "answer.\n"
        )
    return ""


async def answer_from_evidence_k_samples(
    question: QuestionEvent,
    evidence: EvidenceEvent,
    *,
    backend_client: ModelClient,
    k: int = 1,
    escalation_hint: str | None = None,
    question_family: str | None = None,
) -> tuple[list[AnswerEvent], list[ModelResponse]]:
    """Phase 3b (2026-05-14 sprint): K=2 reasoner self-consistency.

    Runs `k` reasoner calls in parallel (asyncio.gather) with diversified
    prompt variants so each sample explores a different angle. Returns
    the parallel lists of AnswerEvent and ModelResponse, in the order
    of `sample_variant=0, 1, ..., k-1`.

    Caller is responsible for picking via `pick_best_answer`. Cost is
    `k * 1` reasoner calls; predicted +2-3pp on the n=148
    wrong_extraction_other bucket at k=2.
    """
    import asyncio

    if k <= 1:
        answer_event, response = await answer_from_evidence(
            question,
            evidence,
            backend_client=backend_client,
            escalation_hint=escalation_hint,
            question_family=question_family,
            sample_variant=0,
        )
        return [answer_event], [response]

    tasks = [
        answer_from_evidence(
            question,
            evidence,
            backend_client=backend_client,
            escalation_hint=escalation_hint,
            question_family=question_family,
            sample_variant=i,
        )
        for i in range(k)
    ]
    results = await asyncio.gather(*tasks)
    answer_events = [r[0] for r in results]
    responses = [r[1] for r in results]
    return answer_events, responses


def pick_best_answer(
    answer_events: list[AnswerEvent],
    *,
    answer_type: str | None,
) -> int:
    """Pick the best of K self-consistency samples. Returns the chosen index.

    Phase 3b v2 (2026-05-15 expansion): when K >= 3 and a majority of
    samples land on the SAME normalized answer (case + whitespace +
    surrounding punctuation collapsed), pick the first sample with that
    consensus answer. This catches close-numeric chart reads where the
    model produces e.g. ['0.4', '0.4', '0.5'] — pure heuristic picker
    might prefer the outlier on confidence, but the majority sample is
    almost always the right call.

    Falls back to the heuristic ordering (most-preferred first) when no
    consensus exists or K < 3:
      1. Non-Unanswerable beats Unanswerable.
      2. Citation count: more cited packets is better.
      3. For exact_match / numeric / boolean: shorter answer is better
         (the format hints all push for concise spans; a verbose sample
         is usually the model padding).
      4. Higher self-reported confidence.
      5. Sample index 0 (stable tie-break).
    """
    if not answer_events:
        raise ValueError("answer_events is empty")
    if len(answer_events) == 1:
        return 0

    # Phase 3b v2: majority-consensus shortcut for K >= 3.
    if len(answer_events) >= 3:
        consensus_idx = _consensus_pick(answer_events)
        if consensus_idx is not None:
            return consensus_idx

    stem = (str(answer_type).split(".")[-1].lower() if answer_type else "").strip()
    prefer_short = stem in {"exact_match", "numeric", "boolean", "multiple_choice"}

    def key(idx_event: tuple[int, AnswerEvent]):
        idx, ev = idx_event
        is_unanswerable = (ev.answer or "").strip().lower() in {
            "unanswerable",
            "unknown",
            "cannot determine",
            "can't determine",
            "",
        }
        n_citations = len(ev.citations or [])
        ans_len = len(ev.answer or "")
        # Sort key: lower is better.
        # - Unanswerable last (1 vs 0)
        # - More citations first (negate)
        # - Shorter first (only when prefer_short)
        # - Higher confidence first (negate)
        # - Lower index first (stable tie-break)
        return (
            1 if is_unanswerable else 0,
            -n_citations,
            ans_len if prefer_short else 0,
            -float(ev.confidence or 0.0),
            idx,
        )

    best_idx, _ = min(enumerate(answer_events), key=key)
    return best_idx


def _consensus_pick(answer_events: list[AnswerEvent]) -> int | None:
    """Phase 3b v2 (2026-05-15): majority-vote on normalized answers.

    Returns the index of the FIRST sample whose normalized answer is the
    majority across all K samples, or None if no answer has > K/2 votes.
    Excludes Unanswerable / empty answers from the vote — if the
    majority is Unanswerable, the heuristic fallback handles it
    (preferring any concrete sample).
    """
    from collections import Counter

    def normalize(s: str | None) -> str:
        if not s:
            return ""
        # Collapse whitespace + strip surrounding punctuation for vote-bucketing.
        normalized = " ".join(s.strip().split())
        # Lowercase only for vote bucketing — we still return the original
        # answer text from the chosen sample.
        return normalized.lower().strip(",.;:")

    normalized = [normalize(ev.answer) for ev in answer_events]
    counts = Counter(n for n in normalized if n and n not in {"unanswerable", "unknown"})
    if not counts:
        return None

    most_common, count = counts.most_common(1)[0]
    # Require a strict majority (> K/2). K=3 → need 2.
    if count <= len(answer_events) / 2:
        return None
    # Return the first sample whose normalized answer matches the majority.
    for idx, n in enumerate(normalized):
        if n == most_common:
            return idx
    return None


def _normalize_answer_shape(
    answer: str,
    *,
    answer_type: str | None,
    domain: str | None,
) -> str:
    """Apply scorer-compatible formatting fixes without using gold answers.

    These are deliberately syntax-level repairs for common document-QA answer
    shapes: accounting negatives, compact variable=value units, and page
    references. They are not semantic rewrites, and they stay gated by answer
    type/domain so they do not become a hidden benchmark-specific oracle.
    """
    text = " ".join(str(answer or "").strip().split())
    if not text:
        return text

    stem = _answer_type_stem(answer_type)
    domain_l = str(domain or "").lower()

    if stem == "boolean":
        boolean = _normalize_boolean_shape(text)
        if boolean:
            return boolean

    if stem == "numeric" and "finance" in domain_l:
        accounting = re.match(
            r"\$?\(\s*([-+]?\d+(?:,\d{3})*(?:\.\d+)?)\s*\)"
            r"\s*(?:million|billion|thousand)?\b",
            text,
            re.IGNORECASE,
        )
        if accounting:
            return "-" + accounting.group(1).replace(",", "")

    if stem in {"exact_match", "numeric"}:
        hex_value = _normalize_hex_value_shape(text)
        if hex_value:
            return hex_value

        min_typ_max = _normalize_min_typ_max_shape(text)
        if min_typ_max:
            return min_typ_max

        if stem == "exact_match" and "finance" in domain_l:
            value_status = _normalize_finance_value_status_shape(text)
            if value_status:
                return value_status

            corresponding_value = _normalize_corresponding_value_status_shape(text)
            if corresponding_value:
                return corresponding_value

        if stem == "exact_match" and "datasheet" in domain_l:
            file_size = _normalize_datasheet_file_size_shape(text)
            if file_size:
                return file_size

        variable_value = re.fullmatch(
            r"([A-Za-z][A-Za-z0-9_]{0,12})\s*=\s*"
            r"(-?\d+(?:\.\d+)?)\s*([A-Za-zµμ%]{1,6})",
            text,
        )
        if variable_value:
            return (
                f"{variable_value.group(1)} = {variable_value.group(2)} {variable_value.group(3)}"
            )

    if stem == "exact_match":
        identifier = _normalize_leading_code_identifier_shape(text)
        if identifier:
            return identifier

        page_ref = re.fullmatch(
            r"(.+?)\s+on\s+page\s+([A-Za-z0-9][A-Za-z0-9.\-]*)",
            text,
            re.IGNORECASE,
        )
        if page_ref:
            return f"{page_ref.group(1)}; page {page_ref.group(2)}"

    return text


def _answer_type_stem(answer_type: str | None) -> str:
    s = str(answer_type or "").strip()
    return s.split(".")[-1].lower() if "." in s else s.lower()


def _normalize_boolean_shape(text: str) -> str | None:
    boolean = re.match(
        r"^(?:the\s+answer\s+is\s+)?(?P<value>yes|no|true|false)\b",
        text,
        re.IGNORECASE,
    )
    if not boolean:
        return None
    value = boolean.group("value").lower()
    return "yes" if value in {"yes", "true"} else "no"


def _normalize_hex_value_shape(text: str) -> str | None:
    """Normalize a single OCR-ish hex value after a label prefix.

    This is intentionally narrow: it only returns the hex span when it is the
    whole answer or follows a label-like semicolon/colon prefix. That keeps
    register phrases such as "r0 (0x5)" intact while still removing verbose
    labels like "Serializer Lanes Enabled; OxFF (...)".
    """
    matches = list(
        re.finditer(
            r"(?<![A-Za-z0-9])(?P<prefix>[0Oo])x(?P<digits>[0-9A-Fa-f]+)"
            r"(?P<context>\s*\([^)]{0,120}\))?",
            text,
        )
    )
    if len(matches) != 1:
        return None

    match = matches[0]
    prefix_text = text[: match.start()].strip()
    if prefix_text and not prefix_text.endswith((";", ":")):
        return None

    suffix_text = text[match.end() :].strip()
    if suffix_text and suffix_text[0] not in ",;.":
        return None

    digits = match.group("digits").upper()
    context = match.group("context") or ""
    if context:
        context = _normalize_terminal_o_digit_in_identifier(context)
    return f"0x{digits}{context}"


def _normalize_terminal_o_digit_in_identifier(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        token = match.group(0)
        prefix = token[:-1]
        sibling_digit = re.search(rf"\b{re.escape(prefix)}\d+\b", text, re.IGNORECASE)
        if sibling_digit:
            return f"{prefix}0"
        return token

    return re.sub(r"\b[A-Za-z][A-Za-z0-9_]*[Oo]\b", repl, text)


def _normalize_leading_code_identifier_shape(text: str) -> str | None:
    leading = re.match(
        r"^(?P<identifier>[A-Z][A-Z0-9]*(?:[ _-]+[A-Z0-9]*[0-9][A-Z0-9]*)*)"
        r"[.;]\s+.+$",
        text,
    )
    if not leading:
        return None

    identifier = leading.group("identifier").strip(" _-")
    if not any(ch.isdigit() for ch in identifier):
        return None
    return re.sub(r"[ -]+", "_", identifier)


def _normalize_corresponding_value_status_shape(text: str) -> str | None:
    """Collapse verbose finance table prose into ``value; status``.

    This targets answers where the model names the setup row, then says the
    corresponding measure was a value and also states whether that value is
    typical/min/max. The regex anchors on the corresponding-value clause so
    earlier distractor numbers in the explanation are ignored.
    """

    value = r"\$?\(?[-+]?\d+(?:,\d{3})*(?:\.\d+)?\)?%?"
    match = re.search(
        rf"\bcorresponding\b.{{0,160}}?\b(?:was|is|equals?|=)\s*(?P<value>{value})"
        r"(?P<tail>[^.?!]{0,220})",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None

    status_match = re.search(
        r"\b(?P<status>typical|middle|minimum|maximum|lowest|highest|smallest|largest|min|max)\b",
        match.group("tail"),
        re.IGNORECASE,
    )
    if not status_match:
        return None

    status = _canonical_finance_status(status_match.group("status"))

    return f"{_normalize_finance_exact_value(match.group('value'))}; {status}"


def _normalize_finance_value_status_shape(text: str) -> str | None:
    value = r"\$?\s*\(?[-+]?\d+(?:,\d{3})*(?:\.\d+)?\)?%?"
    status = r"typical|middle|minimum|maximum|lowest|highest|smallest|largest|min|max"
    match = re.fullmatch(
        rf"(?P<value>{value})\s*(?:[,;/]|\band\b)\s*(?:the\s+)?(?P<status>{status})",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    return (
        f"{_normalize_finance_exact_value(match.group('value'))}; "
        f"{_canonical_finance_status(match.group('status'))}"
    )


def _canonical_finance_status(text: str) -> str:
    status = str(text or "").strip().lower()
    return {
        "middle": "typical",
        "lowest": "minimum",
        "smallest": "minimum",
        "min": "minimum",
        "highest": "maximum",
        "largest": "maximum",
        "max": "maximum",
    }.get(status, status)


def _normalize_finance_exact_value(text: str) -> str:
    value = str(text or "").strip().rstrip(",;.")
    value = re.sub(r"^\$\s*", "", value)
    accounting = re.fullmatch(r"\(\s*([-+]?\d+(?:,\d{3})*(?:\.\d+)?)\s*\)", value)
    if accounting:
        return f"-{accounting.group(1)}"
    return value


def _normalize_datasheet_file_size_shape(text: str) -> str | None:
    file_name = r"[A-Za-z0-9_.-]+\.(?:bin|elf|fw|hex|img)"
    size = r"\d+(?:\.\d+)?\s*(?:b|bytes?|kb|kib|mb|mib|gb|gib)"
    match = re.match(
        rf"^(?P<file>{file_name})\s*[,;]\s*(?P<size>{size})(?P<tail>.*)$",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None

    tail = match.group("tail").strip()
    if tail and not re.match(r"^[,;]\s*state\b", tail, re.IGNORECASE):
        return None
    size_text = re.sub(r"\s+", " ", match.group("size").strip())
    return f"{match.group('file')}, {size_text}"


def _normalize_min_typ_max_shape(text: str) -> str | None:
    value = r"[-+]?\d+(?:\.\d+)?\s*[A-Za-zµμ%]{0,8}"
    pattern = re.fullmatch(
        rf"min(?:imum)?\s*[:=]?\s*(?P<min>{value})\s*[,;/ ]+\s*"
        rf"typ(?:ical)?\s*[:=]?\s*(?P<typ>{value})\s*[,;/ ]+\s*"
        rf"max(?:imum)?\s*[:=]?\s*(?P<max>{value})",
        text,
        re.IGNORECASE,
    )
    if not pattern:
        return None

    def fmt(raw: str) -> str:
        return re.sub(r"(?<=\d)\s*([A-Za-zµμ%]+)$", r" \1", raw.strip())

    return f"min: {fmt(pattern.group('min'))}, typ: {fmt(pattern.group('typ'))}, max: {fmt(pattern.group('max'))}"


def _render_packet_line(packet, *, question_text: str | None = None) -> str:
    """One descriptor line for a packet in the reasoner's prompt.

    Sprint Phase 2: multi_scale_crops annotation tells the reasoner how
    many image scales it will see (tight + context).
    Sprint Phase 3: when chart_csv is populated, the reasoner sees a
    code-fenced CSV block beneath the descriptor so axis-value
    interpolation questions land on hard data instead of guesses.
    Path A (2026-05-06): when expand_context attached neighbors, list
    their roles ("caption, footnote, ...") so the reasoner knows which
    images that follow are primary focus vs context. The selective context
    follow-up keeps header-like neighbors text-only once OCR/text has
    already been appended to the packet.
    """
    base = f"- {packet.packet_id}: page {packet.page}, bbox {packet.bbox_norm}"
    n_scales = len(packet.multi_scale_crops)
    if n_scales >= 2:
        base += (
            f" — {n_scales} image scales in order: "
            f"{_format_scale_summary(packet.multi_scale_crops)}"
        )
        if any(c.scale == "chart_context" for c in packet.multi_scale_crops):
            base += (
                "\n  Chart context crop: use this wider crop for axes, legends, "
                "and curve geometry when visually reading chart values."
            )
    image_neighbor_roles, text_only_neighbor_roles = _linked_neighbor_roles_by_delivery(packet)
    if image_neighbor_roles:
        types = ", ".join(image_neighbor_roles)
        n_neighbors = len(image_neighbor_roles)
        base += f"\n  Attached neighbor images ({n_neighbors}): {types}"
        if "context-window" in {_normalize_neighbor_role(t) for t in image_neighbor_roles}:
            base += (
                "\n  Context window: this attached image is a wider crop around "
                "the same packet; use it for axes, gridlines, labels, and "
                "row/column headers that may be just outside the tight bbox."
            )
    if text_only_neighbor_roles:
        contexts = _text_only_neighbor_contexts(packet, text_only_neighbor_roles)
        if contexts:
            joined = "; ".join(f"{role}={_quote_context_text(text)}" for role, text in contexts)
        else:
            joined = ", ".join(text_only_neighbor_roles)
        base += f"\n  Attached text-only context ({len(text_only_neighbor_roles)}): {joined}"
    text_snippet = _packet_text_snippet(packet, question_text=question_text)
    if text_snippet:
        base += f"\n  Extracted text: {text_snippet!r}"
    if packet.chart_csv:
        conf = packet.chart_extraction_confidence
        conf_str = f" (confidence={conf:.2f})" if conf is not None else ""
        base += (
            f"\n  Chart extraction{conf_str} — treat as advisory; "
            "verify against the crop:\n  ```csv\n  "
            + "\n  ".join(packet.chart_csv.splitlines())
            + "\n  ```"
        )
    return base


def _format_scale_summary(crops) -> str:
    return ", ".join(f"{c.scale} {_format_bbox(c.bbox_norm)}" for c in crops)


def _format_bbox(bbox: tuple[float, float, float, float]) -> str:
    return "[" + ", ".join(f"{v:.3f}" for v in bbox) + "]"


def _packet_text_snippet(packet, *, question_text: str | None = None) -> str:
    """Compact packet text/OCR for the reasoner descriptor line."""
    snippet = packet.text_layer_snippet or packet.ocr_snippet or ""
    snippet = _question_focused_text(str(snippet), question_text=question_text)
    snippet = " ".join(snippet.split())
    if len(snippet) > _MAX_PACKET_TEXT_CHARS:
        snippet = snippet[: _MAX_PACKET_TEXT_CHARS - 3] + "..."
    return snippet


def _question_focused_text(text: str, *, question_text: str | None = None) -> str:
    """Prefer question-matching table rows over the first rows of a long packet.

    PDF text extraction for a large table can span thousands of characters. A
    blind prefix truncation over-represents the first rows, which can lure the
    VLM toward an answer that satisfies only a nearby-looking subset of the
    question. Keep the legacy prefix when no question terms match; otherwise
    surface the highest-overlap lines plus their immediate row continuations.
    """
    if not text or not question_text or len(text) <= _MAX_PACKET_TEXT_CHARS:
        return text
    q_tokens = _focus_tokens(question_text)
    if not q_tokens:
        return text

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    scored: list[tuple[int, int]] = []
    for idx, line in enumerate(lines):
        overlap = len(q_tokens & _focus_tokens(line))
        if overlap:
            scored.append((overlap, idx))
    if not scored:
        return text

    max_score = max(score for score, _idx in scored)
    score_floor = max(1, max_score - 1)
    selected_indexes: set[int] = set()
    for _score, idx in [
        item
        for item in sorted(scored, key=lambda item: (-item[0], item[1]))
        if item[0] >= score_floor
    ][:3]:
        selected_indexes.update({idx - 1, idx, idx + 1})
    selected = [lines[idx] for idx in sorted(selected_indexes) if 0 <= idx < len(lines)]
    return " / ".join(selected)


def _focus_tokens(text: str) -> set[str]:
    tokens = set(re.findall(r"[a-z0-9]+", text.lower()))
    return {tok for tok in tokens if len(tok) > 1 and tok not in _FOCUS_STOPWORDS}


def _linked_neighbor_roles_by_delivery(packet) -> tuple[list[str], list[str]]:
    """Return (image_roles, text_only_roles) aligned with non-empty linked refs."""
    context_by_role = _packet_context_by_role(packet)
    image_roles: list[str] = []
    text_only_roles: list[str] = []
    neighbor_types = packet.linked_neighbor_types or []
    for idx, ref in enumerate(packet.linked_crop_refs or []):
        if not ref:
            continue
        role = neighbor_types[idx] if idx < len(neighbor_types) else "unknown"
        if _should_deliver_neighbor_as_text_only(role, context_by_role):
            text_only_roles.append(role)
        else:
            image_roles.append(role)
    return image_roles, text_only_roles


def _linked_neighbor_image_refs(packet) -> list[str]:
    """Linked crop refs that should still be sent as images to the reasoner.

    Expand can attach neighbors for two different purposes:
    - visual context that the VLM must inspect (captions/footnotes/charts/legends)
    - deterministic text context already extracted into `Context [role]: ...`

    Header-like context is often enough as text and was a notable source of
    image bloat in +4 runs. Keep those refs on the packet for traceability, but
    avoid sending their crop images once the text is present.
    """
    context_by_role = _packet_context_by_role(packet)
    neighbor_types = packet.linked_neighbor_types or []
    image_refs: list[str] = []
    for idx, ref in enumerate(packet.linked_crop_refs or []):
        if not ref:
            continue
        role = neighbor_types[idx] if idx < len(neighbor_types) else "unknown"
        if _should_deliver_neighbor_as_text_only(role, context_by_role):
            continue
        image_refs.append(ref)
    return image_refs


def _should_deliver_neighbor_as_text_only(role: str, context_by_role: dict[str, list[str]]) -> bool:
    normalized = _normalize_neighbor_role(role)
    return normalized in _TEXT_ONLY_NEIGHBOR_TYPES and bool(context_by_role.get(normalized))


def _packet_context_by_role(packet) -> dict[str, list[str]]:
    """Parse `Context [role]: text` snippets appended by expand_context."""
    context_by_role: dict[str, list[str]] = {}
    for snippet in (packet.text_layer_snippet, packet.ocr_snippet):
        for line in (snippet or "").splitlines():
            match = _CONTEXT_LINE_RE.match(line.strip())
            if not match:
                continue
            role = _normalize_neighbor_role(match.group("role"))
            text = " ".join(match.group("text").split())
            if text:
                context_by_role.setdefault(role, []).append(text)
    return context_by_role


def _text_only_neighbor_contexts(packet, roles: list[str]) -> list[tuple[str, str]]:
    context_by_role = _packet_context_by_role(packet)
    contexts: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for role in roles:
        normalized = _normalize_neighbor_role(role)
        for text in context_by_role.get(normalized, []):
            key = (normalized, text.casefold())
            if key in seen:
                continue
            seen.add(key)
            contexts.append((role, text))
            break
    return contexts


def _quote_context_text(text: str) -> str:
    text = " ".join(text.split())
    if len(text) > _MAX_TEXT_ONLY_CONTEXT_CHARS:
        text = text[: _MAX_TEXT_ONLY_CONTEXT_CHARS - 3].rstrip() + "..."
    return repr(text)


def _normalize_neighbor_role(role: str) -> str:
    return str(role).strip().lower().replace("_", "-")


def _collect_packet_images(evidence: EvidenceEvent) -> list[Path]:
    """Gather unique crop_ref paths in packet order.

    Packets can share a page image (multiple bboxes on the same page). We
    deduplicate while preserving order so the reasoner doesn't see redundant
    attachments.

    Sprint Phase 2 (2026-05-04, Phase 6 #6): when a packet has
    `multi_scale_crops` populated (tight + context), enumerate every
    scale's ref. Falls back to the legacy local_crop_ref / page_thumbnail
    chain for packets without multi-scale.

    Path A (2026-05-06): after the primary crop(s), enumerate the packet's
    `linked_crop_refs` (neighbors attached by `expand_context` — captions,
    footnotes, section headers, etc.). Pre-Path-A, these were populated
    on the packet but never reached the reasoner. The 2026-05-06 memory
    entry documents the dead-code finding that motivated this change.

    Selective context follow-up: header-like linked crops that already have
    extracted `Context [role]: ...` text stay traceable on the packet but do
    not get sent as extra reasoner images.
    """
    seen: set[str] = set()
    images: list[Path] = []
    for p in evidence.packets:
        if p.multi_scale_crops:
            for scaled in p.multi_scale_crops:
                ref = scaled.ref
                if not ref or ref in seen:
                    continue
                seen.add(ref)
                images.append(Path(ref))
        else:
            ref = p.local_crop_ref or p.page_thumbnail_ref
            if ref and ref not in seen:
                seen.add(ref)
                images.append(Path(ref))
        # Linked neighbor crops follow the primary crop(s) so the prompt
        # ordering matches "primary first, then context."
        for neighbor_ref in _linked_neighbor_image_refs(p):
            if not neighbor_ref or neighbor_ref in seen:
                continue
            seen.add(neighbor_ref)
            images.append(Path(neighbor_ref))
    return images


def _parse_reasoner_response(
    text: str,
    *,
    valid_packet_ids: set[str],
) -> tuple[str, list[str], float]:
    """Extract (answer, citations, confidence). Tolerant of fence / prefix noise."""
    if not text:
        return "", [], 0.0

    candidate = text.strip()
    fence = _JSON_FENCE_RE.search(candidate)
    if fence:
        candidate = fence.group(1)
    else:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = candidate[start : end + 1]

    try:
        obj = json.loads(candidate)
    except json.JSONDecodeError:
        return text.strip(), [], 0.0

    if not isinstance(obj, dict):
        return text.strip(), [], 0.0

    answer = obj.get("answer", "")
    if not isinstance(answer, str):
        answer = str(answer)
    answer = _canonicalize_bit_field_assignments(answer)

    raw_citations = obj.get("citations", []) or []
    citations = [c for c in raw_citations if isinstance(c, str) and c in valid_packet_ids]

    confidence_raw = obj.get("confidence", 0.5)
    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))

    return answer, citations, confidence


def _canonicalize_bit_field_assignments(answer: str) -> str:
    """Normalize terse register bit-field answers without touching prose."""
    matches = list(_BIT_ASSIGNMENT_RE.finditer(answer))
    if len(matches) < 2:
        return answer
    residual = _BIT_ASSIGNMENT_RE.sub("", answer)
    residual = re.sub(r"[\s,;]+", "", residual)
    if residual:
        return answer
    return ", ".join(f"[{match.group('bits')}]={match.group('value').lower()}" for match in matches)
