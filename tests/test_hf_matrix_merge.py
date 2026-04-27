"""Tests for `scripts/run_hf_matrix.py` — merge + grouping logic.

Covers the pure helpers (`_build_group_key`, `_extract_cell`, `_merge_cell`,
`_build_specs`, `_build_cmd`). The subprocess dispatch in `main()` needs real
evals to exercise end-to-end; that's covered by the manual Phase C check in
the plan (`--phase a --limit 3` against a live HF dataset).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_hf_matrix.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("_run_hf_matrix_under_test", SCRIPT_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def matrix_mod():
    return _load_script_module()


def _make_run_json(
    *,
    agent: str,
    protocol: str,
    tier_sha8: str,
    accuracy: float = 0.5,
    count: int = 10,
    focus_extras: bool = False,
) -> dict:
    overall = {
        "accuracy": accuracy,
        "abstain_rate": 0.1,
        "page_recall": 0.9,
        "bbox_iou": 0.6,
        "count": count,
        "total_cost_usd": 1.23,
        "cost_per_correct_usd": 0.24,
        "total_input_tokens": 1000,
        "total_output_tokens": 500,
        "evidence_reward_mean": 0.42 if focus_extras else None,
        "lazy_answer_rate": 0.1 if focus_extras else None,
        "tool_calls_mean": 2.5 if focus_extras else None,
    }
    return {
        "config_key": f"focusparse_{agent}_{protocol}_{tier_sha8}",
        "agent": agent,
        "protocol": protocol,
        "tier_sha8": tier_sha8,
        "resolved_tiers": {"reasoner": {"provider": "openai", "model": "gpt-5.4"}},
        "hf_repo": "gabrielbo/parser-bench",
        "hf_split": "validation",
        "hf_revision": None,
        "dataset_fingerprint": {"num_rows": count, "fingerprint": "abc123"},
        "overall": overall,
    }


# ---------------------------------------------------------------------------
# _build_group_key
# ---------------------------------------------------------------------------


def test_group_key_simple_omits_profile(matrix_mod):
    k = matrix_mod._build_group_key(agent="simple", tier_sha8="abc12345", tier_profile=None)
    assert k == "focusparse_simple_abc12345"


def test_group_key_focus_embeds_profile(matrix_mod):
    k = matrix_mod._build_group_key(agent="focus", tier_sha8="deadbeef", tier_profile="balanced")
    assert k == "focusparse_focus_balanced_deadbeef"


def test_group_key_distinct_profiles_distinct_keys(matrix_mod):
    # Even if tier_sha8s collide (they shouldn't), profile names distinguish.
    a = matrix_mod._build_group_key(agent="focus", tier_sha8="11111111", tier_profile="cheap_only")
    b = matrix_mod._build_group_key(agent="focus", tier_sha8="11111111", tier_profile="frontier")
    assert a != b


# ---------------------------------------------------------------------------
# _extract_cell
# ---------------------------------------------------------------------------


def test_extract_cell_drops_null_focus_extras(matrix_mod):
    overall = _make_run_json(agent="simple", protocol="oracle_crop", tier_sha8="abc12345")[
        "overall"
    ]
    cell = matrix_mod._extract_cell(overall)
    # parser-bench parity: simple rows don't carry focus-specific keys at all
    assert "evidence_reward_mean" not in cell
    assert "lazy_answer_rate" not in cell
    assert "tool_calls_mean" not in cell
    assert cell["accuracy"] == 0.5
    assert cell["count"] == 10
    assert cell["total_input_tokens"] == 1000


def test_extract_cell_keeps_focus_extras_when_populated(matrix_mod):
    overall = _make_run_json(
        agent="focus",
        protocol="focus_default",
        tier_sha8="deadbeef",
        focus_extras=True,
    )["overall"]
    cell = matrix_mod._extract_cell(overall)
    assert cell["evidence_reward_mean"] == 0.42
    assert cell["lazy_answer_rate"] == 0.1
    assert cell["tool_calls_mean"] == 2.5


def test_extract_cell_handles_missing_optional_fields(matrix_mod):
    overall = {
        "accuracy": 0.3,
        "abstain_rate": 0.0,
        "page_recall": 0.5,
        "bbox_iou": 0.2,
        "count": 5,
        # no total_cost_usd, no tokens
    }
    cell = matrix_mod._extract_cell(overall)
    assert cell["total_cost_usd"] is None
    assert cell["cost_per_correct_usd"] is None
    assert cell["total_input_tokens"] == 0
    assert cell["total_output_tokens"] == 0


# ---------------------------------------------------------------------------
# _merge_cell — groups simple protocols under one key, focus rows under their own
# ---------------------------------------------------------------------------


def test_merge_cell_groups_simple_protocols_under_one_key(matrix_mod):
    summary = {"results": {}, "dataset_fingerprint": None}
    sha = "abc12345"
    for proto in ("full_doc", "oracle_page", "oracle_crop"):
        data = _make_run_json(agent="simple", protocol=proto, tier_sha8=sha)
        matrix_mod._merge_cell(summary, data, tier_profile=None)

    assert set(summary["results"]) == {"focusparse_simple_abc12345"}
    nested = summary["results"]["focusparse_simple_abc12345"]
    assert set(nested) == {"full_doc", "oracle_page", "oracle_crop"}


def test_merge_cell_stamps_fingerprint_once(matrix_mod):
    summary = {"results": {}, "dataset_fingerprint": None}
    data = _make_run_json(agent="simple", protocol="full_doc", tier_sha8="aaa00000")
    matrix_mod._merge_cell(summary, data, tier_profile=None)
    assert summary["dataset_fingerprint"] == {"num_rows": 10, "fingerprint": "abc123"}

    # Second merge with a different fingerprint → first one wins.
    data2 = _make_run_json(agent="simple", protocol="oracle_page", tier_sha8="aaa00000")
    data2["dataset_fingerprint"] = {"num_rows": 99, "fingerprint": "changed"}
    matrix_mod._merge_cell(summary, data2, tier_profile=None)
    assert summary["dataset_fingerprint"] == {"num_rows": 10, "fingerprint": "abc123"}


def test_merge_cell_preserves_existing_keys(matrix_mod):
    """Re-running `--phase a` after `--phase b` must not clobber phase-b."""
    summary = {
        "results": {
            "focusparse_focus_balanced_deadbeef": {"focus_default": {"accuracy": 0.7, "count": 10}}
        },
        "dataset_fingerprint": {"num_rows": 10},
    }
    data = _make_run_json(agent="simple", protocol="full_doc", tier_sha8="aaa00000")
    matrix_mod._merge_cell(summary, data, tier_profile=None)

    assert "focusparse_focus_balanced_deadbeef" in summary["results"]
    assert "focusparse_simple_aaa00000" in summary["results"]
    assert (
        summary["results"]["focusparse_focus_balanced_deadbeef"]["focus_default"]["accuracy"] == 0.7
    )


def test_merge_cell_rerun_same_config_overwrites_protocol(matrix_mod):
    summary = {"results": {}, "dataset_fingerprint": None}
    data1 = _make_run_json(agent="simple", protocol="full_doc", tier_sha8="aaa00000", accuracy=0.5)
    data2 = _make_run_json(agent="simple", protocol="full_doc", tier_sha8="aaa00000", accuracy=0.8)
    matrix_mod._merge_cell(summary, data1, tier_profile=None)
    matrix_mod._merge_cell(summary, data2, tier_profile=None)
    cell = summary["results"]["focusparse_simple_aaa00000"]["full_doc"]
    assert cell["accuracy"] == 0.8  # overwritten, not appended


def test_merge_cell_focus_with_profile_nests_under_labeled_group(matrix_mod):
    summary = {"results": {}, "dataset_fingerprint": None}
    data = _make_run_json(
        agent="focus",
        protocol="focus_default",
        tier_sha8="deadbeef",
        focus_extras=True,
    )
    matrix_mod._merge_cell(summary, data, tier_profile="balanced")

    key = "focusparse_focus_balanced_deadbeef"
    assert key in summary["results"]
    assert "focus_default" in summary["results"][key]
    assert summary["results"][key]["focus_default"]["evidence_reward_mean"] == 0.42


# ---------------------------------------------------------------------------
# _build_specs
# ---------------------------------------------------------------------------


def test_build_specs_phase_a_only(matrix_mod):
    specs = matrix_mod._build_specs(phases=["a"], focus_tiers="balanced")
    # Default Phase A now covers parser-bench's 5 protocols + our `full_doc`.
    expected = [
        "full_doc",
        "oracle_page",
        "oracle_crop",
        "tiled_2up",
        "tiled_4up",
        "tiled_8up",
    ]
    assert [s["protocol"] for s in specs] == expected
    assert all(s["agent"] == "simple" for s in specs)
    assert all("tier_profile" not in s for s in specs)


def test_build_specs_phase_a_with_subset_protocols(matrix_mod):
    """`--simple-protocols` subsets Phase A to a comma-separated list."""
    specs = matrix_mod._build_specs(
        phases=["a"],
        focus_tiers="balanced",
        simple_protocols="oracle_crop,tiled_4up",
    )
    assert [s["protocol"] for s in specs] == ["oracle_crop", "tiled_4up"]


def test_build_specs_phase_b_expands_focus_tiers(matrix_mod):
    specs = matrix_mod._build_specs(phases=["b"], focus_tiers="cheap_only,frontier")
    assert len(specs) == 2
    assert all(s["agent"] == "focus" for s in specs)
    assert all(s["protocol"] == "focus_default" for s in specs)
    assert [s["tier_profile"] for s in specs] == ["cheap_only", "frontier"]


def test_build_specs_phase_a_and_b(matrix_mod):
    specs = matrix_mod._build_specs(phases=["a", "b"], focus_tiers="balanced")
    # Default phase A = 6 simple specs + phase B balanced = 1 focus.
    assert len(specs) == 7
    agents = [s["agent"] for s in specs]
    assert agents.count("simple") == 6
    assert agents.count("focus") == 1


def test_build_specs_rejects_unknown_tier_profile(matrix_mod):
    with pytest.raises(ValueError, match="Unknown tier profile"):
        matrix_mod._build_specs(phases=["b"], focus_tiers="not_a_real_profile")


def test_build_specs_empty_when_no_phases(matrix_mod):
    assert matrix_mod._build_specs(phases=[], focus_tiers="balanced") == []


# ---------------------------------------------------------------------------
# _build_cmd
# ---------------------------------------------------------------------------


def test_build_cmd_simple_row(matrix_mod, tmp_path):
    cmd = matrix_mod._build_cmd(
        {"agent": "simple", "protocol": "full_doc"},
        output_dir=tmp_path,
        staging_dir=tmp_path / "staging",
        limit=5,
        hf_revision=None,
        resume=True,
    )
    assert "--agent" in cmd
    assert "simple" in cmd
    assert "--protocol" in cmd
    assert "full_doc" in cmd
    assert "--limit" in cmd and "5" in cmd
    # No tier overrides for simple default
    assert "--tier-override" not in cmd
    # resume=True → no --no-resume flag
    assert "--no-resume" not in cmd


def test_build_cmd_focus_row_emits_tier_overrides(matrix_mod, tmp_path):
    cmd = matrix_mod._build_cmd(
        {"agent": "focus", "protocol": "focus_default", "tier_profile": "cheap_only"},
        output_dir=tmp_path,
        staging_dir=tmp_path,
        limit=None,
        hf_revision=None,
        resume=True,
    )
    # cheap_only overrides all 5 roles
    override_count = sum(1 for c in cmd if c == "--tier-override")
    assert override_count == 5
    # Each override pairs --tier-override with role=tier
    override_idx = [i for i, c in enumerate(cmd) if c == "--tier-override"]
    for i in override_idx:
        assert "=cheap" in cmd[i + 1]


def test_build_cmd_balanced_has_no_overrides(matrix_mod, tmp_path):
    cmd = matrix_mod._build_cmd(
        {"agent": "focus", "protocol": "focus_default", "tier_profile": "balanced"},
        output_dir=tmp_path,
        staging_dir=tmp_path,
        limit=None,
        hf_revision=None,
        resume=True,
    )
    assert "--tier-override" not in cmd


def test_build_cmd_no_resume_emits_flag(matrix_mod, tmp_path):
    cmd = matrix_mod._build_cmd(
        {"agent": "simple", "protocol": "full_doc"},
        output_dir=tmp_path,
        staging_dir=tmp_path,
        limit=None,
        hf_revision=None,
        resume=False,
    )
    assert "--no-resume" in cmd


def test_build_cmd_passes_hf_revision(matrix_mod, tmp_path):
    cmd = matrix_mod._build_cmd(
        {"agent": "simple", "protocol": "full_doc"},
        output_dir=tmp_path,
        staging_dir=tmp_path,
        limit=None,
        hf_revision="v1.2.3",
        resume=True,
    )
    assert "--hf-revision" in cmd
    assert "v1.2.3" in cmd


# ---------------------------------------------------------------------------
# _load_or_init_summary + _find_cell_json
# ---------------------------------------------------------------------------


def test_load_or_init_summary_reads_existing(matrix_mod, tmp_path):
    existing = {
        "generated_at": "2026-04-22T00:00:00+00:00",
        "hf_repo": "gabrielbo/parser-bench",
        "hf_split": "validation",
        "hf_revision": "HEAD",
        "dataset_fingerprint": {"num_rows": 148},
        "limit": None,
        "results": {"focusparse_simple_aaa00000": {"full_doc": {"accuracy": 0.5}}},
    }
    path = tmp_path / "matrix_summary.json"
    path.write_text(json.dumps(existing))
    loaded = matrix_mod._load_or_init_summary(path, hf_revision=None, limit=None)
    assert loaded == existing


def test_load_or_init_summary_builds_fresh_when_missing(matrix_mod, tmp_path):
    path = tmp_path / "matrix_summary.json"
    summary = matrix_mod._load_or_init_summary(path, hf_revision="v1", limit=5)
    assert summary["hf_repo"] == "gabrielbo/parser-bench"
    assert summary["hf_split"] == "validation"
    assert summary["hf_revision"] == "v1"
    assert summary["limit"] == 5
    assert summary["results"] == {}
    assert summary["dataset_fingerprint"] is None


def test_find_cell_json_picks_newest(matrix_mod, tmp_path):
    import time

    older = tmp_path / "focusparse_simple_full_doc_aaa11111.json"
    newer = tmp_path / "focusparse_simple_full_doc_bbb22222.json"
    older.write_text("{}")
    time.sleep(0.01)
    newer.write_text("{}")
    found = matrix_mod._find_cell_json(tmp_path, {"agent": "simple", "protocol": "full_doc"})
    assert found == newer


def test_find_cell_json_ignores_matrix_summary(matrix_mod, tmp_path):
    (tmp_path / "matrix_summary.json").write_text("{}")
    assert matrix_mod._find_cell_json(tmp_path, {"agent": "simple", "protocol": "full_doc"}) is None


def test_find_cell_json_returns_none_when_no_match(matrix_mod, tmp_path):
    (tmp_path / "focusparse_simple_oracle_page_xxx.json").write_text("{}")
    # Looking for different protocol → no match
    assert matrix_mod._find_cell_json(tmp_path, {"agent": "simple", "protocol": "full_doc"}) is None


# ---------------------------------------------------------------------------
# End-to-end merge shape — exercises the complete grouping pipeline
# ---------------------------------------------------------------------------


def test_full_phase_a_merge_matches_parser_bench_shape(matrix_mod, tmp_path):
    """A 3-protocol simple sweep produces one group key with 3 protocol rows,
    matching parser-bench's `gemini_3_1_pro_preview: {full_doc, oracle_page, oracle_crop}`."""
    summary = matrix_mod._load_or_init_summary(
        tmp_path / "matrix_summary.json", hf_revision=None, limit=3
    )
    for proto in ("full_doc", "oracle_page", "oracle_crop"):
        data = _make_run_json(agent="simple", protocol=proto, tier_sha8="abc12345")
        matrix_mod._merge_cell(summary, data, tier_profile=None)

    assert list(summary["results"]) == ["focusparse_simple_abc12345"]
    cells = summary["results"]["focusparse_simple_abc12345"]
    assert list(cells) == ["full_doc", "oracle_page", "oracle_crop"]
    for cell in cells.values():
        assert "accuracy" in cell
        assert "abstain_rate" in cell
        assert "page_recall" in cell
        assert "bbox_iou" in cell
        assert "count" in cell
        assert "total_cost_usd" in cell
        assert "cost_per_correct_usd" in cell
        assert "total_input_tokens" in cell
        assert "total_output_tokens" in cell
