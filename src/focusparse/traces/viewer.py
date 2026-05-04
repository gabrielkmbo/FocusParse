"""HTML trace viewer — pure functions for prediction → self-contained HTML.

The CLI entrypoint lives at `scripts/visualize_trace.py`. This module is the
testable core: crop / page resolution and the HTML render. Vanilla JS +
Tailwind CDN; the output works under `file://` (the only external request is
Tailwind, which is harmless).
"""

from __future__ import annotations

import base64
import html
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

DEFAULT_STAGING_ROOT = Path.home() / ".cache" / "focusparse" / "hf_staging"


# ---------------------------------------------------------------------------
# Resolution helpers
# ---------------------------------------------------------------------------


def example_id_to_doc_stem(example_id: str) -> str:
    """`dat-AN040_EN-0008` -> `AN040_EN`. `fin-10-K-0010` -> `10-K`.

    The benchmark IDs are `<domain-prefix>-<doc_stem>-<NNNN>`. We strip the
    leading domain prefix (`dat-` / `fin-`) and the trailing `-NNNN`. The
    remaining slug matches the `processed/<stem>/images/<stem>_page_*.png`
    on-disk layout.
    """
    parts = example_id.split("-")
    if len(parts) >= 3 and parts[0] in ("dat", "fin"):
        return "-".join(parts[1:-1])
    if len(parts) >= 2:
        return "-".join(parts[:-1])
    return example_id


def find_page_image(
    example_id: str,
    page: int,
    *,
    staging_root: Path = DEFAULT_STAGING_ROOT,
) -> Path | None:
    """Resolve a page image for `(example_id, page)` to a PNG path.

    Walks the canonical `processed/<doc_stem>/images/` layout the parser-bench
    HF dataset materializes into. Returns None when not found — caller should
    skip rendering that overlay rather than fail.
    """
    stem = example_id_to_doc_stem(example_id)
    images_dir = staging_root / "data" / "processed" / stem / "images"
    if not images_dir.is_dir():
        return None
    candidates = list(images_dir.glob(f"*_page_{page:04d}_*.png"))
    if not candidates:
        return None
    return candidates[0]


def resolve_crop_ref(ref: str | None, *, search_dirs: Iterable[Path]) -> Path | None:
    """Resolve an `EvidencePacketSummary.local_crop_ref` to a PNG path.

    Refs come in three shapes in the wild:
      1. An absolute or relative path that exists as-is (literal).
      2. A bare sha256 stem (the content-addressed cache key).
      3. A path-with-extension under one of the search dirs.

    We try each interpretation in order. None on any failure.
    """
    if not ref:
        return None
    direct = Path(ref)
    if direct.is_file():
        return direct
    for d in search_dirs:
        if not d or not Path(d).is_dir():
            continue
        for candidate in (
            Path(d) / ref,
            Path(d) / f"{ref}.png",
            Path(d) / direct.name,
        ):
            if candidate.is_file():
                return candidate
    return None


def image_to_data_url(path: Path) -> str:
    """Return `data:image/png;base64,...` for the given PNG path."""
    blob = path.read_bytes()
    encoded = base64.b64encode(blob).decode("ascii")
    return f"data:image/png;base64,{encoded}"


# ---------------------------------------------------------------------------
# View-model builder
# ---------------------------------------------------------------------------


def build_view_model(
    record: dict[str, Any],
    *,
    search_dirs: Iterable[Path],
    staging_root: Path = DEFAULT_STAGING_ROOT,
) -> dict[str, Any]:
    """Project one per-example prediction record into the JS-side data shape.

    All images are inlined as data URLs (or omitted if unresolvable). The
    result is small enough (~200-500 KB) to embed in a single HTML file.
    """
    trace = record.get("trace") or {}
    steps = trace.get("steps") or []
    snapshot = trace.get("evidence_snapshot")

    citations = record.get("citations") or []
    citation_pages = sorted({int(c["page"]) for c in citations if "page" in c})

    pages_view: list[dict[str, Any]] = []
    for page in citation_pages:
        img_path = find_page_image(record.get("example_id", ""), page, staging_root=staging_root)
        page_citations = [
            {"bbox": list(c.get("bbox", [0, 0, 1, 1]))}
            for c in citations
            if int(c.get("page", -1)) == page
        ]
        pages_view.append(
            {
                "page": page,
                "image_data_url": image_to_data_url(img_path) if img_path else None,
                "citations": page_citations,
            }
        )

    snapshot_view: list[dict[str, Any]] = []
    if isinstance(snapshot, list):
        for pkt in snapshot:
            crop_path = resolve_crop_ref(pkt.get("local_crop_ref"), search_dirs=search_dirs)
            linked = []
            for ref in pkt.get("linked_crop_refs") or []:
                linked_path = resolve_crop_ref(ref, search_dirs=search_dirs)
                if linked_path is not None:
                    linked.append(image_to_data_url(linked_path))
            snapshot_view.append(
                {
                    "packet_id": pkt.get("packet_id"),
                    "page": pkt.get("page"),
                    "bbox_norm": list(pkt.get("bbox_norm") or [0, 0, 1, 1]),
                    "region_type": pkt.get("region_type"),
                    "confidence": pkt.get("confidence"),
                    "provenance_tool": pkt.get("provenance_tool"),
                    "text_layer_snippet": pkt.get("text_layer_snippet"),
                    "ocr_snippet": pkt.get("ocr_snippet"),
                    "crop_data_url": (image_to_data_url(crop_path) if crop_path else None),
                    "linked_data_urls": linked,
                }
            )

    return {
        "example_id": record.get("example_id"),
        "domain": record.get("domain"),
        "protocol": record.get("protocol"),
        "question": (trace.get("question") if isinstance(trace, dict) else None)
        or record.get("question"),
        "answer_pred": record.get("answer_pred"),
        "answer_gold": record.get("answer_gold"),
        "answer_correct": record.get("answer_correct"),
        "is_lazy": record.get("is_lazy"),
        "page_recall": record.get("page_recall"),
        "bbox_iou": record.get("bbox_iou"),
        "evidence_reward": record.get("evidence_reward"),
        "tool_calls": record.get("tool_calls"),
        "tokens_in": record.get("tokens_in"),
        "tokens_out": record.get("tokens_out"),
        "usd": record.get("usd"),
        "latency_ms": record.get("latency_ms"),
        "citations": citations,
        "steps": steps,
        "evidence_snapshot": snapshot_view,
        "pages": pages_view,
    }


# ---------------------------------------------------------------------------
# HTML render
# ---------------------------------------------------------------------------


def render_html(view_model: dict[str, Any], *, title: str | None = None) -> str:
    """One self-contained HTML page rendering a single trace.

    Vanilla JS reads `const VIEW = {...}` and produces the timeline + cards.
    Tailwind via CDN handles styling — fine under file:// (the only external
    request).
    """
    payload = json.dumps(view_model, indent=2, default=str)
    page_title = html.escape(title or f"Trace · {view_model.get('example_id', '?')}")
    return _HTML_TEMPLATE.replace("{{TITLE}}", page_title).replace("{{PAYLOAD}}", payload)


_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>{{TITLE}}</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    body { font-family: -apple-system, system-ui, sans-serif; }
    .bbox-overlay {
      position: absolute; border: 2px solid; pointer-events: none;
    }
    .stage-plan { background-color: #fde68a; }
    .stage-route_pages { background-color: #fcd34d; }
    .stage-localize { background-color: #c4b5fd; }
    .stage-rerank { background-color: #a78bfa; }
    .stage-inspect { background-color: #93c5fd; }
    .stage-expand_context { background-color: #6ee7b7; }
    .stage-answer { background-color: #fca5a5; }
    .stage-verify { background-color: #f9a8d4; }
    .stage-react_step { background-color: #bae6fd; }
    .stage-react_final { background-color: #fb923c; }
    .stage-simple_answer { background-color: #fca5a5; }
    .tier-frontier { font-weight: bold; }
    .tier-skipped { opacity: 0.5; }
  </style>
</head>
<body class="bg-slate-50 p-6 max-w-7xl mx-auto">
  <div id="root">Loading…</div>
  <script>
    const VIEW = {{PAYLOAD}};

    function el(tag, attrs, ...children) {
      const node = document.createElement(tag);
      for (const [k, v] of Object.entries(attrs || {})) {
        if (k === 'class') node.className = v;
        else if (k === 'style' && typeof v === 'object') Object.assign(node.style, v);
        else if (k === 'html') node.innerHTML = v;
        else node.setAttribute(k, v);
      }
      for (const c of children.flat()) {
        if (c == null) continue;
        node.append(c instanceof Node ? c : String(c));
      }
      return node;
    }

    function fmt(v, digits) {
      if (v == null) return '—';
      if (typeof v === 'number') return digits != null ? v.toFixed(digits) : v.toString();
      return String(v);
    }

    function asMoney(v) {
      if (v == null) return '—';
      return '$' + Number(v).toFixed(4);
    }

    function header() {
      const correctText = VIEW.answer_correct == null ? '—'
        : (VIEW.answer_correct >= 1.0 ? '✓ correct' : '✗ wrong');
      const lazyText = VIEW.is_lazy ? ' · lazy' : '';
      return el('div', { class: 'bg-white rounded shadow p-4 mb-6' },
        el('div', { class: 'flex items-baseline justify-between mb-2' },
          el('h1', { class: 'text-2xl font-bold' }, VIEW.example_id || '?'),
          el('div', { class: 'text-sm text-slate-500' },
            (VIEW.domain || '?'), ' · ', (VIEW.protocol || '?')
          )
        ),
        el('div', { class: 'text-lg mb-3' }, 'Q: ', VIEW.question || '?'),
        el('div', { class: 'grid grid-cols-2 gap-3 text-sm' },
          el('div', {},
            el('div', { class: 'font-semibold' }, 'predicted'),
            el('div', { class: 'p-2 bg-slate-100 rounded font-mono' }, VIEW.answer_pred || '—')),
          el('div', {},
            el('div', { class: 'font-semibold' }, 'gold'),
            el('div', { class: 'p-2 bg-slate-100 rounded font-mono' }, VIEW.answer_gold || '—'))
        ),
        el('div', { class: 'mt-3 grid grid-cols-4 gap-3 text-sm' },
          metric('result', correctText + lazyText, VIEW.answer_correct >= 1 ? 'text-emerald-600' : 'text-red-600'),
          metric('bbox_iou', fmt(VIEW.bbox_iou, 3)),
          metric('page_recall', fmt(VIEW.page_recall, 3)),
          metric('evidence_reward', fmt(VIEW.evidence_reward, 3)),
          metric('tool_calls', fmt(VIEW.tool_calls)),
          metric('tokens', `${VIEW.tokens_in||0} → ${VIEW.tokens_out||0}`),
          metric('usd', asMoney(VIEW.usd)),
          metric('latency', `${VIEW.latency_ms||0} ms`)
        )
      );
    }

    function metric(label, value, valueClass) {
      return el('div', {},
        el('div', { class: 'text-slate-500 uppercase text-xs' }, label),
        el('div', { class: valueClass || 'font-medium' }, value)
      );
    }

    function timeline() {
      if (!VIEW.steps || !VIEW.steps.length) {
        return el('div', { class: 'p-4 text-slate-500' }, 'No steps recorded.');
      }
      return el('div', { class: 'bg-white rounded shadow p-4 mb-6' },
        el('h2', { class: 'text-xl font-bold mb-3' }, 'Trajectory'),
        el('div', { class: 'space-y-2' },
          VIEW.steps.map(stepCard)
        )
      );
    }

    function stepCard(step, i) {
      const stageClass = 'stage-' + (step.stage || 'unknown');
      const tierClass = 'tier-' + (step.tier || 'unknown');
      const summary = step.obs_summary;
      const argsBox = el('pre', { class: 'mt-2 text-xs bg-slate-50 p-2 rounded overflow-auto max-h-64' },
        JSON.stringify(step.args || {}, null, 2)
      );
      const summaryBox = summary
        ? el('div', { class: 'mt-2' },
            el('div', { class: 'text-xs uppercase text-slate-500' }, 'observation'),
            el('div', { class: 'text-sm bg-amber-50 p-2 rounded font-mono' }, summary))
        : null;
      const meta = [
        step.tool ? `tool=${step.tool}` : null,
        step.tokens_in ? `${step.tokens_in}→${step.tokens_out||0} tok` : null,
        step.usd ? '$' + Number(step.usd).toFixed(4) : null,
        step.latency_ms ? `${step.latency_ms}ms` : null,
        step.confidence != null ? `conf=${Number(step.confidence).toFixed(2)}` : null,
      ].filter(Boolean).join(' · ');
      return el('details', { class: `border rounded ${tierClass}` },
        el('summary', { class: `cursor-pointer p-2 ${stageClass}` },
          el('span', { class: 'font-mono text-xs mr-2' }, `#${step.step_index ?? i}`),
          el('span', { class: 'font-semibold' }, step.stage || '?'),
          el('span', { class: 'mx-2 text-slate-700' }, '·'),
          el('span', {}, step.action || '?'),
          el('span', { class: 'ml-3 text-slate-500 text-sm' }, meta)
        ),
        el('div', { class: 'p-3' },
          summaryBox,
          argsBox
        )
      );
    }

    function evidenceSnapshot() {
      const snap = VIEW.evidence_snapshot || [];
      if (!snap.length) {
        return el('div', { class: 'p-4 text-slate-500' }, 'No evidence_snapshot in this trace (v1, or comparator with no citations).');
      }
      return el('div', { class: 'bg-white rounded shadow p-4 mb-6' },
        el('h2', { class: 'text-xl font-bold mb-3' }, `Evidence packets (${snap.length})`),
        el('div', { class: 'grid grid-cols-2 gap-3' },
          snap.map(packetCard)
        )
      );
    }

    function packetCard(pkt) {
      const bbox = (pkt.bbox_norm || []).map(v => Number(v).toFixed(3)).join(', ');
      const text = pkt.text_layer_snippet || pkt.ocr_snippet;
      return el('div', { class: 'border rounded p-3' },
        el('div', { class: 'flex justify-between items-baseline mb-2' },
          el('div', { class: 'font-mono text-sm' }, pkt.packet_id),
          el('div', { class: 'text-xs text-slate-500' },
            `page ${pkt.page} · ${pkt.region_type || '?'} · conf=${fmt(pkt.confidence, 2)}`)
        ),
        el('div', { class: 'text-xs text-slate-500 mb-2' }, `[${bbox}]`),
        pkt.crop_data_url
          ? el('img', { src: pkt.crop_data_url, class: 'max-w-full rounded mb-2' })
          : el('div', { class: 'p-3 bg-slate-100 rounded text-slate-500 text-sm mb-2' }, '(no crop)'),
        text ? el('div', { class: 'text-sm bg-amber-50 p-2 rounded font-mono whitespace-pre-wrap' }, text) : null,
        pkt.provenance_tool ? el('div', { class: 'text-xs text-slate-400 mt-2' }, 'tool: ' + pkt.provenance_tool) : null
      );
    }

    function pagesPanel() {
      const pages = VIEW.pages || [];
      if (!pages.length) {
        return el('div', { class: 'p-4 text-slate-500' }, 'No cited pages.');
      }
      return el('div', { class: 'bg-white rounded shadow p-4 mb-6' },
        el('h2', { class: 'text-xl font-bold mb-3' }, 'Cited pages'),
        el('div', { class: 'grid grid-cols-1 gap-4' },
          pages.map(pageOverlay)
        )
      );
    }

    function pageOverlay(p) {
      if (!p.image_data_url) {
        return el('div', { class: 'p-3 bg-slate-100 rounded' },
          `Page ${p.page} (image not found in staging)`);
      }
      const wrapper = el('div', { class: 'relative inline-block max-w-full' });
      const img = el('img', { src: p.image_data_url, class: 'max-w-full' });
      wrapper.appendChild(img);
      const overlay = el('div', { class: 'absolute inset-0' });
      wrapper.appendChild(overlay);
      img.addEventListener('load', () => {
        const w = img.clientWidth, h = img.clientHeight;
        overlay.style.width = w + 'px';
        overlay.style.height = h + 'px';
        for (const c of (p.citations || [])) {
          const [x0, y0, x1, y1] = c.bbox || [0, 0, 1, 1];
          const box = el('div', {
            class: 'bbox-overlay',
            style: {
              left: (x0 * w) + 'px',
              top: (y0 * h) + 'px',
              width: ((x1 - x0) * w) + 'px',
              height: ((y1 - y0) * h) + 'px',
              borderColor: '#dc2626',
            }
          });
          overlay.appendChild(box);
        }
      });
      return el('div', {},
        el('div', { class: 'text-sm font-medium mb-1' }, `Page ${p.page} · ${(p.citations||[]).length} citation(s)`),
        wrapper
      );
    }

    document.getElementById('root').replaceWith(
      el('div', {},
        header(),
        pagesPanel(),
        evidenceSnapshot(),
        timeline()
      )
    );
  </script>
</body>
</html>
"""
