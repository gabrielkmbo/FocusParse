"""Audit parser-bench public gold QA rows for publish readiness.

The audit is intentionally read-only against Hugging Face and the local
`third_party/parser-bench` submodule. It uses the Hugging Face Dataset Viewer
API instead of downloading the multi-GB parquet shards, then writes row-level
findings and a compact research report.

Example:

    uv run python scripts/audit_parser_bench_goldens.py \
      --hf-revision 3774c67f8b814392b6d04c939e904f749a3f52eb \
      --splits train,validation,test
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DATASET_VIEWER = "https://datasets-server.huggingface.co"
DEFAULT_REPO = "gabrielbo/parser-bench"
DEFAULT_REVISION = "3774c67f8b814392b6d04c939e904f749a3f52eb"
DEFAULT_OUTPUT_DIR = Path("results/audits/parser-bench-golden-audit-2026-05-11")
DEFAULT_REPORT_PATH = Path("docs/audits/parser-bench-golden-audit.md")
DEFAULT_SPLITS = ("train", "validation", "test")
HF_TO_LOCAL_SPLIT = {"train": "dev", "validation": "test", "test": "holdout"}
CANONICAL_STRESS_VALUE = "none"

ALLOWED_ANSWER_TYPES = {"numeric", "exact_match", "multiple_choice", "boolean", "unanswerable"}
ABSTAIN_PHRASES = {
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

NUMERIC_TOKEN_RE = re.compile(r"-?\d+(?:,\d{3})*(?:\.\d+)?(?:[eE][+-]?\d+)?")
HEX_TOKEN_RE = re.compile(r"0x[0-9A-Fa-f]+")
UNIT_PATTERN_RE = re.compile(r"[^\d\.\-\+eE]")
ASSET_REVISION_RE = re.compile(r"/--/([0-9a-f]{40})/--/")
ESTIMATE_WORD_RE = re.compile(
    r"(?:\b(?:estimate|estimated|approximately|approx\.?|nearest|interpolat\w*)\b|±|\+/-)",
    re.IGNORECASE,
)
REQUESTED_TOLERANCE_RE = re.compile(
    r"(?:tolerance[^0-9±+/-]{0,30}|within\s+|acceptable tolerance:?\s*)"
    r"(?:±|\+/-)\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
VOLT_REQUEST_RE = re.compile(
    r"(?:answer|provide|report|express)[^.?\n]{0,80}\b(?:volts?|v)\b|"
    r"(?:±|\+/-)\s*\d+(?:\.\d+)?\s*v\b",
    re.IGNORECASE,
)
WHITESPACE_RE = re.compile(r"\s+")
GOLDEN_FIX_CODES = {
    "answer_unit_mismatch",
    "estimate_with_zero_tolerance",
    "invalid_tolerance",
    "numeric_answer_unparseable",
    "numeric_formula_answer",
    "numeric_hex_answer",
    "numeric_missing_tolerance",
    "numeric_multi_field_answer",
    "numeric_prose_prefix_answer",
    "numeric_range_answer",
    "numeric_ratio_prose_answer",
    "numeric_symbolic_expression_answer",
    "numeric_wording_with_non_numeric_type",
    "tolerance_mismatch",
    "unanswerable_answer_not_abstain",
}


@dataclass(frozen=True)
class Issue:
    severity: str
    code: str
    message: str
    suggestion: str

    def as_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "suggestion": self.suggestion,
        }


def _json_default(obj: Any) -> Any:
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _fetch_json(
    endpoint: str,
    params: dict[str, str | int],
    *,
    timeout_s: float,
    retries: int,
) -> dict[str, Any]:
    url = f"{DATASET_VIEWER}{endpoint}?{urlencode(params)}"
    headers = {"User-Agent": "focusparse-golden-audit/1.0"}
    if token := os.environ.get("HF_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers)
    for attempt in range(retries + 1):
        try:
            with urlopen(request, timeout=timeout_s) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            retryable = exc.code == 429 or 500 <= exc.code < 600
            if retryable and attempt < retries:
                retry_after = exc.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after else None
                except ValueError:
                    delay = None
                if delay is None:
                    delay = (
                        min(60.0, 10.0 * (attempt + 1))
                        if exc.code == 429
                        else min(8.0, 1.5 * (attempt + 1))
                    )
                time.sleep(delay)
                continue
            raise RuntimeError(
                f"HF Dataset Viewer request failed: {exc.code} {url}: {body}"
            ) from exc
        except (TimeoutError, URLError) as exc:
            if attempt < retries:
                time.sleep(min(8.0, 1.5 * (attempt + 1)))
                continue
            raise RuntimeError(f"HF Dataset Viewer request failed: {url}: {exc}") from exc
    raise RuntimeError(f"HF Dataset Viewer request failed after retries: {url}")


def _fetch_split_rows(
    *,
    repo: str,
    revision: str | None,
    split: str,
    limit: int | None,
    timeout_s: float,
    retries: int,
    page_size: int,
    progress_interval: int,
    request_delay_s: float,
    fetch_cache_dir: Path | None,
) -> tuple[list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = _load_cached_split_rows(fetch_cache_dir, split, revision)
    total_rows = 0
    offset = len(rows)
    if rows:
        print(f"loaded cached {split}: {len(rows)} rows", file=sys.stderr, flush=True)
    while True:
        if limit is not None and len(rows) >= limit:
            break
        length = min(page_size, (limit - len(rows)) if limit is not None else page_size)
        params: dict[str, str | int] = {
            "dataset": repo,
            "config": "default",
            "split": split,
            "offset": offset,
            "length": length,
        }
        if revision:
            params["revision"] = revision
        try:
            payload = _fetch_json("/rows", params, timeout_s=timeout_s, retries=retries)
        except RuntimeError:
            if length <= 1:
                raise
            # Some image-heavy row windows 502 when batched but succeed as a
            # single-row request. Keep the audit moving without downloading
            # parquet shards.
            params["length"] = 1
            payload = _fetch_json("/rows", params, timeout_s=timeout_s, retries=retries)
        total_rows = int(payload.get("num_rows_total") or total_rows)
        wrapped_rows = payload.get("rows") or []
        if not isinstance(wrapped_rows, list) or not wrapped_rows:
            break
        new_rows: list[dict[str, Any]] = []
        for wrapped in wrapped_rows:
            row = dict(wrapped.get("row") or {})
            row["_hf_split"] = split
            row["_row_idx"] = wrapped.get("row_idx")
            rows.append(row)
            new_rows.append(row)
            if progress_interval and len(rows) % progress_interval == 0:
                total_label = str(total_rows) if total_rows else "?"
                print(
                    f"fetched {split}: {len(rows)}/{total_label} rows",
                    file=sys.stderr,
                    flush=True,
                )
        _append_cached_split_rows(fetch_cache_dir, split, revision, new_rows)
        offset += len(wrapped_rows)
        if offset >= total_rows or len(wrapped_rows) < length:
            break
        if request_delay_s > 0:
            time.sleep(request_delay_s)
    return rows, total_rows


def _fetch_rows(
    *,
    repo: str,
    revision: str | None,
    splits: list[str],
    limit: int | None,
    timeout_s: float,
    retries: int,
    page_size: int,
    progress_interval: int,
    request_delay_s: float,
    fetch_cache_dir: Path | None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows: list[dict[str, Any]] = []
    totals: dict[str, int] = {}
    remaining = limit
    for split in splits:
        split_limit = remaining
        split_rows, total = _fetch_split_rows(
            repo=repo,
            revision=revision,
            split=split,
            limit=split_limit,
            timeout_s=timeout_s,
            retries=retries,
            page_size=page_size,
            progress_interval=progress_interval,
            request_delay_s=request_delay_s,
            fetch_cache_dir=fetch_cache_dir,
        )
        totals[split] = total
        rows.extend(split_rows)
        if remaining is not None:
            remaining -= len(split_rows)
            if remaining <= 0:
                break
    return rows, totals


def _cache_file(fetch_cache_dir: Path | None, split: str, revision: str | None) -> Path | None:
    if fetch_cache_dir is None:
        return None
    rev = revision or "HEAD"
    safe_rev = re.sub(r"[^A-Za-z0-9_.-]", "_", rev)
    return fetch_cache_dir / f"{split}_{safe_rev}.jsonl"


def _load_cached_split_rows(
    fetch_cache_dir: Path | None,
    split: str,
    revision: str | None,
) -> list[dict[str, Any]]:
    cache_file = _cache_file(fetch_cache_dir, split, revision)
    if cache_file is None or not cache_file.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in cache_file.read_text().splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def _append_cached_split_rows(
    fetch_cache_dir: Path | None,
    split: str,
    revision: str | None,
    rows: list[dict[str, Any]],
) -> None:
    cache_file = _cache_file(fetch_cache_dir, split, revision)
    if cache_file is None or not rows:
        return
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    with cache_file.open("a") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _parse_json_list(value: Any, *, field_name: str, issues: list[Issue]) -> list[dict[str, Any]]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [v for v in value if isinstance(v, dict)]
    if not isinstance(value, str):
        issues.append(
            Issue(
                "error",
                f"invalid_{field_name}",
                f"{field_name} should be a JSON list, got {type(value).__name__}.",
                f"Re-export {field_name} as a JSON-encoded list.",
            )
        )
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        issues.append(
            Issue(
                "error",
                f"invalid_{field_name}",
                f"{field_name} is not valid JSON: {exc.msg}.",
                f"Repair the serialized {field_name} payload before publishing.",
            )
        )
        return []
    if not isinstance(parsed, list):
        issues.append(
            Issue(
                "error",
                f"invalid_{field_name}",
                f"{field_name} JSON decoded to {type(parsed).__name__}, not list.",
                f"Re-export {field_name} as a list.",
            )
        )
        return []
    return [v for v in parsed if isinstance(v, dict)]


def _strip_units(text: str) -> str:
    return UNIT_PATTERN_RE.sub("", text.replace(",", "").replace(" ", "")).strip()


def _extract_float(text: Any) -> float | None:
    if text is None:
        return None
    s = str(text)
    try:
        return float(_strip_units(s))
    except (TypeError, ValueError):
        pass
    match = NUMERIC_TOKEN_RE.search(s)
    if not match:
        return None
    try:
        return float(match.group().replace(",", ""))
    except ValueError:
        return None


def _numeric_token_strings(text: Any) -> list[str]:
    return [match.group().replace(",", "") for match in NUMERIC_TOKEN_RE.finditer(str(text or ""))]


def _last_numeric_token(text: Any) -> str | None:
    tokens = _numeric_token_strings(text)
    return tokens[-1] if tokens else None


def _hex_result(text: Any) -> str | None:
    tokens = [match.group() for match in HEX_TOKEN_RE.finditer(str(text or ""))]
    return tokens[-1] if tokens else None


def _numeric_after_equals(text: Any) -> str | None:
    rhs = str(text or "").rsplit("=", 1)[-1]
    return _last_numeric_token(rhs)


def _requested_tolerance(text: Any) -> float | None:
    match = REQUESTED_TOLERANCE_RE.search(str(text or ""))
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _normalize_unit(value: Any) -> str:
    return re.sub(r"[^a-z%]", "", str(value or "").lower())


def _answer_requests_volts(question: str) -> bool:
    return bool(VOLT_REQUEST_RE.search(question))


def _answer_has_numeric_range(answer: str) -> bool:
    return bool(
        re.search(
            rf"{NUMERIC_TOKEN_RE.pattern}\s+to\s+{NUMERIC_TOKEN_RE.pattern}",
            answer,
            re.IGNORECASE,
        )
    )


def _by_value_after_prefix(answer: str, numeric_tokens: list[str]) -> str | None:
    if len(numeric_tokens) < 2:
        return None
    match = re.search(
        rf"\bby\s+(?:approximately\s+|about\s+)?({NUMERIC_TOKEN_RE.pattern})\b",
        answer,
        re.IGNORECASE,
    )
    if not match:
        return None
    value = match.group(1).replace(",", "")
    return value if value != numeric_tokens[0] else None


def _looks_multi_field_numeric(question: str, answer: str, answer_unit: Any) -> bool:
    if len(_numeric_token_strings(answer)) < 2:
        return False
    unit_text = str(answer_unit or "").lower()
    question_text = question.lower()
    if "," in unit_text:
        return True
    if re.search(r"\bprovide the .*, .* and\b", question_text):
        return True
    return bool(re.search(r"\band what is the approximate\b", question_text))


def _looks_symbolic_numeric_expression(answer: str) -> bool:
    return bool(re.search(r"^\s*[A-Za-z_][A-Za-z0-9_]*\s*[-+*/]\s*\d", answer))


def _looks_abstain(text: Any) -> bool:
    lowered = str(text or "").strip().lower()
    return bool(lowered) and any(phrase in lowered for phrase in ABSTAIN_PHRASES)


def _normalize_text(text: Any) -> str:
    lowered = str(text or "").strip().lower()
    return WHITESPACE_RE.sub(" ", lowered)


def _image_dims_by_supporting_page(row: dict[str, Any]) -> dict[int, tuple[int, int]]:
    supporting_pages = row.get("supporting_pages") or []
    page_images = row.get("page_images") or []
    dims: dict[int, tuple[int, int]] = {}
    if not isinstance(supporting_pages, list) or not isinstance(page_images, list):
        return dims
    for idx, image in enumerate(page_images):
        if idx >= len(supporting_pages) or not isinstance(image, dict):
            continue
        try:
            page = int(supporting_pages[idx])
            width = int(image.get("width") or 0)
            height = int(image.get("height") or 0)
        except (TypeError, ValueError):
            continue
        if width > 0 and height > 0:
            dims[page] = (width, height)
    return dims


def _bbox_area_ratio(bbox: dict[str, Any], dims: tuple[int, int]) -> float | None:
    try:
        width, height = dims
        x0 = float(bbox["x0"])
        y0 = float(bbox["y0"])
        x1 = float(bbox["x1"])
        y1 = float(bbox["y1"])
    except (KeyError, TypeError, ValueError):
        return None
    page_area = width * height
    if page_area <= 0:
        return None
    return max(0.0, (x1 - x0) * (y1 - y0)) / page_area


def _validate_bboxes(
    *,
    bboxes: list[dict[str, Any]],
    field_name: str,
    supporting_pages: list[int],
    dims_by_page: dict[int, tuple[int, int]],
    issues: list[Issue],
) -> None:
    for idx, bbox in enumerate(bboxes):
        prefix = f"{field_name}[{idx}]"
        try:
            page = int(bbox["page"])
            x0 = float(bbox["x0"])
            y0 = float(bbox["y0"])
            x1 = float(bbox["x1"])
            y1 = float(bbox["y1"])
        except (KeyError, TypeError, ValueError):
            issues.append(
                Issue(
                    "error",
                    "malformed_bbox",
                    f"{prefix} is missing page/x0/y0/x1/y1 numeric fields.",
                    "Redraw or re-export the bbox with complete numeric coordinates.",
                )
            )
            continue

        if page not in supporting_pages and field_name == "supporting_bboxes":
            issues.append(
                Issue(
                    "error",
                    "bbox_page_not_supporting_page",
                    f"{prefix} is on page {page}, outside supporting_pages={supporting_pages}.",
                    "Align supporting_pages with the evidence bboxes.",
                )
            )

        if x1 <= x0 or y1 <= y0:
            issues.append(
                Issue(
                    "error",
                    "degenerate_bbox",
                    f"{prefix} has non-positive area.",
                    "Redraw the evidence box with x1>x0 and y1>y0.",
                )
            )
            continue

        if max(x0, y0, x1, y1) <= 1.0:
            issues.append(
                Issue(
                    "warning",
                    "normalized_bbox",
                    f"{prefix} appears normalized even though parser-bench schema uses pixels.",
                    "Confirm coordinate space and re-export in pixel coordinates if needed.",
                )
            )
            continue

        dims = dims_by_page.get(page)
        if dims is None:
            issues.append(
                Issue(
                    "warning",
                    "bbox_without_image_dims",
                    f"{prefix} page {page} has no matching page image dimensions.",
                    "Ensure page_images order matches supporting_pages.",
                )
            )
            continue
        width, height = dims
        if x0 < 0 or y0 < 0 or x1 > width or y1 > height:
            issues.append(
                Issue(
                    "error",
                    "bbox_out_of_bounds",
                    f"{prefix} exceeds image bounds {width}x{height}.",
                    "Redraw the bbox inside the rendered page image.",
                )
            )
        area_ratio = _bbox_area_ratio(bbox, dims)
        if area_ratio is None:
            continue
        if area_ratio > 0.80:
            issues.append(
                Issue(
                    "warning",
                    "very_large_bbox",
                    f"{prefix} covers {area_ratio:.1%} of the page.",
                    "Tighten the evidence box so it localizes the answer-bearing region.",
                )
            )
        elif area_ratio < 0.00001:
            issues.append(
                Issue(
                    "warning",
                    "very_small_bbox",
                    f"{prefix} covers only {area_ratio:.4%} of the page.",
                    "Confirm the box is not too small to contain readable evidence.",
                )
            )


def _extract_asset_revision(row: dict[str, Any]) -> str | None:
    candidates: list[Any] = []
    candidates.extend(row.get("page_images") or [])
    for field in ("tiled_2up", "tiled_4up", "tiled_8up"):
        candidates.append(row.get(field))
    for image in candidates:
        if not isinstance(image, dict):
            continue
        src = str(image.get("src") or "")
        match = ASSET_REVISION_RE.search(src)
        if match:
            return match.group(1)
    return None


def _status_from_issues(issues: list[Issue]) -> str:
    error_codes = {issue.code for issue in issues if issue.severity == "error"}
    if not error_codes:
        return "publishable"
    remove_codes = {"empty_question", "empty_answer", "no_page_images", "no_supporting_bboxes"}
    if error_codes & remove_codes:
        return "remove"
    return "fix_required"


def _suggested_action(status: str, issues: list[Issue]) -> str:
    if status == "publishable":
        return "No deterministic publish blocker found; keep available for visual adjudication."
    suggestions = []
    for issue in issues:
        if issue.severity == "error" and issue.suggestion not in suggestions:
            suggestions.append(issue.suggestion)
    if not suggestions:
        suggestions = [issue.suggestion for issue in issues[:3]]
    return " ".join(suggestions)


def _proposed_fix(record: dict[str, Any]) -> str:
    codes = {str(issue["code"]) for issue in record.get("issues", [])}
    answer = _short_text(record.get("answer") or "", 80)
    row_id = str(record.get("id") or "row")
    split = str(record.get("hf_split") or "split")
    row_idx = record.get("row_idx")
    unique_id = f"{row_id}__{split}_{row_idx}"
    full_answer = str(record.get("answer") or "")
    question = str(record.get("question") or "")

    if record.get("status") == "publishable":
        return "No answer or question rewrite indicated by deterministic audit."
    if "empty_question" in codes:
        return "Regenerate the question from the cited evidence or remove the row."
    if "empty_answer" in codes or "numeric_answer_unparseable" in codes:
        return "Restore a parseable gold answer from the cited evidence before publishing."
    if "answer_abstains_but_type_answerable" in codes:
        return (
            "Rewrite the gold answer with the actual answer, or change answer_type to unanswerable."
        )
    if "unanswerable_answer_not_abstain" in codes:
        return "Keep the question, but set the gold answer to an abstention phrase."
    if "numeric_hex_answer" in codes:
        hex_answer = _hex_result(full_answer) or answer
        return (
            f"Change answer_type to exact_match and use gold answer `{hex_answer}`, "
            "or add a hex-aware scorer before publishing."
        )
    if "numeric_symbolic_expression_answer" in codes:
        return (
            f"Gold answer `{answer}` is symbolic, not scalar. Rewrite the question as "
            "symbolic/exact-match, or provide a concrete numeric value if the document "
            "defines the missing variable."
        )
    if "numeric_formula_answer" in codes:
        scalar_answer = (
            _numeric_after_equals(full_answer) or _last_numeric_token(full_answer) or answer
        )
        return f"Use scalar numeric gold `{scalar_answer}` and move the equation/explanation to rationale."
    if "numeric_ratio_prose_answer" in codes:
        scalar_answer = _last_numeric_token(full_answer) or answer
        return (
            f"Use scalar ratio gold `{scalar_answer}`; keep dates/series values in rationale only."
        )
    if "numeric_prose_prefix_answer" in codes:
        scalar_answer = (
            _by_value_after_prefix(full_answer, _numeric_token_strings(full_answer)) or answer
        )
        return (
            f"Use scalar numeric gold `{scalar_answer}`; keep label/context numbers in rationale."
        )
    if "numeric_range_answer" in codes:
        return (
            f"Range gold `{answer}` is not a single scalar. Split into lower/upper-bound "
            "questions, ask for a midpoint, or use exact/structured scoring."
        )
    if "numeric_multi_field_answer" in codes:
        return (
            f"Compound gold `{answer}` should not use scalar numeric scoring. Split the "
            "question into one scored scalar, or convert the row to exact/structured scoring."
        )
    if "answer_unit_mismatch" in codes and "tolerance_mismatch" in codes:
        requested = _requested_tolerance(question)
        requested_label = f"`{requested:g}`" if requested is not None else "the stated tolerance"
        return f"Keep gold answer `{answer}`, but set answer_unit to `V` and tolerance to {requested_label}."
    if "answer_unit_mismatch" in codes:
        unit = "V" if _answer_requests_volts(question) else "the requested unit"
        return (
            f"Keep gold answer `{answer}`, but set answer_unit to `{unit}` and recheck tolerance."
        )
    if "tolerance_mismatch" in codes:
        requested = _requested_tolerance(question)
        requested_label = f"`{requested:g}`" if requested is not None else "the stated tolerance"
        return f"Keep gold answer `{answer}`, but set tolerance to {requested_label}."
    if "estimate_with_zero_tolerance" in codes:
        return (
            f"Keep gold answer `{answer}`; set a non-zero absolute tolerance matching the "
            "question wording, or rewrite the question as an exact lookup."
        )
    if "numeric_missing_tolerance" in codes or "invalid_tolerance" in codes:
        return f"Keep gold answer `{answer}`; set a non-negative numeric tolerance."
    if "numeric_wording_with_non_numeric_type" in codes:
        return (
            f"Keep question and gold answer `{answer}`, but change answer_type to numeric "
            "with an explicit unit/tolerance, or rewrite the question to request exact text."
        )
    if "non_numeric_tolerance" in codes:
        return (
            f"Keep gold answer `{answer}`; either clear tolerance for exact scoring or convert "
            "the row to numeric scoring."
        )
    if "duplicate_id" in codes:
        return (
            f"No answer rewrite indicated; assign a unique id such as `{unique_id}` or remove "
            "the duplicate row after choosing the intended split/stress variant."
        )
    if codes & {
        "bbox_without_image_dims",
        "bbox_out_of_bounds",
        "bbox_page_not_supporting_page",
        "page_image_supporting_page_count_mismatch",
        "malformed_bbox",
        "degenerate_bbox",
        "no_supporting_bboxes",
        "no_supporting_pages",
        "no_page_images",
    }:
        return "Keep QA text only after visual review; re-export supporting pages/images/bboxes."
    return _short_text(record.get("suggested_action") or "", 180)


def _audit_row(row: dict[str, Any]) -> dict[str, Any]:
    issues: list[Issue] = []
    row_id = str(row.get("id") or "")
    hf_split = str(row.get("_hf_split") or "")
    local_split = str(row.get("split") or "")
    expected_local_split = HF_TO_LOCAL_SPLIT.get(hf_split)

    question = str(row.get("question") or "")
    answer = str(row.get("answer") or "")
    answer_type = str(row.get("answer_type") or "").lower()
    stress_type = str(row.get("stress_type") or CANONICAL_STRESS_VALUE).lower()
    supporting_pages_raw = row.get("supporting_pages") or []
    page_images = row.get("page_images") or []

    if not row_id:
        issues.append(
            Issue("error", "empty_id", "Row id is empty.", "Regenerate the row with a stable id.")
        )
    if not question.strip():
        issues.append(
            Issue(
                "error",
                "empty_question",
                "Question is empty.",
                "Remove the row or regenerate a complete QA pair.",
            )
        )
    if not answer.strip():
        issues.append(
            Issue(
                "error",
                "empty_answer",
                "Answer is empty.",
                "Restore the gold answer before publishing.",
            )
        )
    if answer_type not in ALLOWED_ANSWER_TYPES:
        issues.append(
            Issue(
                "error",
                "invalid_answer_type",
                f"answer_type={answer_type!r} is not supported.",
                f"Use one of {sorted(ALLOWED_ANSWER_TYPES)}.",
            )
        )
    if expected_local_split and local_split != expected_local_split:
        issues.append(
            Issue(
                "error",
                "split_mapping_mismatch",
                f"HF split {hf_split!r} should carry local split {expected_local_split!r}, "
                f"got {local_split!r}.",
                "Re-export the row with the correct parser-bench split value.",
            )
        )

    if not isinstance(supporting_pages_raw, list) or not supporting_pages_raw:
        supporting_pages: list[int] = []
        issues.append(
            Issue(
                "error",
                "no_supporting_pages",
                "supporting_pages is empty or malformed.",
                "Add the page numbers needed to answer this question.",
            )
        )
    else:
        supporting_pages = []
        for page in supporting_pages_raw:
            try:
                supporting_pages.append(int(page))
            except (TypeError, ValueError):
                issues.append(
                    Issue(
                        "error",
                        "invalid_supporting_page",
                        f"supporting_pages contains non-integer value {page!r}.",
                        "Re-export supporting_pages as integer page numbers.",
                    )
                )

    if not isinstance(page_images, list) or not page_images:
        issues.append(
            Issue(
                "error",
                "no_page_images",
                "page_images is empty or malformed.",
                "Restore the rendered page image(s) for this row.",
            )
        )
    else:
        for idx, image in enumerate(page_images):
            if not isinstance(image, dict):
                issues.append(
                    Issue(
                        "error",
                        "malformed_page_image",
                        f"page_images[{idx}] is not an image object.",
                        "Re-export page_images with embedded HF image metadata.",
                    )
                )
                continue
            width = image.get("width")
            height = image.get("height")
            if (
                not isinstance(width, int)
                or not isinstance(height, int)
                or width <= 0
                or height <= 0
            ):
                issues.append(
                    Issue(
                        "error",
                        "invalid_page_image_dims",
                        f"page_images[{idx}] has invalid dimensions {width}x{height}.",
                        "Re-render the page image before publishing.",
                    )
                )

    if len(page_images) != len(supporting_pages):
        issues.append(
            Issue(
                "warning",
                "page_image_supporting_page_count_mismatch",
                f"page_images has {len(page_images)} entries but supporting_pages has "
                f"{len(supporting_pages)}.",
                "Confirm image order still matches supporting_pages for eval citation remapping.",
            )
        )

    supporting_bboxes = _parse_json_list(
        row.get("supporting_bboxes"), field_name="supporting_bboxes", issues=issues
    )
    alternate_bboxes = _parse_json_list(
        row.get("alternate_bboxes"), field_name="alternate_bboxes", issues=issues
    )
    evidence_relations = _parse_json_list(
        row.get("evidence_relations"), field_name="evidence_relations", issues=issues
    )

    if not supporting_bboxes:
        issues.append(
            Issue(
                "error",
                "no_supporting_bboxes",
                "supporting_bboxes is empty.",
                "Add evidence boxes or remove the row.",
            )
        )

    dims_by_page = _image_dims_by_supporting_page(row)
    _validate_bboxes(
        bboxes=supporting_bboxes,
        field_name="supporting_bboxes",
        supporting_pages=supporting_pages,
        dims_by_page=dims_by_page,
        issues=issues,
    )
    _validate_bboxes(
        bboxes=alternate_bboxes,
        field_name="alternate_bboxes",
        supporting_pages=supporting_pages,
        dims_by_page=dims_by_page,
        issues=issues,
    )

    numeric_answer = _extract_float(answer)
    tolerance = row.get("tolerance")
    requested_tolerance = _requested_tolerance(question)
    answer_unit = row.get("answer_unit")
    if answer_type == "numeric":
        numeric_tokens = _numeric_token_strings(answer)
        if numeric_answer is None:
            issues.append(
                Issue(
                    "error",
                    "numeric_answer_unparseable",
                    f"Numeric answer {answer!r} does not contain a parseable number.",
                    "Correct the answer string or change answer_type.",
                )
            )
        if tolerance is None:
            issues.append(
                Issue(
                    "warning",
                    "numeric_missing_tolerance",
                    "Numeric answer has no explicit tolerance.",
                    "Set a tolerance matching the question wording.",
                )
            )
        else:
            try:
                tolerance_value = float(tolerance)
            except (TypeError, ValueError):
                tolerance_value = -1.0
            if tolerance_value < 0:
                issues.append(
                    Issue(
                        "error",
                        "invalid_tolerance",
                        f"Numeric tolerance {tolerance!r} is invalid.",
                        "Set tolerance to a non-negative number or null for scorer default.",
                    )
                )
            elif tolerance_value == 0 and ESTIMATE_WORD_RE.search(question):
                issues.append(
                    Issue(
                        "error",
                        "estimate_with_zero_tolerance",
                        "Question asks for an estimate/interpolation but tolerance is 0.",
                        "Set a non-zero tolerance or rewrite the question as an exact count.",
                    )
                )
            elif (
                requested_tolerance is not None
                and abs(tolerance_value - requested_tolerance) > 1e-9
            ):
                issues.append(
                    Issue(
                        "error",
                        "tolerance_mismatch",
                        f"Question states ±{requested_tolerance:g} but tolerance={tolerance!r}.",
                        "Set the row tolerance to the value stated in the question.",
                    )
                )

        if _answer_requests_volts(question):
            normalized_unit = _normalize_unit(answer_unit)
            if normalized_unit and not normalized_unit.startswith(("v", "volt")):
                issues.append(
                    Issue(
                        "error",
                        "answer_unit_mismatch",
                        f"Question asks for volts but answer_unit={answer_unit!r}.",
                        "Set answer_unit to V or rewrite the question to match the stored unit.",
                    )
                )

        if HEX_TOKEN_RE.search(answer) or "hex" in str(answer_unit or "").lower():
            issues.append(
                Issue(
                    "error",
                    "numeric_hex_answer",
                    "Numeric scorer cannot safely score hexadecimal address expressions.",
                    "Use exact_match with the final hexadecimal value or add a hex-aware scorer.",
                )
            )
        elif _looks_symbolic_numeric_expression(answer):
            issues.append(
                Issue(
                    "error",
                    "numeric_symbolic_expression_answer",
                    "Numeric scorer will extract a scalar from a symbolic expression answer.",
                    "Use exact_match/structured scoring or provide a fully numeric scalar answer.",
                )
            )
        elif _answer_has_numeric_range(answer):
            issues.append(
                Issue(
                    "error",
                    "numeric_range_answer",
                    "Numeric scorer handles one scalar, but the gold answer is a range.",
                    "Split into lower/upper-bound rows or use a range-aware scorer.",
                )
            )
        elif "=" in answer and len(numeric_tokens) > 1:
            issues.append(
                Issue(
                    "error",
                    "numeric_formula_answer",
                    "Numeric scorer will extract the first operand rather than the final result.",
                    "Store only the final scalar in answer and move the formula to reasoning.",
                )
            )
        elif "ratio" in question.lower() and "ratio" in answer.lower() and len(numeric_tokens) > 1:
            issues.append(
                Issue(
                    "error",
                    "numeric_ratio_prose_answer",
                    "Numeric scorer will extract a context number before the intended ratio.",
                    "Store only the rounded ratio scalar in answer.",
                )
            )
        elif by_value := _by_value_after_prefix(answer, numeric_tokens):
            issues.append(
                Issue(
                    "error",
                    "numeric_prose_prefix_answer",
                    f"Numeric scorer extracts {numeric_tokens[0]}, but answer later says {by_value}.",
                    "Store only the intended scalar answer, not context labels with numbers.",
                )
            )
        elif _looks_multi_field_numeric(question, answer, answer_unit):
            issues.append(
                Issue(
                    "error",
                    "numeric_multi_field_answer",
                    "Numeric scorer handles one scalar, but the question/gold has multiple fields.",
                    "Split the question or use exact/structured scoring.",
                )
            )
    elif answer_type in {"exact_match", "multiple_choice", "boolean"} and tolerance is not None:
        issues.append(
            Issue(
                "warning",
                "non_numeric_tolerance",
                f"{answer_type} row carries tolerance={tolerance!r}, which scoring ignores.",
                "Clear tolerance or convert the row to numeric if a tolerance is intended.",
            )
        )
    elif (
        answer_type == "exact_match"
        and numeric_answer is not None
        and (ESTIMATE_WORD_RE.search(question) or ESTIMATE_WORD_RE.search(answer))
    ):
        issues.append(
            Issue(
                "error",
                "numeric_wording_with_non_numeric_type",
                "Question/answer asks for a numeric estimate or tolerance but answer_type is exact_match.",
                "Convert to numeric with answer_unit/tolerance, or rewrite as an exact-text question.",
            )
        )

    if answer_type == "unanswerable" and answer.strip() and not _looks_abstain(answer):
        issues.append(
            Issue(
                "error",
                "unanswerable_answer_not_abstain",
                f"answer_type is unanswerable but answer={answer!r}.",
                "Set answer to an abstention phrase or change answer_type.",
            )
        )
    if answer_type != "unanswerable" and _looks_abstain(answer):
        issues.append(
            Issue(
                "error",
                "answer_abstains_but_type_answerable",
                f"answer_type={answer_type!r} but answer looks like abstention.",
                "Change answer_type to unanswerable or provide the actual gold answer.",
            )
        )

    if bool(row.get("multi_region_required")):
        if len(supporting_bboxes) < 2:
            issues.append(
                Issue(
                    "error",
                    "multi_region_without_multiple_bboxes",
                    "multi_region_required is true but fewer than two supporting bboxes exist.",
                    "Add the missing evidence region or mark multi_region_required=false.",
                )
            )
        if not evidence_relations:
            issues.append(
                Issue(
                    "warning",
                    "multi_region_without_relations",
                    "multi_region_required is true but evidence_relations is empty.",
                    "Record the evidence relation(s) that make the row multi-region.",
                )
            )

    evidence_page_spread = row.get("evidence_page_spread")
    try:
        spread_value = int(evidence_page_spread or 0)
    except (TypeError, ValueError):
        spread_value = 0
    if spread_value > 0 and len(set(supporting_pages)) < 2:
        issues.append(
            Issue(
                "warning",
                "spread_without_multi_page_support",
                f"evidence_page_spread={spread_value} but supporting_pages={supporting_pages}.",
                "Confirm supporting_pages includes every page needed for the cross-page answer.",
            )
        )

    if stress_type != CANONICAL_STRESS_VALUE:
        issues.append(
            Issue(
                "info",
                "stress_variant",
                f"stress_type={stress_type!r}; FocusParse hf_loader filters this row.",
                "Keep for raw dataset study; exclude from headline canonical evals.",
            )
        )

    status = _status_from_issues(issues)
    issue_dicts = [issue.as_dict() for issue in issues]
    record = {
        "id": row_id,
        "hf_split": hf_split,
        "local_split": local_split,
        "row_idx": row.get("_row_idx"),
        "domain": row.get("domain"),
        "source_pdf": row.get("source_pdf"),
        "question": question,
        "answer": answer,
        "answer_type": answer_type,
        "answer_unit": row.get("answer_unit"),
        "tolerance": row.get("tolerance"),
        "numeric_answer": numeric_answer,
        "supporting_pages": supporting_pages,
        "supporting_bbox_count": len(supporting_bboxes),
        "alternate_bbox_count": len(alternate_bboxes),
        "evidence_relation_count": len(evidence_relations),
        "page_image_count": len(page_images) if isinstance(page_images, list) else 0,
        "multi_region_required": bool(row.get("multi_region_required")),
        "requires_visual": bool(row.get("requires_visual")),
        "question_family": row.get("question_family"),
        "stress_type": stress_type,
        "adversarial_type": row.get("adversarial_type"),
        "asset_revision": _extract_asset_revision(row),
        "issues": issue_dicts,
        "status": status,
        "suggested_action": _suggested_action(status, issues),
        "review_packet": _review_packet(row, supporting_bboxes, alternate_bboxes),
    }
    record["proposed_fix"] = _proposed_fix(record)
    return record


def _review_packet(
    row: dict[str, Any],
    supporting_bboxes: list[dict[str, Any]],
    alternate_bboxes: list[dict[str, Any]],
) -> dict[str, Any]:
    page_images = []
    for idx, image in enumerate(row.get("page_images") or []):
        if not isinstance(image, dict):
            continue
        page_images.append(
            {
                "index": idx,
                "width": image.get("width"),
                "height": image.get("height"),
                "src": image.get("src"),
            }
        )
    return {
        "id": row.get("id"),
        "hf_split": row.get("_hf_split"),
        "row_idx": row.get("_row_idx"),
        "question": row.get("question"),
        "gold_answer": row.get("answer"),
        "answer_type": row.get("answer_type"),
        "answer_unit": row.get("answer_unit"),
        "tolerance": row.get("tolerance"),
        "reasoning_chain": row.get("reasoning_chain"),
        "supporting_pages": row.get("supporting_pages") or [],
        "supporting_bboxes": supporting_bboxes,
        "alternate_bboxes": alternate_bboxes,
        "page_images": page_images,
    }


def _apply_duplicate_checks(records: list[dict[str, Any]]) -> None:
    by_id: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    by_question: defaultdict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_id[str(record["id"])].append(record)
        key = (
            str(record.get("source_pdf") or ""),
            str(record.get("hf_split") or ""),
            _normalize_text(record.get("question") or ""),
        )
        by_question[key].append(record)

    for duplicate_records in by_id.values():
        if len(duplicate_records) <= 1:
            continue
        ids = [f"{r['hf_split']}:{r['row_idx']}" for r in duplicate_records]
        for record in duplicate_records:
            _append_issue(
                record,
                Issue(
                    "error",
                    "duplicate_id",
                    f"Duplicate id appears at {ids}.",
                    "Give each row a unique id or remove duplicate rows.",
                ),
            )

    for duplicate_records in by_question.values():
        if len(duplicate_records) <= 1:
            continue
        ids = [str(r["id"]) for r in duplicate_records]
        for record in duplicate_records:
            _append_issue(
                record,
                Issue(
                    "warning",
                    "duplicate_question",
                    f"Question text duplicates rows {ids}.",
                    "Confirm the duplicate is intentional or merge/regenerate one row.",
                ),
            )


def _append_issue(record: dict[str, Any], issue: Issue) -> None:
    record["issues"].append(issue.as_dict())
    issue_objs = [Issue(**i) for i in record["issues"]]
    record["status"] = _status_from_issues(issue_objs)
    record["suggested_action"] = _suggested_action(record["status"], issue_objs)
    record["proposed_fix"] = _proposed_fix(record)


def _summarize(records: list[dict[str, Any]], totals_by_split: dict[str, int]) -> dict[str, Any]:
    issue_counts: Counter[str] = Counter()
    issue_severity_counts: Counter[str] = Counter()
    golden_fix_records = 0
    for record in records:
        has_golden_fix = False
        for issue in record["issues"]:
            code = str(issue["code"])
            issue_counts[code] += 1
            issue_severity_counts[str(issue["severity"])] += 1
            has_golden_fix = has_golden_fix or code in GOLDEN_FIX_CODES
        if has_golden_fix:
            golden_fix_records += 1

    canonical_records = [r for r in records if r.get("stress_type") == CANONICAL_STRESS_VALUE]
    return {
        "generated_at_unix": int(time.time()),
        "total_rows_loaded": len(records),
        "hf_totals_by_split": totals_by_split,
        "rows_by_hf_split": dict(Counter(str(r["hf_split"]) for r in records)),
        "rows_by_local_split": dict(Counter(str(r["local_split"]) for r in records)),
        "rows_by_domain": dict(Counter(str(r["domain"]) for r in records)),
        "rows_by_answer_type": dict(Counter(str(r["answer_type"]) for r in records)),
        "rows_by_status": dict(Counter(str(r["status"]) for r in records)),
        "rows_by_stress_type": dict(Counter(str(r["stress_type"]) for r in records)),
        "canonical_row_count": len(canonical_records),
        "stress_row_count": len(records) - len(canonical_records),
        "golden_fix_row_count": golden_fix_records,
        "issue_counts": dict(issue_counts.most_common()),
        "issue_severity_counts": dict(issue_severity_counts),
        "asset_revisions": sorted({r["asset_revision"] for r in records if r["asset_revision"]}),
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, default=_json_default) + "\n")


def _write_artifacts(
    *,
    output_dir: Path,
    report_path: Path,
    records: list[dict[str, Any]],
    summary: dict[str, Any],
    args: argparse.Namespace,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    suspects = [r for r in records if r["status"] != "publishable"]
    golden_fix_suspects = [r for r in records if _has_golden_fix_issue(r)]
    review_packets = [r["review_packet"] for r in records]
    _write_jsonl(output_dir / "audit_rows.jsonl", records)
    _write_jsonl(output_dir / "patch_candidates.jsonl", suspects)
    _write_jsonl(output_dir / "golden_fix_candidates.jsonl", golden_fix_suspects)
    _write_jsonl(output_dir / "review_packets.jsonl", review_packets)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, default=_json_default)
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_render_report(summary, suspects, golden_fix_suspects, args, output_dir))


def _has_golden_fix_issue(record: dict[str, Any]) -> bool:
    return any(str(issue["code"]) in GOLDEN_FIX_CODES for issue in record.get("issues", []))


def _render_report(
    summary: dict[str, Any],
    suspects: list[dict[str, Any]],
    golden_fix_suspects: list[dict[str, Any]],
    args: argparse.Namespace,
    output_dir: Path,
) -> str:
    lines = [
        "# Parser-Bench Golden QA Audit",
        "",
        f"Dataset: `{args.hf_repo}`",
        f"Requested revision: `{args.hf_revision or 'HEAD'}`",
        f"Splits audited: `{', '.join(args.splits)}`",
        f"Rows loaded: `{summary['total_rows_loaded']}`",
        "",
        "## Result",
        "",
        _counter_table("Publishability", summary["rows_by_status"]),
        "",
        _counter_table("Splits", summary["rows_by_hf_split"]),
        "",
        _counter_table("Stress Types", summary["rows_by_stress_type"]),
        "",
        "The deterministic audit found "
        f"`{summary['canonical_row_count']}` canonical rows and "
        f"`{summary['stress_row_count']}` stress rows. FocusParse's current "
        "`src/focusparse/eval/hf_loader.py` filters non-`none` stress rows before "
        "headline evals, so the canonical headline-eval surface is "
        f"`{summary['canonical_row_count']}` rows when all public splits are loaded.",
        "",
        "## Method",
        "",
        "- Loaded row metadata through Hugging Face Dataset Viewer `/rows`, pinned with "
        "`revision` and checked against embedded cached-asset revisions.",
        "- Checked schema, split mapping, answer type/tolerance consistency, page-image "
        "metadata, evidence bbox geometry, multi-region markers, duplicate ids/questions, "
        "and unanswerable consistency.",
        "- Emitted review packets for visual adjudication. This automated pass can find "
        "structural and scorer-facing blockers; it does not independently remeasure every "
        "chart/image value by eye.",
        "",
        "## Pipeline Implications",
        "",
        "- `scripts/run_hf_eval.py` defaults to HF `validation`, which is parser-bench local "
        "`test`, not local `dev`.",
        "- `src/focusparse/eval/hf_loader.py` filters stress rows, while the raw public "
        "dataset keeps them for stress analysis.",
        "- `src/focusparse/eval/scoring.py` extracts the first numeric token for numeric "
        "answers and applies absolute tolerance when present; bad or missing tolerances "
        "directly affect headline accuracy.",
        "- `src/focusparse/eval/harness.py` caches predictions by example id only, so any "
        "gold-question or gold-answer edits require a fresh output directory.",
        "",
        "## Artifacts",
        "",
        f"- Row audit: `{output_dir / 'audit_rows.jsonl'}`",
        f"- Patch candidates: `{output_dir / 'patch_candidates.jsonl'}`",
        f"- Golden/scorer fix candidates: `{output_dir / 'golden_fix_candidates.jsonl'}`",
        f"- Review packets: `{output_dir / 'review_packets.jsonl'}`",
        f"- Summary: `{output_dir / 'summary.json'}`",
        "",
        "## Issue Counts",
        "",
        _counter_table("Issues", summary["issue_counts"]),
        "",
        "## Golden Answer / Scorer Fixes",
        "",
        f"`{summary['golden_fix_row_count']}` rows have high-confidence gold answer, "
        "answer_type, unit, or tolerance fixes. These are the rows most likely to make "
        "an otherwise correct model answer score incorrectly.",
        "",
        _finding_table(golden_fix_suspects),
        "",
        "## Patch-Ready Findings",
        "",
    ]

    if not suspects:
        lines.extend(
            [
                "No rows had deterministic publish blockers. Use `review_packets.jsonl` "
                "for visual adjudication of the gold answers.",
                "",
            ]
        )
    else:
        lines.append(_finding_table(suspects))

    return "\n".join(lines)


def _finding_table(records: list[dict[str, Any]]) -> str:
    if not records:
        return "No rows in this category."
    lines = [
        "| id | split | status | issue codes | proposed answer/question fix |",
        "| --- | --- | --- | --- | --- |",
    ]
    for record in records:
        codes = ", ".join(sorted({issue["code"] for issue in record["issues"]}))
        lines.append(
            "| "
            + " | ".join(
                [
                    _md_cell(record["id"]),
                    _md_cell(record["hf_split"]),
                    _md_cell(record["status"]),
                    _md_cell(codes),
                    _md_cell(record.get("proposed_fix") or record["suggested_action"]),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def _counter_table(title: str, counts: dict[str, int]) -> str:
    if not counts:
        return f"### {title}\n\nNo entries."
    lines = [f"### {title}", "", "| key | count |", "| --- | ---: |"]
    for key, value in counts.items():
        lines.append(f"| {_md_cell(key)} | {value} |")
    return "\n".join(lines)


def _md_cell(value: Any) -> str:
    text = str(value).replace("\n", " ").replace("|", "\\|")
    return WHITESPACE_RE.sub(" ", text).strip()


def _short_text(value: Any, max_len: int) -> str:
    text = WHITESPACE_RE.sub(" ", str(value).strip())
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "..."


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hf-repo", default=DEFAULT_REPO)
    parser.add_argument("--hf-revision", default=DEFAULT_REVISION)
    parser.add_argument(
        "--splits",
        default=",".join(DEFAULT_SPLITS),
        help="Comma-separated HF splits, e.g. train,validation,test.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum rows to audit across all requested splits, in split order.",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--timeout-s", type=float, default=60.0)
    parser.add_argument(
        "--page-size",
        type=int,
        default=1,
        help="Dataset Viewer rows per request. Keep small for image-heavy datasets.",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=4,
        help="Retries for transient Dataset Viewer 429/5xx/network errors.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Fetch and audit rows, print summary, but do not write artifacts.",
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=50,
        help="Print fetch progress every N rows per split. Set 0 to silence.",
    )
    parser.add_argument(
        "--request-delay-s",
        type=float,
        default=1.0,
        help="Delay between Dataset Viewer row requests to avoid public API rate limits.",
    )
    args = parser.parse_args(argv)
    args.splits = [s.strip() for s in str(args.splits).split(",") if s.strip()]
    unknown_splits = sorted(set(args.splits) - set(DEFAULT_SPLITS))
    if unknown_splits:
        parser.error(f"unsupported split(s): {unknown_splits}; expected {DEFAULT_SPLITS}")
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be positive when provided")
    if args.retries < 0:
        parser.error("--retries must be non-negative")
    if args.page_size <= 0 or args.page_size > 100:
        parser.error("--page-size must be between 1 and 100")
    if args.progress_interval < 0:
        parser.error("--progress-interval must be non-negative")
    if args.request_delay_s < 0:
        parser.error("--request-delay-s must be non-negative")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    rows, totals = _fetch_rows(
        repo=args.hf_repo,
        revision=args.hf_revision,
        splits=args.splits,
        limit=args.limit,
        timeout_s=args.timeout_s,
        retries=args.retries,
        page_size=args.page_size,
        progress_interval=args.progress_interval,
        request_delay_s=args.request_delay_s,
        fetch_cache_dir=None if args.dry_run else args.output_dir / "fetch_cache",
    )
    records = [_audit_row(row) for row in rows]
    _apply_duplicate_checks(records)
    summary = _summarize(records, totals)

    requested_revision = args.hf_revision
    observed_revisions = set(summary.get("asset_revisions") or [])
    if requested_revision and observed_revisions and observed_revisions != {requested_revision}:
        print(
            "warning: requested revision does not match cached asset revisions: "
            f"requested={requested_revision} observed={sorted(observed_revisions)}",
            file=sys.stderr,
        )

    if args.dry_run:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0

    _write_artifacts(
        output_dir=args.output_dir,
        report_path=args.report_path,
        records=records,
        summary=summary,
        args=args,
    )
    print(f"Wrote audit artifacts to {args.output_dir}")
    print(f"Wrote report to {args.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
