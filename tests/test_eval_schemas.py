"""Tests for `focusparse.eval.schemas` — pydantic round-trip and optional
focus-extras handling.

Shape matters here because `scripts/run_hf_matrix.py` reads these JSONs back
via `EvalRunResults.model_validate_json` — drift silently breaks the matrix.
"""

from __future__ import annotations

import json

from focusparse.eval.schemas import EvalRunResults, PerProtocolResults


def _overall(**overrides) -> PerProtocolResults:
    base = dict(
        accuracy=0.75,
        abstain_rate=0.1,
        page_recall=0.9,
        bbox_iou=0.6,
        count=20,
        total_cost_usd=1.23,
        cost_per_correct_usd=0.082,
        total_input_tokens=12345,
        total_output_tokens=678,
    )
    base.update(overrides)
    return PerProtocolResults(**base)


def test_per_protocol_focus_extras_default_none():
    overall = _overall()
    assert overall.evidence_reward_mean is None
    assert overall.lazy_answer_rate is None
    assert overall.tool_calls_mean is None


def test_per_protocol_accepts_focus_extras():
    overall = _overall(
        evidence_reward_mean=0.55,
        lazy_answer_rate=0.2,
        tool_calls_mean=3.4,
    )
    assert overall.evidence_reward_mean == 0.55
    assert overall.lazy_answer_rate == 0.2
    assert overall.tool_calls_mean == 3.4


def test_eval_run_results_roundtrip_simple_agent():
    """`simple` agent leaves focus-extras as None; round-trip preserves that."""
    result = EvalRunResults(
        config_key="focusparse_simple_full_doc_abc12345",
        agent="simple",
        protocol="full_doc",
        tier_sha8="abc12345",
        resolved_tiers={
            "reasoner": {"provider": "openai", "model": "gpt-5.4"},
            "verifier": {"provider": "anthropic", "model": "claude-haiku-4-5"},
        },
        hf_repo="gabrielbo/parser-bench",
        hf_split="validation",
        hf_revision=None,
        dataset_fingerprint={"fingerprint": "xyz", "num_rows": 20},
        overall=_overall(),
    )
    payload = result.model_dump_json()
    restored = EvalRunResults.model_validate_json(payload)

    assert restored.config_key == result.config_key
    assert restored.resolved_tiers == result.resolved_tiers
    assert restored.overall.accuracy == 0.75
    assert restored.overall.evidence_reward_mean is None
    assert restored.hf_revision is None
    assert restored.per_example is None


def test_eval_run_results_roundtrip_focus_agent_populates_extras():
    result = EvalRunResults(
        config_key="focusparse_focus_focus_default_deadbeef",
        agent="focus",
        protocol="focus_default",
        tier_sha8="deadbeef",
        resolved_tiers={"reasoner": {"provider": "openai", "model": "gpt-5.4"}},
        hf_repo="gabrielbo/parser-bench",
        hf_split="validation",
        hf_revision="v1.2.3",
        dataset_fingerprint={"fingerprint": "xyz", "num_rows": 10},
        overall=_overall(
            evidence_reward_mean=0.42,
            lazy_answer_rate=0.05,
            tool_calls_mean=2.7,
        ),
    )
    restored = EvalRunResults.model_validate_json(result.model_dump_json())
    assert restored.overall.evidence_reward_mean == 0.42
    assert restored.overall.lazy_answer_rate == 0.05
    assert restored.overall.tool_calls_mean == 2.7
    assert restored.hf_revision == "v1.2.3"


def test_eval_run_results_json_shape_is_matrix_consumable():
    """`run_hf_matrix.py` indexes by config_key and reads `overall.*` — lock
    that shape in."""
    result = EvalRunResults(
        config_key="focusparse_simple_oracle_crop_11111111",
        agent="simple",
        protocol="oracle_crop",
        tier_sha8="11111111",
        resolved_tiers={},
        hf_repo="gabrielbo/parser-bench",
        hf_split="validation",
        dataset_fingerprint={},
        overall=_overall(),
    )
    raw = json.loads(result.model_dump_json())
    assert "config_key" in raw
    assert "overall" in raw
    assert "accuracy" in raw["overall"]
    assert "total_cost_usd" in raw["overall"]
    assert "total_input_tokens" in raw["overall"]
    assert "dataset_fingerprint" in raw


def test_per_protocol_defaults_for_tokens():
    """Tokens default to 0 so matrix rows are never missing them."""
    minimal = PerProtocolResults(
        accuracy=1.0,
        abstain_rate=0.0,
        page_recall=1.0,
        bbox_iou=1.0,
        count=1,
    )
    assert minimal.total_input_tokens == 0
    assert minimal.total_output_tokens == 0
    assert minimal.total_cost_usd is None
    assert minimal.cost_per_correct_usd is None
