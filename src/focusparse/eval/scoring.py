"""Scoring — wraps parser-bench's scorer where possible, adds FocusParse-specific
metrics (most importantly `score_evidence_reward`, the lazy-answer penalty).

`score_answer`, `_bbox_iou`, `page_recall` are duplicated here in pure-python
form so FocusParse can run even if the submodule hasn't imported them yet.
They are **semantically** compatible with parser-bench's scorer so the
reproducibility gate (simple agent within ±1 pt of published numbers) holds.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from focusparse._parser_bench import BBox, BenchmarkExample


# ---------------------------------------------------------------------------
# Answer scoring
# ---------------------------------------------------------------------------

def score_answer(prediction_text: str, example: "BenchmarkExample") -> float:
    """Return 1.0 if the prediction matches the gold answer under the example's
    answer_type tolerance, else 0.0."""
    gold = (example.answer or "").strip()
    pred = (prediction_text or "").strip()

    answer_type = str(example.answer_type)
    # Unanswerable — correct iff the model abstains with a recognizable signal.
    if answer_type.endswith("unanswerable"):
        return 1.0 if _is_abstention(pred) else 0.0

    if answer_type.endswith("boolean"):
        return 1.0 if _normalize_bool(pred) == _normalize_bool(gold) else 0.0

    if answer_type.endswith("multiple_choice"):
        return 1.0 if pred.strip().upper()[:1] == gold.strip().upper()[:1] else 0.0

    if answer_type.endswith("numeric"):
        return _score_numeric(pred, gold, example.tolerance)

    # exact_match (fall-through)
    return 1.0 if pred.casefold() == gold.casefold() else 0.0


def _is_abstention(text: str) -> bool:
    lowered = text.lower()
    return any(
        kw in lowered
        for kw in ("unanswerable", "cannot be determined", "not enough information", "n/a")
    )


def _normalize_bool(text: str) -> str | None:
    t = text.strip().lower()
    if t in ("true", "yes", "y", "1"):
        return "true"
    if t in ("false", "no", "n", "0"):
        return "false"
    return None


def _score_numeric(pred: str, gold: str, tolerance: float | None) -> float:
    p = _extract_float(pred)
    g = _extract_float(gold)
    if p is None or g is None:
        return 0.0
    tol = tolerance if tolerance is not None else 0.01
    if abs(g) < 1e-9:
        return 1.0 if abs(p - g) <= tol else 0.0
    return 1.0 if abs(p - g) / max(abs(g), 1e-9) <= tol else 0.0


def _extract_float(text: str) -> float | None:
    import re
    m = re.search(r"-?\d+(?:\.\d+)?", text)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Localization scoring
# ---------------------------------------------------------------------------

def _bbox_iou(a: "BBox", b: "BBox") -> float:
    if a.page != b.page:
        return 0.0
    x0 = max(a.x0, b.x0)
    y0 = max(a.y0, b.y0)
    x1 = min(a.x1, b.x1)
    y1 = min(a.y1, b.y1)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    inter = (x1 - x0) * (y1 - y0)
    area_a = max(0.0, (a.x1 - a.x0) * (a.y1 - a.y0))
    area_b = max(0.0, (b.x1 - b.x0) * (b.y1 - b.y0))
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def page_recall(predicted_pages: list[int], gold_pages: list[int]) -> float:
    if not gold_pages:
        return 1.0
    pred = set(predicted_pages)
    gold = set(gold_pages)
    return len(pred & gold) / len(gold)


def max_iou_over_alternates(
    predicted_bboxes: list["BBox"],
    example: "BenchmarkExample",
) -> float:
    """Best IoU between any predicted bbox and any gold-or-alternate bbox."""
    from focusparse._parser_bench import BBox  # noqa: F401 — type only

    golds = list(example.supporting_bboxes) + list(example.alternate_bboxes)
    if not predicted_bboxes or not golds:
        return 0.0
    best = 0.0
    for p in predicted_bboxes:
        for g in golds:
            iou = _bbox_iou(p, g)
            if iou > best:
                best = iou
    return best


# ---------------------------------------------------------------------------
# Evidence-reward (lazy-answer penalty)
# ---------------------------------------------------------------------------

def score_evidence_reward(
    *,
    prediction_text: str,
    predicted_pages: list[int],
    predicted_bboxes: list["BBox"],
    tool_calls: list[dict[str, Any]],
    example: "BenchmarkExample",
    largest_crop_area_ratio: float = 0.0,
) -> float:
    """Evidence-grounded reward ∈ [0, 1].

    Zero iff the model answered without calling any tool, or without predicting
    any bbox — the "lazy correct" case. Otherwise, multiplicative combination of
    answer correctness × page recall × best IoU, minus a penalty for crops that
    are essentially the whole page (AgenticOCR-style "lazy full-page" flag).
    """
    if len(tool_calls) == 0 or len(predicted_bboxes) == 0:
        return 0.0
    answer = score_answer(prediction_text, example)
    pages = page_recall(predicted_pages, [b.page for b in example.supporting_bboxes])
    iou = max_iou_over_alternates(predicted_bboxes, example)
    lazy_penalty = 0.2 if largest_crop_area_ratio > 0.6 else 0.0
    reward = answer * pages * iou - lazy_penalty
    return max(0.0, min(1.0, reward))
