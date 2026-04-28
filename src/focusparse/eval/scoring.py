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


def _answer_type_stem(answer_type: object) -> str:
    """Normalize answer_type to a lowercase stem regardless of repr form.

    Accepts the parser-bench `AnswerType` enum (`AnswerType.NUMERIC`, str-repr
    `"AnswerType.NUMERIC"`) and a bare string (`"numeric"`). Returns the
    lowercase stem (`"numeric"`) so the scorer's branch checks work uniformly.
    """
    s = str(answer_type)
    return s.split(".")[-1].lower() if "." in s else s.lower()


def score_answer(prediction_text: str, example: BenchmarkExample) -> float:
    """Return 1.0 if the prediction matches the gold answer under the example's
    answer_type tolerance, else 0.0.

    Mirrors parser-bench's scorer (`third_party/parser-bench/src/eval/scoring.py`)
    so the reproducibility gate (simple agent within ±1 pt of published numbers)
    holds. Each branch delegates to a parser-bench-equivalent helper.
    """
    gold = (example.answer or "").strip()
    pred = (prediction_text or "").strip()
    stem = _answer_type_stem(example.answer_type)

    if stem == "unanswerable":
        return 1.0 if _is_abstention(pred) else 0.0

    if stem == "boolean":
        return 1.0 if _score_boolean(pred, gold) else 0.0

    if stem == "multiple_choice":
        return 1.0 if _score_multiple_choice(pred, gold) else 0.0

    if stem == "numeric":
        return _score_numeric(pred, gold, example.tolerance)

    # exact_match (fall-through)
    return 1.0 if _score_exact_match(pred, gold) else 0.0


# Parser-bench parity: mirror of `src/eval/scoring.py:_ABSTAIN_PHRASES`.
_ABSTAIN_PHRASES: frozenset[str] = frozenset(
    {
        "unanswerable",
        "cannot be determined",
        "not enough information",
        "cannot answer",
        "insufficient information",
        "unable to determine",
        "not answerable",
        "cannot be answered",
        "n/a",
    }
)


def _is_abstention(text: str) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in _ABSTAIN_PHRASES)


def _normalize_bool(text: str) -> str | None:
    t = text.strip().lower()
    if t in ("true", "yes", "y", "1", "correct"):
        return "true"
    if t in ("false", "no", "n", "0", "incorrect"):
        return "false"
    return None


# ---------------------------------------------------------------------------
# Parser-bench parity helpers: exact_match / boolean / multiple_choice
# (mirrors of `third_party/parser-bench/src/eval/scoring.py`)
# ---------------------------------------------------------------------------


def _normalize_text_for_match(s: str) -> str:
    """Lowercase, collapse whitespace, strip trailing punctuation.

    Mirrors parser-bench's `_normalize_text`. Trailing `;,.\\s` strip catches
    the common pattern where the gold answer has an explanation clause after
    the core value.
    """
    import re

    s = s.strip().lower()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[;,.\s]+$", "", s)
    return s


def _score_exact_match(pred: str, gold: str) -> bool:
    """Match parser-bench's `_score_exact_match` — 4 fallback layers.

    1. Verbatim normalized equality.
    2. Gold has explanation after a separator (`;`, `. `, ` — `, ` - `) →
       compare the core token before the separator.
    3. Containment in either direction with overlap thresholds.
    4. Parenthetical removal: `X (Y)` ≡ `X`.
    """
    import re

    p = _normalize_text_for_match(pred)
    g = _normalize_text_for_match(gold)

    # 1. Verbatim match
    if p == g:
        return True

    # 2. Gold has explanation after separator — match the core value
    for sep in (";", ". ", " — ", " - "):
        if sep in g:
            g_core = _normalize_text_for_match(g.split(sep, 1)[0])
            if g_core and (p == g_core or (len(p) >= 3 and p in g_core)):
                return True

    # 3. Containment: pred is the core answer within a longer gold
    if len(p) >= 3 and p in g:
        if len(g) <= 80:
            if len(p) >= len(g) * 0.4:
                return True
        else:
            return True
    # 3b. Gold is contained in pred (model was more verbose)
    if len(g) >= 3 and g in p:
        if len(g) >= len(p) * 0.4:
            return True

    # 4. Parenthetical removal
    g_np = _normalize_text_for_match(re.sub(r"\s*\([^)]*\)", "", g))
    p_np = _normalize_text_for_match(re.sub(r"\s*\([^)]*\)", "", p))
    if p_np and p_np == g_np:
        return True

    return False


def _score_boolean(pred: str, gold: str) -> bool:
    """Match parser-bench's `_score_boolean`. Tokenize on `,;.`, normalize."""
    p_token = pred.strip().lower().split(",")[0].split(";")[0].split(".")[0].strip()
    g_token = gold.strip().lower().split(",")[0].split(";")[0].split(".")[0].strip()
    p_bool = _normalize_bool(p_token)
    g_bool = _normalize_bool(g_token)
    if p_bool is not None and g_bool is not None:
        return p_bool == g_bool
    return p_token == g_token


def _score_multiple_choice(pred: str, gold: str) -> bool:
    """Match parser-bench's `_score_multiple_choice`. Standalone letter A-E first."""
    import re

    standalone = re.compile(r"(?<![a-zA-Z])([A-Ea-e])(?![a-zA-Z])")
    p_m = standalone.search(pred)
    g_m = standalone.search(gold)
    if p_m and g_m:
        return p_m.group(1).upper() == g_m.group(1).upper()
    p_any = re.search(r"[A-Ea-e]", pred)
    g_any = re.search(r"[A-Ea-e]", gold)
    if p_any and g_any:
        return p_any.group().upper() == g_any.group().upper()
    return pred.strip().lower() == gold.strip().lower()


_NUMERIC_TOKEN_RE_STR = r"-?\d+(?:,\d{3})*(?:\.\d+)?(?:[eE][+-]?\d+)?"
_UNIT_PATTERN_STR = r"[^\d\.\-\+eE]"


def _strip_units(s: str) -> str:
    """Mirror parser-bench's `_strip_units`: drop currency / units / commas."""
    import re

    s = s.replace(",", "").replace(" ", "")
    s = re.sub(_UNIT_PATTERN_STR, "", s)
    return s.strip()


def _extract_float(text: str) -> float | None:
    """Parse a numeric value from `text` matching parser-bench `_parse_numeric`.

    First tries strip-and-parse (handles "$1,234.56", "42 USD", "5.5V", "40%"
    cleanly). Falls back to first-numeric-token regex for prose-wrapped golds
    like "Approximately 520 A" or "The aspect ratio is approximately 1.0 (...)".
    """
    if text is None:
        return None
    try:
        return float(_strip_units(text))
    except (ValueError, TypeError):
        pass
    import re

    m = re.search(_NUMERIC_TOKEN_RE_STR, text)
    if not m:
        return None
    try:
        return float(m.group().replace(",", ""))
    except ValueError:
        return None


def _score_numeric(pred: str, gold: str, tolerance: float | None) -> float:
    """Match parser-bench's scorer (third_party/parser-bench/src/eval/scoring.py:56):
    when `tolerance` is provided, it's an absolute delta between extracted
    numeric tokens. When `tolerance` is None, fall back to 1% relative
    tolerance against the gold magnitude (clamped to abs(gold) ≥ 1.0 so small
    golds like 0.5 don't reduce tolerance to 0.005). The 1e-9 epsilon absorbs
    FP error near tolerance boundaries (`|1.1 - 1.0|` is `0.10000000000000009`).
    """
    p = _extract_float(pred)
    g = _extract_float(gold)
    if p is None or g is None:
        return 0.0
    if tolerance is not None:
        return 1.0 if abs(p - g) <= tolerance + 1e-9 else 0.0
    rel = 0.01 * max(abs(g), 1.0)
    return 1.0 if abs(p - g) <= rel + 1e-9 else 0.0


# ---------------------------------------------------------------------------
# Localization scoring
# ---------------------------------------------------------------------------


def _bbox_iou(a: BBox, b: BBox) -> float:
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


def _to_unit_interval_bbox(
    bbox: BBox,
    image_dims_by_page: dict[int, tuple[int, int]] | None,
) -> BBox:
    """Return a copy of `bbox` in [0,1] coords.

    Coordinate-space convention in FocusParse:
      * focus-agent citations are normalized [0,1]
      * parser-bench gold `supporting_bboxes` are absolute pixel coords at
        the page image's render DPI (typically 300)

    We autodetect by max coord: anything > 1.0 is treated as pixel-space.
    When `image_dims_by_page` doesn't cover a page, the bbox is returned
    unchanged — an imperfect fallback, but `_bbox_iou` then safely returns
    0 for the mixed-space case instead of a misleading non-zero number.
    """
    max_coord = max(bbox.x0, bbox.y0, bbox.x1, bbox.y1)
    if max_coord <= 1.0:
        return bbox
    if image_dims_by_page is None:
        return bbox
    dims = image_dims_by_page.get(bbox.page)
    if dims is None:
        return bbox

    from focusparse._parser_bench import BBox

    width, height = dims
    if width <= 0 or height <= 0:
        return bbox
    return BBox(
        page=bbox.page,
        x0=bbox.x0 / width,
        y0=bbox.y0 / height,
        x1=bbox.x1 / width,
        y1=bbox.y1 / height,
    )


def max_iou_over_alternates(
    predicted_bboxes: list[BBox],
    example: BenchmarkExample,
    *,
    image_dims_by_page: dict[int, tuple[int, int]] | None = None,
) -> float:
    """Best IoU between any predicted bbox and any gold-or-alternate bbox.

    Both sides are normalized to [0,1] via `_to_unit_interval_bbox` when
    `image_dims_by_page` is provided, so predicted (normalized) and gold
    (pixel-space) bboxes yield meaningful IoU. Without the dim map, we
    fall through to raw-coord comparison (correct when both sides happen
    to be in the same space — e.g. simple-agent runs where the VLM
    returns pixel coords to match gold).
    """
    from focusparse._parser_bench import BBox  # noqa: F401 — type only

    golds = list(example.supporting_bboxes) + list(example.alternate_bboxes)
    if not predicted_bboxes or not golds:
        return 0.0
    norm_preds = [_to_unit_interval_bbox(p, image_dims_by_page) for p in predicted_bboxes]
    norm_golds = [_to_unit_interval_bbox(g, image_dims_by_page) for g in golds]
    best = 0.0
    for p in norm_preds:
        for g in norm_golds:
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
    predicted_bboxes: list[BBox],
    tool_calls: list[dict[str, Any]],
    example: BenchmarkExample,
    largest_crop_area_ratio: float = 0.0,
    image_dims_by_page: dict[int, tuple[int, int]] | None = None,
) -> float:
    """Evidence-grounded reward ∈ [0, 1].

    Zero iff the model answered without calling any tool, or without predicting
    any bbox — the "lazy correct" case. Otherwise, multiplicative combination of
    answer correctness × page recall × best IoU, minus a penalty for crops that
    are essentially the whole page (AgenticOCR-style "lazy full-page" flag).

    `image_dims_by_page` forwards to `max_iou_over_alternates` for
    coordinate-space normalization. Pass it whenever predicted and gold
    bboxes are in different spaces (typical for the focus agent — predicted
    is normalized [0,1], gold is pixel at render DPI).
    """
    if len(tool_calls) == 0 or len(predicted_bboxes) == 0:
        return 0.0
    answer = score_answer(prediction_text, example)
    pages = page_recall(predicted_pages, [b.page for b in example.supporting_bboxes])
    iou = max_iou_over_alternates(predicted_bboxes, example, image_dims_by_page=image_dims_by_page)
    lazy_penalty = 0.2 if largest_crop_area_ratio > 0.6 else 0.0
    reward = answer * pages * iou - lazy_penalty
    return max(0.0, min(1.0, reward))
