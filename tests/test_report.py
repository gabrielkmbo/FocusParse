from __future__ import annotations

import json

from focusparse.eval.report import render_run_report


def test_render_run_report_writes_index_html(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "agent": "focus",
                "backend": "openai",
                "model": "gpt-test",
                "protocol": "agentic_multi_page",
                "n_examples": 3,
                "aggregate": {"n": 3, "accuracy": 0.666666, "usd_total": 0.12},
                "aggregate_by_domain": {
                    "datasheet": {"n": 2, "accuracy": 1.0, "page_recall_mean": 0.5}
                },
                "stage_aggregate": {"reasoning": {"calls_mean": 1.0}},
            }
        )
    )

    report_path = render_run_report(run_dir)

    assert report_path == run_dir / "index.html"
    html = report_path.read_text()
    assert "focus / agentic_multi_page / gpt-test" in html
    assert "accuracy" in html
    assert "0.6667" in html
    assert "datasheet" in html


def test_render_run_report_accepts_run_json_path(tmp_path):
    run_json = tmp_path / "run.json"
    run_json.write_text(json.dumps({"agent": "simple", "aggregate": {"n": 1}}))

    report_path = render_run_report(run_json)

    assert report_path == tmp_path / "index.html"
