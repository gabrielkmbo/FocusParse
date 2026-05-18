"""Tests for scripts/run_related_work_protocols.py manifest generation."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import run_related_work_protocols as rwp  # noqa: E402


def _manifest(tmp_path: Path, specs: list[rwp.ProtocolSpec]) -> dict:
    return rwp.build_manifest(
        specs,
        generated_at="2026-05-18T00:00:00+00:00",
        output_root=tmp_path / "runs",
        staging_dir=tmp_path / "staging",
        pdfs_root=None,
        hf_revision=rwp.PINNED_HF_REVISION,
        limit=5,
        resume=True,
        tier_sha8="abc12345",
        resolved_tiers={"reasoner": {"provider": "openai", "model": "gpt-5.4"}},
    )


def test_basic_vlm_manifest_covers_required_protocols(tmp_path: Path) -> None:
    specs = rwp.select_specs(suites=["basic-vlm"], protocols=None, agents=None)
    manifest = _manifest(tmp_path, specs)

    assert [run["protocol"] for run in manifest["runs"]] == list(rwp._PROTOCOLS)
    assert all(run["agent"] == "simple" for run in manifest["runs"])
    assert all(run["tool_set"] == "full" for run in manifest["runs"])
    assert all(run["status"] == "pending" for run in manifest["runs"])

    full_doc = manifest["runs"][0]
    assert full_doc["method_label"] == "Basic VLM / full_doc"
    assert full_doc["expected_config_key"] == "focusparse_simple_full_doc_abc12345"
    assert full_doc["output_dir"].endswith("focusparse_simple_full_doc_abc12345")


def test_commands_pin_hf_revision_and_standard_artifacts(tmp_path: Path) -> None:
    specs = rwp.select_specs(suites=["basic-vlm"], protocols=["oracle_crop"], agents=None)
    manifest = _manifest(tmp_path, specs)
    run = manifest["runs"][0]

    assert "--hf-revision" in run["command_argv"]
    revision_idx = run["command_argv"].index("--hf-revision") + 1
    assert run["command_argv"][revision_idx] == rwp.PINNED_HF_REVISION
    assert "--hf-repo" in run["command_argv"]
    assert "--hf-split" in run["command_argv"]
    assert "--minimal-artifacts" not in run["command_argv"]
    assert run["expected_artifacts"]["wrapper_json"].endswith(
        "focusparse_simple_oracle_crop_abc12345.json"
    )
    assert run["expected_artifacts"]["run_json"].endswith(
        "focusparse_simple_oracle_crop_abc12345/run.json"
    )
    assert run["expected_artifacts"]["per_example_jsonl"].endswith(
        "focusparse_simple_oracle_crop_abc12345/per_example.jsonl"
    )


def test_appendix_comparator_tool_set_suffixes(tmp_path: Path) -> None:
    specs = rwp.select_specs(suites=["appendix-comparators"], protocols=None, agents=None)
    manifest = _manifest(tmp_path, specs)

    by_label = {run["method_label"]: run for run in manifest["runs"]}
    react_min = by_label["ReAct appendix +2 tools / agentic_multi_page"]
    react_full = by_label["ReAct appendix +4 tools / agentic_multi_page"]
    agent_min = by_label["Agent baseline appendix +2 tools / agentic_multi_page"]

    assert react_min["expected_config_key"] == (
        "focusparse_react_agentic_multi_page_abc12345_tminimal"
    )
    assert react_full["expected_config_key"] == "focusparse_react_agentic_multi_page_abc12345"
    assert agent_min["expected_config_key"] == (
        "focusparse_agent_baseline_agentic_multi_page_abc12345_tminimal"
    )
    assert "--tool-set minimal" in react_min["command"]
    assert "--tool-set full" in react_full["command"]


def test_artifact_status_tracks_pending_partial_complete(tmp_path: Path) -> None:
    wrapper = tmp_path / "run.json"
    run_json = tmp_path / "run" / "run.json"
    per_example = tmp_path / "run" / "per_example.jsonl"

    assert (
        rwp.artifact_status(
            wrapper_json=wrapper,
            run_json=run_json,
            per_example_jsonl=per_example,
        )
        == "pending"
    )

    wrapper.write_text("{}")
    assert (
        rwp.artifact_status(
            wrapper_json=wrapper,
            run_json=run_json,
            per_example_jsonl=per_example,
        )
        == "partial"
    )

    run_json.parent.mkdir()
    run_json.write_text("{}")
    per_example.write_text("")
    assert (
        rwp.artifact_status(
            wrapper_json=wrapper,
            run_json=run_json,
            per_example_jsonl=per_example,
        )
        == "complete"
    )
