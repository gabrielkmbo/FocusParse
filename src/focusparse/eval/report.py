"""Small HTML report generator for completed FocusParse runs."""

from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any


def render_run_report(run_dir: Path) -> Path:
    """Render an HTML report for a completed run. Returns the path to index.html."""
    manifest_path = run_dir if run_dir.is_file() else run_dir / "run.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"run manifest not found: {manifest_path}")

    manifest = json.loads(manifest_path.read_text())
    output_dir = manifest_path.parent
    report_path = output_dir / "index.html"

    title = _run_title(manifest, output_dir)
    parts = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{escape(title)}</title>",
        "<style>",
        _CSS,
        "</style>",
        "</head>",
        "<body>",
        f"<h1>{escape(title)}</h1>",
        _section("Run", _table(_run_rows(manifest))),
    ]

    aggregate = manifest.get("aggregate") or manifest.get("overall")
    if isinstance(aggregate, dict):
        parts.append(_section("Aggregate", _table(_dict_rows(aggregate))))

    by_domain = manifest.get("aggregate_by_domain")
    if isinstance(by_domain, dict) and by_domain:
        domain_rows: list[tuple[str, str]] = []
        for domain, metrics in by_domain.items():
            if isinstance(metrics, dict):
                summary = ", ".join(
                    f"{key}={_format_value(value)}"
                    for key, value in metrics.items()
                    if key in {"n", "accuracy", "page_recall_mean", "bbox_iou_mean"}
                )
                domain_rows.append((str(domain), summary))
        parts.append(_section("Domains", _table(domain_rows)))

    stage_aggregate = manifest.get("stage_aggregate")
    if isinstance(stage_aggregate, dict) and stage_aggregate:
        parts.append(_section("Stage Aggregate", _table(_dict_rows(stage_aggregate))))

    parts.extend(["</body>", "</html>"])
    report_path.write_text("\n".join(parts))
    return report_path


def _run_title(manifest: dict[str, Any], output_dir: Path) -> str:
    agent = manifest.get("agent")
    protocol = manifest.get("protocol")
    model = manifest.get("model")
    bits = [str(value) for value in (agent, protocol, model) if value]
    return " / ".join(bits) if bits else output_dir.name


def _run_rows(manifest: dict[str, Any]) -> list[tuple[str, str]]:
    keys = [
        "agent",
        "backend",
        "model",
        "protocol",
        "tool_set",
        "n_examples",
        "limit",
        "started_at",
        "ended_at",
    ]
    return [(key, _format_value(manifest[key])) for key in keys if key in manifest]


def _dict_rows(values: dict[str, Any]) -> list[tuple[str, str]]:
    return [(str(key), _format_value(value)) for key, value in values.items()]


def _format_value(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.4g}"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_format_value(item) for item in value) + "]"
    if isinstance(value, dict):
        return ", ".join(f"{key}: {_format_value(val)}" for key, val in value.items())
    return str(value)


def _section(title: str, body: str) -> str:
    return f"<section><h2>{escape(title)}</h2>{body}</section>"


def _table(rows: list[tuple[str, str]]) -> str:
    body = "\n".join(
        f"<tr><th>{escape(label)}</th><td>{escape(value)}</td></tr>" for label, value in rows
    )
    return f"<table>{body}</table>"


_CSS = """
body {
  color: #17202a;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  line-height: 1.45;
  margin: 2rem auto;
  max-width: 960px;
  padding: 0 1rem;
}
h1 {
  font-size: 1.8rem;
  margin-bottom: 1.5rem;
}
h2 {
  border-bottom: 1px solid #d8dee4;
  font-size: 1.1rem;
  margin-top: 2rem;
  padding-bottom: 0.35rem;
}
table {
  border-collapse: collapse;
  width: 100%;
}
th,
td {
  border-bottom: 1px solid #eaeef2;
  padding: 0.5rem;
  text-align: left;
  vertical-align: top;
}
th {
  width: 220px;
}
""".strip()
