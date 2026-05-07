"""Tests for `scripts/run_hf_eval.py` helpers.

The script isn't importable as a module (it lives in `scripts/`, outside the
package), so we load it via importlib. We exercise the pure helpers
(`_tier_sha8`, `_wrap_results`, `_looks_abstain`, `_resolve_tiers`) and the
`--tier-override` → env-var plumbing; the `main()` run loop needs real
backends and is covered by the end-to-end smoke in `tests/test_harness.py`.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from focusparse.eval.metrics import AggregateMetrics
from focusparse.eval.schemas import EvalRunResults

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_hf_eval.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("_run_hf_eval_under_test", SCRIPT_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def script_mod():
    return _load_script_module()


# ---------------------------------------------------------------------------
# _tier_sha8 — determinism is load-bearing for filename stability
# ---------------------------------------------------------------------------


def test_tier_sha8_is_deterministic_across_key_order(script_mod):
    a = {
        "reasoner": {"provider": "openai", "model": "gpt-5.4"},
        "verifier": {"provider": "anthropic", "model": "claude-haiku-4-5"},
    }
    # Same content, keys inserted in reverse:
    b = {
        "verifier": {"provider": "anthropic", "model": "claude-haiku-4-5"},
        "reasoner": {"provider": "openai", "model": "gpt-5.4"},
    }
    assert script_mod._tier_sha8(a) == script_mod._tier_sha8(b)


def test_tier_sha8_changes_when_tier_changes(script_mod):
    a = {"reasoner": {"provider": "openai", "model": "gpt-5.4"}}
    b = {"reasoner": {"provider": "openai", "model": "gpt-5.0"}}
    assert script_mod._tier_sha8(a) != script_mod._tier_sha8(b)


def test_tier_sha8_is_8_hex_chars(script_mod):
    h = script_mod._tier_sha8({"reasoner": {"provider": "openai", "model": "x"}})
    assert len(h) == 8
    int(h, 16)  # hex-parse — raises if not hex


# ---------------------------------------------------------------------------
# _looks_abstain
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("The answer is unanswerable", True),
        ("This cannot be determined from the document", True),
        ("N/A", True),
        ("n/a based on the evidence", True),
        ("UNANSWERABLE", True),  # case-insensitive
        ("5.5 V", False),
        ("The voltage is 3.3V", False),
        ("", False),
        (None, False),
    ],
)
def test_looks_abstain(script_mod, text, expected):
    assert script_mod._looks_abstain(text) is expected


# ---------------------------------------------------------------------------
# _wrap_results — dict-from-harness → EvalRunResults
# ---------------------------------------------------------------------------


def _make_harness_result(
    *,
    accuracy=0.5,
    n=4,
    usd_total=0.12,
    usd_per_correct=0.06,
    tokens_in_mean=1000.0,
    tokens_out_mean=50.0,
    evidence_reward_mean=0.3,
    lazy_answer_rate=0.25,
    tool_calls_mean=1.5,
    per_example=None,
) -> dict:
    if per_example is None:
        per_example = [
            {"answer_pred": "5.5 V"},
            {"answer_pred": "unanswerable"},
            {"answer_pred": "3.3 V"},
            {"answer_pred": None},
        ]
    return {
        "aggregate": AggregateMetrics(
            n=n,
            accuracy=accuracy,
            page_recall_mean=0.9,
            bbox_iou_mean=0.6,
            evidence_reward_mean=evidence_reward_mean,
            lazy_answer_rate=lazy_answer_rate,
            tool_calls_mean=tool_calls_mean,
            tokens_in_mean=tokens_in_mean,
            tokens_out_mean=tokens_out_mean,
            usd_total=usd_total,
            usd_per_correct=usd_per_correct,
        ),
        "per_example": per_example,
    }


def test_wrap_results_simple_agent_nulls_focus_extras(script_mod):
    from focusparse.eval.schemas import PerProtocolResults

    harness = _make_harness_result()
    wrapped = script_mod._wrap_results(
        harness,
        config_key="focusparse_simple_full_doc_abc12345",
        agent="simple",
        protocol="full_doc",
        tier_sha8="abc12345",
        resolved_tiers={"reasoner": {"provider": "openai", "model": "gpt-5.4"}},
        hf_repo="gabrielbo/parser-bench",
        hf_split="validation",
        hf_revision=None,
        fingerprint={"fingerprint": "xxx", "num_rows": 4},
        schemas=(EvalRunResults, PerProtocolResults),
    )
    assert isinstance(wrapped, EvalRunResults)
    assert wrapped.agent == "simple"
    assert wrapped.overall.accuracy == 0.5
    assert wrapped.overall.count == 4
    assert wrapped.overall.total_cost_usd == 0.12
    assert wrapped.overall.cost_per_correct_usd == 0.06
    # Focus-only columns must be None for simple agent
    assert wrapped.overall.evidence_reward_mean is None
    assert wrapped.overall.lazy_answer_rate is None
    assert wrapped.overall.tool_calls_mean is None
    # Token totals are means * n
    assert wrapped.overall.total_input_tokens == 4000
    assert wrapped.overall.total_output_tokens == 200


def test_wrap_results_focus_agent_populates_extras(script_mod):
    from focusparse.eval.schemas import PerProtocolResults

    harness = _make_harness_result()
    wrapped = script_mod._wrap_results(
        harness,
        config_key="focusparse_focus_focus_default_deadbeef",
        agent="focus",
        protocol="focus_default",
        tier_sha8="deadbeef",
        resolved_tiers={},
        hf_repo="gabrielbo/parser-bench",
        hf_split="validation",
        hf_revision="v1",
        fingerprint={},
        schemas=(EvalRunResults, PerProtocolResults),
    )
    assert wrapped.overall.evidence_reward_mean == 0.3
    assert wrapped.overall.lazy_answer_rate == 0.25
    assert wrapped.overall.tool_calls_mean == 1.5


def test_wrap_results_computes_abstain_rate(script_mod):
    from focusparse.eval.schemas import PerProtocolResults

    # 1 "unanswerable" out of 4 rows → abstain_rate = 0.25
    harness = _make_harness_result()
    wrapped = script_mod._wrap_results(
        harness,
        config_key="k",
        agent="simple",
        protocol="full_doc",
        tier_sha8="00000000",
        resolved_tiers={},
        hf_repo="r",
        hf_split="validation",
        hf_revision=None,
        fingerprint={},
        schemas=(EvalRunResults, PerProtocolResults),
    )
    assert wrapped.overall.abstain_rate == 0.25


def test_wrap_results_empty_run_handles_zero_division(script_mod):
    from focusparse.eval.schemas import PerProtocolResults

    harness = {
        "aggregate": AggregateMetrics(
            n=0,
            accuracy=0.0,
            page_recall_mean=0.0,
            bbox_iou_mean=0.0,
            evidence_reward_mean=0.0,
            lazy_answer_rate=0.0,
            tool_calls_mean=0.0,
            tokens_in_mean=0.0,
            tokens_out_mean=0.0,
            usd_total=0.0,
            usd_per_correct=None,
        ),
        "per_example": [],
    }
    wrapped = script_mod._wrap_results(
        harness,
        config_key="k",
        agent="simple",
        protocol="full_doc",
        tier_sha8="00000000",
        resolved_tiers={},
        hf_repo="r",
        hf_split="validation",
        hf_revision=None,
        fingerprint={},
        schemas=(EvalRunResults, PerProtocolResults),
    )
    assert wrapped.overall.count == 0
    assert wrapped.overall.abstain_rate == 0.0
    assert wrapped.overall.total_input_tokens == 0
    assert wrapped.overall.total_output_tokens == 0


# ---------------------------------------------------------------------------
# _resolve_tiers + config_key formation via argparse
# ---------------------------------------------------------------------------


def test_resolve_tiers_snapshots_all_roles(script_mod):
    from focusparse.utils.config import load_config

    config = load_config()
    resolved = script_mod._resolve_tiers(config)
    # Every role in config.roles should appear with a provider+model dict
    for role in config.roles:
        assert role in resolved
        assert "provider" in resolved[role]
        assert "model" in resolved[role]


def test_resolve_tiers_honors_env_override(script_mod, monkeypatch):
    from focusparse.utils.config import load_config

    # Any role that has >1 tier to choose from — reasoner almost always does.
    config = load_config()
    original_reasoner = config.tier_for("reasoner").model_dump()
    # Pick any tier name that differs from the current reasoner tier
    other_tier = next(
        name for name in config.tiers if config.tiers[name].model_dump() != original_reasoner
    )
    monkeypatch.setenv("FOCUSPARSE_TIER_REASONER", other_tier)

    resolved = script_mod._resolve_tiers(config)
    assert resolved["reasoner"] == config.tiers[other_tier].model_dump()
    assert resolved["reasoner"] != original_reasoner

    # Hash must change when the override takes effect
    no_override_hash = script_mod._tier_sha8(
        {role: config.tiers[config.roles[role]].model_dump() for role in config.roles}
    )
    override_hash = script_mod._tier_sha8(resolved)
    assert no_override_hash != override_hash


# ---------------------------------------------------------------------------
# argparse smoke — verifies --tier-override ROLE=TIER parses and repeats
# ---------------------------------------------------------------------------


def test_argparse_tier_override_repeatable(script_mod, monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_hf_eval.py",
            "--protocol",
            "full_doc",
            "--tier-override",
            "reasoner=frontier",
            "--tier-override",
            "verifier=mid",
        ],
    )
    args = script_mod._parse_args()
    assert args.tier_override == ["reasoner=frontier", "verifier=mid"]
    assert args.protocol == "full_doc"
    assert args.agent == "simple"  # default


def test_argparse_trace_viewer_flags(script_mod, monkeypatch, tmp_path):
    out = tmp_path / "trace.html"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_hf_eval.py",
            "--protocol",
            "agentic_multi_page",
            "--agent",
            "focus",
            "--example-id",
            "dat-Foo-0001",
            "--visualize-trace",
            "--trace-viewer-output",
            str(out),
        ],
    )
    args = script_mod._parse_args()
    assert args.example_id == "dat-Foo-0001"
    assert args.visualize_trace is True
    assert args.trace_viewer_output == out


def test_argparse_layout_preflight_flags(script_mod, monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_hf_eval.py",
            "--protocol",
            "agentic_multi_page",
            "--agent",
            "focus",
            "--skip-layout-preflight",
            "--allow-layout-fallbacks",
            "--layout-preflight-retries",
            "2",
            "--layout-detect-retries",
            "5",
            "--layout-detect-timeout-s",
            "45.5",
        ],
    )
    args = script_mod._parse_args()
    assert args.skip_layout_preflight is True
    assert args.allow_layout_fallbacks is True
    assert args.layout_preflight_retries == 2
    assert args.layout_detect_retries == 5
    assert args.layout_detect_timeout_s == 45.5


def test_argparse_rejects_unknown_protocol(script_mod, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["run_hf_eval.py", "--protocol", "bogus"])
    with pytest.raises(SystemExit):
        script_mod._parse_args()


def test_filter_examples_by_id(script_mod):
    examples = [SimpleNamespace(id="a"), SimpleNamespace(id="b")]
    assert script_mod._filter_examples_by_id(examples, "b") == [examples[1]]
    assert script_mod._filter_examples_by_id(examples, "missing") == []


def test_default_trace_viewer_output(script_mod):
    path = script_mod._default_trace_viewer_output(Path("results/hf/run1"), "ex-1")
    assert path == Path("results/trace_viewer/run1/ex-1.html")


def test_first_existing_page_image_prefers_staged_relative_path(script_mod, tmp_path):
    image = tmp_path / "pages" / "p1.png"
    image.parent.mkdir()
    image.write_bytes(b"fake")
    examples = [
        SimpleNamespace(page_images=["missing.png"]),
        SimpleNamespace(page_images=["pages/p1.png"]),
    ]
    assert script_mod._first_existing_page_image(examples, tmp_path) == image


def test_first_existing_page_image_accepts_absolute_path(script_mod, tmp_path):
    image = tmp_path / "abs.png"
    image.write_bytes(b"fake")
    examples = [SimpleNamespace(page_images=[str(image)])]
    assert script_mod._first_existing_page_image(examples, tmp_path / "unused") == image


def test_first_existing_page_image_raises_when_missing(script_mod, tmp_path):
    examples = [SimpleNamespace(page_images=["missing.png"])]
    with pytest.raises(RuntimeError, match="no staged page image"):
        script_mod._first_existing_page_image(examples, tmp_path)


async def test_layout_preflight_calls_detect_with_uncached_staged_image(script_mod, tmp_path):
    image = tmp_path / "page.png"
    Image.new("RGB", (7, 5), color="white").save(image)
    calls: list[dict] = []

    async def _fake_detect(png_bytes, **kwargs):
        calls.append({"png_bytes": png_bytes, **kwargs})
        return SimpleNamespace(boxes=[object(), object()])

    await script_mod._preflight_layout_endpoint(
        [SimpleNamespace(page_images=["page.png"])],
        images_root=tmp_path,
        max_retries=2,
        timeout_s=3.0,
        detect_layout_func=_fake_detect,
    )

    assert len(calls) == 1
    assert calls[0]["png_bytes"] == image.read_bytes()
    assert calls[0]["image_width"] == 7
    assert calls[0]["image_height"] == 5
    assert calls[0]["cache_dir"] is None
    assert calls[0]["max_retries"] == 2
    assert calls[0]["timeout_s"] == 3.0


async def test_layout_preflight_wraps_endpoint_failure(script_mod, tmp_path):
    from focusparse.tools.layout_detect import LayoutEndpointUnavailable

    image = tmp_path / "page.png"
    Image.new("RGB", (7, 5), color="white").save(image)

    async def _fake_detect(*args, **kwargs):
        raise LayoutEndpointUnavailable("503 on attempt 1")

    with pytest.raises(RuntimeError, match="503 on attempt 1"):
        await script_mod._preflight_layout_endpoint(
            [SimpleNamespace(page_images=[str(image)])],
            images_root=tmp_path,
            max_retries=1,
            detect_layout_func=_fake_detect,
        )


def test_render_trace_viewer_writes_html(script_mod, tmp_path):
    run_dir = tmp_path / "run"
    pred_dir = run_dir / "predictions"
    pred_dir.mkdir(parents=True)
    (pred_dir / "ex-1.json").write_text(
        """{
          "example_id": "ex-1",
          "answer_pred": "x",
          "answer_gold": "x",
          "answer_correct": 1.0,
          "citations": [],
          "trace": {"steps": [], "evidence_snapshot": null, "artifacts": [], "debug_events": []}
        }"""
    )
    out = tmp_path / "trace.html"
    script_mod._render_trace_viewer(
        run_dir=run_dir,
        example_id="ex-1",
        output_path=out,
        staging_root=tmp_path,
    )
    text = out.read_text()
    assert "Trace · ex-1" in text
    assert "const VIEW" in text


# ---------------------------------------------------------------------------
# _protocol_matches_agent — guardrail against nonsensical combos
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "agent,protocol,expected",
    [
        ("simple", "full_doc", True),
        ("simple", "oracle_page", True),
        ("simple", "oracle_crop", True),
        ("simple", "focus_default", False),  # simple can't use focus protocol
        ("focus", "focus_default", True),
        ("focus", "full_doc", False),  # focus can't use baseline protocols
        ("focus", "oracle_page", False),
        ("focus", "oracle_crop", False),
    ],
)
def test_protocol_matches_agent(script_mod, agent, protocol, expected):
    assert script_mod._protocol_matches_agent(agent, protocol) is expected
