"""Gold-free answer-shape contracts for post-evidence verification.

The contract is inferred only from the question, domain, answer type, and
planner family. It deliberately avoids gold answers and example ids.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class AnswerContract:
    """Question-derived constraints the final answer must satisfy."""

    requires_multi_field: bool = False
    requires_min_typ_max: bool = False
    requires_quantitative_value: bool = False
    requires_visual_explanation: bool = False
    row_disambiguation_cues: tuple[str, ...] = ()
    requires_corresponding_row_binding: bool = False
    checkbox_binding_required: bool = False
    chart_binding_required: bool = False


_VALUE_TOKEN_RE = re.compile(
    r"""
    (?:
        \$?\(?-?\d+(?:,\d{3})*(?:\.\d+)?\)?%?
        |0x[0-9a-f]+
        |b[01x]+
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)
_WORD_RE = re.compile(r"[a-z0-9_]+", re.IGNORECASE)
_UNIT_ONLY_RE = re.compile(r"^[a-zµμ%/]+$", re.IGNORECASE)
_MIN_TYP_MAX_RE = re.compile(
    r"\b(?:min\s*/\s*typ\s*/\s*max|min\s*,\s*typ\s*,?\s*(?:or\s+)?max|"
    r"minimum\s*,\s*typical\s*,?\s*(?:or\s+)?maximum|typ(?:ical)?)\b",
    re.IGNORECASE,
)
_QUANTITATIVE_QUESTION_RE = re.compile(
    r"\b(?:which|what)\s+(?:specific\s+)?"
    r"(?:value|rating|voltage|current|percentage|percent|amount|count|number|energy)\b"
    r"|\b(?:value|rating|voltage|current|percentage|percent|amount|count|energy)\s+"
    r"(?:should|must|is|was|were|to)\b",
    re.IGNORECASE,
)
_MULTI_FIELD_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:both|two|three|all)\b", re.IGNORECASE),
    re.compile(r"\band\s+(?:what|which|how|why|the corresponding|corresponding)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:label|function|parameter|part number|row|value)\b.{0,80}"
        r"\band\s+(?:unit|value|package|voltage|current|condition|reason|cue|context)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:explain|include)\b.{0,80}\b(?:cue|cues|reason|context|condition)\b", re.IGNORECASE
    ),
)
_VISUAL_EXPLANATION_RE = re.compile(
    r"\b(?:explain|how\s+(?:does|is|was|do|did)|visual(?:ly)?|cue|cues|"
    r"indicat(?:e|ed|es|ing)|confirm(?:ed|s|ing)?|diagram)\b",
    re.IGNORECASE,
)
_ROW_CUE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("lowest", re.compile(r"\blowest\b", re.IGNORECASE)),
    ("highest", re.compile(r"\bhighest\b", re.IGNORECASE)),
    ("among", re.compile(r"\bamong\b", re.IGNORECASE)),
    ("corresponding", re.compile(r"\bcorresponding\b", re.IGNORECASE)),
    ("compare", re.compile(r"\bcompar(?:e|ing|ison)\b", re.IGNORECASE)),
    ("visually_similar", re.compile(r"\bvisually\s+similar\b", re.IGNORECASE)),
    ("min_typ_max", _MIN_TYP_MAX_RE),
    ("part_number", re.compile(r"\bpart\s+number\b", re.IGNORECASE)),
    ("row", re.compile(r"\brow\b", re.IGNORECASE)),
    ("condition", re.compile(r"\bcondition\b", re.IGNORECASE)),
    ("value", re.compile(r"\bvalue\b", re.IGNORECASE)),
)
_CORRESPONDING_ROW_BINDING_RE = re.compile(
    r"\bfor\s+the\s+(?:year|period|quarter|row|item|entity|metric|series)\s+in\s+which\b"
    r"|\breached\s+(?:its|their|the)?\s*(?:minimum|maximum|lowest|highest|largest|smallest)\b",
    re.IGNORECASE,
)
_CORRESPONDING_OUTPUT_RE = re.compile(r"\bcorresponding\b", re.IGNORECASE)
_CHECKBOX_BINDING_RE = re.compile(
    r"\b(?:check\s*marks?|check\s+boxes|checkbox(?:es)?|checked|large\s+accelerated\s+filer|"
    r"filed\s+all\s+required\s+reports|yes\s*/\s*no\s+checkbox(?:es)?)\b",
    re.IGNORECASE,
)
_CHART_BINDING_RE = re.compile(
    r"\b(?:chart|legend|series|panel|caption|axis|axes|curve|line|bar|exhibit|figure|marker)\b",
    re.IGNORECASE,
)
_CHART_FAMILY_RE = re.compile(r"(?:chart|legend|axis|curve|caption|figure|panel|series)")


def build_answer_contract(
    question_text: str | None,
    *,
    answer_type: str | None = None,
    domain: str | None = None,
    question_family: str | None = None,
) -> AnswerContract:
    """Infer answer-shape constraints from question metadata only."""

    question = str(question_text or "")
    family = str(question_family or "").lower()
    domain_l = str(domain or "").lower()
    answer_stem = str(answer_type or "").split(".")[-1].lower()
    requires_min_typ_max = bool(_MIN_TYP_MAX_RE.search(question))
    requires_multi_field = requires_min_typ_max or any(
        pattern.search(question) for pattern in _MULTI_FIELD_PATTERNS
    )
    if answer_stem == "boolean":
        requires_multi_field = False
    if answer_stem == "numeric" and not requires_min_typ_max:
        requires_multi_field = False
    requires_visual_explanation = bool(_VISUAL_EXPLANATION_RE.search(question)) and bool(
        re.search(
            r"\b(?:cue|cues|diagram|explain|how\s+(?:does|is|was|do|did)|"
            r"indicat(?:e|ed|es|ing)|confirm(?:ed|s|ing)?|using both)\b",
            question,
            re.I,
        )
    )
    requires_quantitative_value = _requires_quantitative_value(question, answer_type)
    row_cues = tuple(name for name, pattern in _ROW_CUE_PATTERNS if pattern.search(question))
    requires_corresponding_row_binding = bool(_CORRESPONDING_OUTPUT_RE.search(question)) and (
        bool(_CORRESPONDING_ROW_BINDING_RE.search(question))
        or bool(
            re.search(r"\b(?:among|min(?:imum)?|max(?:imum)?|lowest|highest)\b", question, re.I)
        )
    )
    checkbox_binding_required = bool(_CHECKBOX_BINDING_RE.search(question))
    chart_binding_required = bool(_CHART_BINDING_RE.search(question)) or bool(
        _CHART_FAMILY_RE.search(family)
    )
    # Finance chart questions often omit the word "chart" once the family has
    # classified them; keep this as a prompt-level binding cue, not a hard fail.
    if "finance" in domain_l and any(token in family for token in ("caption", "axis", "curve")):
        chart_binding_required = True

    return AnswerContract(
        requires_multi_field=requires_multi_field,
        requires_min_typ_max=requires_min_typ_max,
        requires_quantitative_value=requires_quantitative_value,
        requires_visual_explanation=requires_visual_explanation,
        row_disambiguation_cues=row_cues,
        requires_corresponding_row_binding=requires_corresponding_row_binding,
        checkbox_binding_required=checkbox_binding_required,
        chart_binding_required=chart_binding_required,
    )


def render_answer_contract(contract: AnswerContract) -> str:
    """Render a compact verifier/reasoner instruction block."""

    lines: list[str] = []
    if contract.requires_multi_field:
        lines.append("include every field requested by the question, not only the first scalar")
    if contract.requires_min_typ_max:
        lines.append("preserve the requested min/typ/max label and its corresponding value/unit")
    if contract.requires_quantitative_value:
        lines.append("answer with the requested value/rating/amount, not only the row label")
    if contract.requires_visual_explanation:
        lines.append("include the requested visual cue or explanation, not just the label")
    if contract.row_disambiguation_cues:
        lines.append(
            "verify the exact table row/entity; disambiguation cues="
            + ", ".join(contract.row_disambiguation_cues)
        )
    if contract.requires_corresponding_row_binding:
        lines.append(
            "for corresponding-value questions, first bind the source row/year/entity, "
            "then read the requested output from that same row"
        )
    if contract.checkbox_binding_required:
        lines.append(
            "bind each checkbox/check mark to the nearest Yes/No or status label before answering"
        )
    if contract.chart_binding_required:
        lines.append(
            "bind the answer to the correct chart series, legend, panel, caption, and axes"
        )
    if not lines:
        return "No extra answer-shape constraints inferred beyond exact support."
    return "\n".join(f"- {line}." for line in lines)


def answer_contract_failures(answer: str | None, contract: AnswerContract) -> list[str]:
    """Return severe contract failures that should block verifier acceptance."""

    text = " ".join(str(answer or "").strip().split())
    if not text or _looks_unanswerable(text):
        return []

    failures: list[str] = []
    if (contract.requires_min_typ_max and not _has_min_typ_max_label_and_value(text)) or (
        not contract.requires_min_typ_max
        and contract.requires_multi_field
        and _looks_too_short_for_multi_field(text)
    ):
        failures.append("missing_field")

    if contract.requires_quantitative_value and not _has_value_token(text):
        failures.append("label_value_mismatch")

    if contract.requires_visual_explanation and _looks_too_short_for_visual_explanation(text):
        failures.append("missing_field")

    return _dedupe_preserve_order(failures)


def answer_contract_diagnostics(contract: AnswerContract) -> dict[str, list[str]]:
    """Non-failing diagnostics useful for traces and repair hints."""

    diagnostics: dict[str, list[str]] = {}
    if contract.row_disambiguation_cues:
        diagnostics["row_disambiguation_cues"] = list(contract.row_disambiguation_cues)
    if contract.requires_corresponding_row_binding:
        diagnostics["corresponding_row_binding_cues"] = ["source_row", "output_field"]
    if contract.checkbox_binding_required:
        diagnostics["checkbox_binding_cues"] = ["check_mark", "nearest_label"]
    if contract.chart_binding_required:
        diagnostics["chart_binding_cues"] = ["series", "legend", "panel", "caption", "axis"]
    return diagnostics


def answer_contract_risks(contract: AnswerContract) -> list[str]:
    """Return non-fatal ambiguity risks inferred from the contract."""

    risks: list[str] = []
    if contract.row_disambiguation_cues:
        risks.append("wrong_row_risk")
    if contract.requires_corresponding_row_binding and "wrong_row_risk" not in risks:
        risks.append("wrong_row_risk")
    if contract.checkbox_binding_required:
        risks.append("checkbox_binding_risk")
    if contract.chart_binding_required:
        risks.append("legend_binding_risk")
    return risks


def _requires_quantitative_value(question: str, answer_type: str | None) -> bool:
    stem = str(answer_type or "").split(".")[-1].lower()
    if stem == "numeric":
        return True
    if "unit" in question.lower() and "which" in question.lower():
        return False
    return bool(_QUANTITATIVE_QUESTION_RE.search(question))


def _has_value_token(text: str) -> bool:
    return bool(_VALUE_TOKEN_RE.search(text))


def _has_min_typ_max_label_and_value(text: str) -> bool:
    normalized = text.lower()
    has_label = bool(re.search(r"\b(?:min(?:imum)?|typ(?:ical)?|max(?:imum)?)\b", normalized))
    return has_label and _has_value_token(text)


def _looks_too_short_for_multi_field(text: str) -> bool:
    if ";" in text or "," in text or re.search(r"\b(?:and|with|plus)\b", text, re.I):
        return False
    value_tokens = _VALUE_TOKEN_RE.findall(text)
    words = _semantic_words(text)
    if len(value_tokens) <= 1 and len(words) <= 3:
        return True
    return len(words) <= 2


def _looks_too_short_for_visual_explanation(text: str) -> bool:
    if ("," in text or ";" in text) and _has_structured_file_size_pair(text):
        return False
    words = [
        word
        for word in _WORD_RE.findall(text)
        if not _VALUE_TOKEN_RE.fullmatch(word)
        and word.lower() not in {"the", "a", "an", "of", "to"}
    ]
    if len(words) < 5:
        return True
    has_visible_chart_label = bool(re.search(r"\b[A-Z][A-Z0-9]+(?:[ -][A-Z0-9]+)+\b", text))
    explanatory_terms = {
        "off",
        "on",
        "path",
        "wireless",
        "adapter",
        "supplied",
        "shows",
        "indicates",
        "arrow",
        "arrows",
        "caption",
        "chart",
        "figure",
        "label",
        "legend",
        "line",
        "region",
        "regions",
        "shown",
        "visual",
        "visually",
        "connected",
        "through",
    }
    return not has_visible_chart_label and not any(
        word.lower() in explanatory_terms for word in words
    )


def _has_structured_file_size_pair(text: str) -> bool:
    return bool(
        re.search(r"\b[\w.-]+\.(?:bin|elf|fw|hex|img)\b", text, re.IGNORECASE)
        and re.search(
            r"\b\d+(?:\.\d+)?\s*(?:b|bytes?|kb|kib|mb|mib|gb|gib)\b",
            text,
            re.IGNORECASE,
        )
    )


def _semantic_words(text: str) -> list[str]:
    words = _WORD_RE.findall(text)
    return [
        word
        for word in words
        if not _VALUE_TOKEN_RE.fullmatch(word)
        and not _UNIT_ONLY_RE.fullmatch(word)
        and word.lower() not in {"the", "a", "an", "of", "to"}
    ]


def _looks_unanswerable(text: str) -> bool:
    return text.strip().lower() in {
        "unanswerable",
        "unknown",
        "cannot determine",
        "can't determine",
    }


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped
