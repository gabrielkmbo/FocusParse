"""Render `headline_table.json` to markdown / HTML for paper figures.

Reads the canonical shape produced by `scripts/run_headline_eval.py` and
emits outputs alongside it:
  * `headline_table.md`  — paper-ready markdown table with CIs
  * `headline_table.html` — quick-look HTML for spot-checking
  * `headline_table.csv` — flat method × domain rows for spreadsheets
  * `headline_table.jsonl` — flat method × domain rows for scripts

Usage:
    uv run python scripts/render_headline_table.py results/hf/headline-v1/headline_table.json
    uv run python scripts/render_headline_table.py results/hf/headline-v1/  # auto-finds the json
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from io import StringIO
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


_DOMAINS_ORDER = ("datasheet", "finance", "_overall")
_DOMAIN_LABELS = {"datasheet": "Datasheets", "finance": "Finance", "_overall": "Overall"}
_CSV_FIELDS = (
    "method",
    "agent",
    "tool_set",
    "domain",
    "missing",
    "n",
    "accuracy",
    "accuracy_ci_low",
    "accuracy_ci_high",
    "usd_per_correct",
    "usd_per_correct_ci_low",
    "usd_per_correct_ci_high",
    "latency_ms_mean",
    "latency_s_mean",
    "bbox_iou",
    "page_recall",
    "usd_total",
)


def _fmt_pct(value: float | None, ci: list[float] | None) -> str:
    if value is None:
        return "—"
    pct = value * 100
    if ci and len(ci) == 2:
        return f"{pct:.1f}% [{ci[0] * 100:.1f}, {ci[1] * 100:.1f}]"
    return f"{pct:.1f}%"


def _fmt_cost(value: float | None, ci: list[float] | None) -> str:
    if value is None:
        return "n/a"
    if ci and len(ci) == 2:
        return f"${value:.4f} [${ci[0]:.4f}, ${ci[1]:.4f}]"
    return f"${value:.4f}"


def _fmt_latency(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{float(value) / 1000:.2f}s"


def _ci_bounds(value: list[float] | None) -> tuple[float | None, float | None]:
    if not value or len(value) != 2:
        return None, None
    return value[0], value[1]


def _flat_rows(table: dict[str, Any]) -> list[dict[str, Any]]:
    """Return one machine-readable row per method × domain cell."""
    rows: list[dict[str, Any]] = []
    for row in table.get("rows", []):
        if row.get("missing"):
            for domain in _DOMAINS_ORDER:
                rows.append(
                    {
                        "method": row.get("label"),
                        "agent": row.get("agent"),
                        "tool_set": row.get("tool_set"),
                        "domain": domain,
                        "missing": True,
                        "n": 0,
                        "accuracy": None,
                        "accuracy_ci_low": None,
                        "accuracy_ci_high": None,
                        "usd_per_correct": None,
                        "usd_per_correct_ci_low": None,
                        "usd_per_correct_ci_high": None,
                        "latency_ms_mean": None,
                        "latency_s_mean": None,
                        "bbox_iou": None,
                        "page_recall": None,
                        "usd_total": None,
                    }
                )
            continue

        by_domain = row.get("by_domain", {})
        for domain in _DOMAINS_ORDER:
            metrics = by_domain.get(domain) or {}
            acc_lo, acc_hi = _ci_bounds(metrics.get("accuracy_ci"))
            usd_lo, usd_hi = _ci_bounds(metrics.get("usd_per_correct_ci"))
            latency_ms = metrics.get("latency_ms_mean")
            rows.append(
                {
                    "method": row.get("label"),
                    "agent": row.get("agent"),
                    "tool_set": row.get("tool_set"),
                    "domain": domain,
                    "missing": False,
                    "n": metrics.get("n", row.get("n_total", 0) if domain == "_overall" else 0),
                    "accuracy": metrics.get("accuracy"),
                    "accuracy_ci_low": acc_lo,
                    "accuracy_ci_high": acc_hi,
                    "usd_per_correct": metrics.get("usd_per_correct"),
                    "usd_per_correct_ci_low": usd_lo,
                    "usd_per_correct_ci_high": usd_hi,
                    "latency_ms_mean": latency_ms,
                    "latency_s_mean": (
                        float(latency_ms) / 1000 if latency_ms is not None else None
                    ),
                    "bbox_iou": metrics.get("bbox_iou"),
                    "page_recall": metrics.get("page_recall"),
                    "usd_total": metrics.get("usd_total"),
                }
            )
    return rows


def _to_csv(table: dict[str, Any]) -> str:
    buf = StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(_CSV_FIELDS), lineterminator="\n")
    writer.writeheader()
    writer.writerows(_flat_rows(table))
    return buf.getvalue()


def _to_jsonl(table: dict[str, Any]) -> str:
    return "\n".join(json.dumps(row, sort_keys=True) for row in _flat_rows(table)) + "\n"


def _to_markdown(table: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"# Headline table — {table.get('protocol', '?')}")
    lines.append("")
    lines.append(f"Generated: {table.get('generated_at', '?')}")
    lines.append("")

    # One-row-per-method × per-domain × accuracy + cost + latency
    header = (
        "| Method | "
        + " | ".join(
            [f"{_DOMAIN_LABELS.get(d, d)} accuracy" for d in _DOMAINS_ORDER if d != "_overall"]
            + [f"{_DOMAIN_LABELS.get(d, d)} $/correct" for d in _DOMAINS_ORDER if d != "_overall"]
            + [f"{_DOMAIN_LABELS.get(d, d)} latency" for d in _DOMAINS_ORDER if d != "_overall"]
        )
        + " | Overall accuracy | Overall latency | n |"
    )
    sep = "|" + "|".join(["---"] * (header.count("|") - 1)) + "|"
    lines.append(header)
    lines.append(sep)

    for row in table.get("rows", []):
        if row.get("missing"):
            cells = ["(missing)"] * (header.count("|") - 2)
            lines.append(f"| **{row['label']}** | " + " | ".join(cells) + " |")
            continue
        by_domain = row.get("by_domain", {})

        acc_cells = []
        cost_cells = []
        latency_cells = []
        for d in _DOMAINS_ORDER:
            if d == "_overall":
                continue
            m = by_domain.get(d) or {}
            acc_cells.append(_fmt_pct(m.get("accuracy"), m.get("accuracy_ci")))
            cost_cells.append(_fmt_cost(m.get("usd_per_correct"), m.get("usd_per_correct_ci")))
            latency_cells.append(_fmt_latency(m.get("latency_ms_mean")))
        overall = by_domain.get("_overall") or {}
        overall_acc = _fmt_pct(overall.get("accuracy"), overall.get("accuracy_ci"))
        overall_latency = _fmt_latency(overall.get("latency_ms_mean"))
        n_total = overall.get("n", row.get("n_total", 0))

        lines.append(
            "| **"
            + row["label"]
            + "** | "
            + " | ".join(acc_cells)
            + " | "
            + " | ".join(cost_cells)
            + " | "
            + " | ".join(latency_cells)
            + f" | {overall_acc} | {overall_latency} | {n_total} |"
        )

    lines.append("")
    lines.append(
        f"_CIs are 95% percentile-bootstrap (1000 resamples, seed=42). "
        f"Protocol: `{table.get('protocol', '?')}`._"
    )
    return "\n".join(lines)


def _to_html(table: dict[str, Any]) -> str:
    """Minimal table HTML for spot-checking. No styling beyond default."""
    rows_html: list[str] = []
    for row in table.get("rows", []):
        if row.get("missing"):
            rows_html.append(
                f"<tr><td><b>{row['label']}</b></td><td colspan='9'><i>missing</i></td></tr>"
            )
            continue
        by_domain = row.get("by_domain", {})
        cells: list[str] = [f"<td><b>{row['label']}</b></td>"]
        for d in _DOMAINS_ORDER:
            if d == "_overall":
                continue
            m = by_domain.get(d) or {}
            cells.append(f"<td>{_fmt_pct(m.get('accuracy'), m.get('accuracy_ci'))}</td>")
        for d in _DOMAINS_ORDER:
            if d == "_overall":
                continue
            m = by_domain.get(d) or {}
            cells.append(
                f"<td>{_fmt_cost(m.get('usd_per_correct'), m.get('usd_per_correct_ci'))}</td>"
            )
        for d in _DOMAINS_ORDER:
            if d == "_overall":
                continue
            m = by_domain.get(d) or {}
            cells.append(f"<td>{_fmt_latency(m.get('latency_ms_mean'))}</td>")
        overall = by_domain.get("_overall") or {}
        cells.append(f"<td>{_fmt_pct(overall.get('accuracy'), overall.get('accuracy_ci'))}</td>")
        cells.append(f"<td>{_fmt_latency(overall.get('latency_ms_mean'))}</td>")
        cells.append(f"<td>{overall.get('n', row.get('n_total', 0))}</td>")
        rows_html.append("<tr>" + "".join(cells) + "</tr>")

    headers = (
        "<tr>"
        + "<th>Method</th>"
        + "".join(
            f"<th>{_DOMAIN_LABELS.get(d, d)} accuracy</th>"
            for d in _DOMAINS_ORDER
            if d != "_overall"
        )
        + "".join(
            f"<th>{_DOMAIN_LABELS.get(d, d)} $/correct</th>"
            for d in _DOMAINS_ORDER
            if d != "_overall"
        )
        + "".join(
            f"<th>{_DOMAIN_LABELS.get(d, d)} latency</th>"
            for d in _DOMAINS_ORDER
            if d != "_overall"
        )
        + "<th>Overall accuracy</th><th>Overall latency</th><th>n</th>"
        + "</tr>"
    )

    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<title>FocusParse headline — {table.get("protocol", "?")}</title>
<style>
table {{ border-collapse: collapse; font-family: -apple-system, sans-serif; font-size: 14px; }}
th, td {{ border: 1px solid #ccc; padding: 6px 12px; text-align: left; }}
th {{ background: #f4f4f4; }}
tr:nth-child(even) td {{ background: #fafafa; }}
caption {{ caption-side: bottom; padding: 8px; color: #555; }}
</style>
</head><body>
<h2>Headline table — protocol: <code>{table.get("protocol", "?")}</code></h2>
<table>
{headers}
{"".join(rows_html)}
<caption>Generated {table.get("generated_at", "?")}. CIs are 95% percentile-bootstrap (n_resamples=1000, seed=42).</caption>
</table>
</body></html>
"""


def _resolve_target(target: Path) -> Path:
    if target.is_dir():
        candidate = target / "headline_table.json"
        if not candidate.exists():
            raise FileNotFoundError(f"No headline_table.json in {target}")
        return candidate
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "target",
        type=Path,
        help="Path to headline_table.json or to a directory containing it.",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    json_path = _resolve_target(args.target)
    table = json.loads(json_path.read_text())

    md_path = json_path.with_suffix(".md")
    md_path.write_text(_to_markdown(table))
    logger.info("Wrote %s", md_path)

    html_path = json_path.with_suffix(".html")
    html_path.write_text(_to_html(table))
    logger.info("Wrote %s", html_path)

    csv_path = json_path.with_suffix(".csv")
    csv_path.write_text(_to_csv(table))
    logger.info("Wrote %s", csv_path)

    jsonl_path = json_path.with_suffix(".jsonl")
    jsonl_path.write_text(_to_jsonl(table))
    logger.info("Wrote %s", jsonl_path)

    print()
    print(_to_markdown(table))
    return 0


if __name__ == "__main__":
    sys.exit(main())
