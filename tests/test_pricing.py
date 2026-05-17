"""Tests for `focusparse.eval.pricing`."""

from __future__ import annotations

from focusparse.eval.pricing import compute_usd, is_priced


def test_compute_usd_known_openai_model():
    # GPT-5.4: $1.25 in / $10.00 out per Mtok.
    # 1M input + 1M output should be $11.25 total.
    usd = compute_usd("openai", "gpt-5.4", tokens_in=1_000_000, tokens_out=1_000_000)
    assert usd == 11.25


def test_compute_usd_gemini_flash_small_usage():
    # Flash is the cheap tier — pennies for the test workload.
    usd = compute_usd("gemini", "gemini-2.5-flash", tokens_in=10_000, tokens_out=2_000)
    assert usd is not None
    assert 0.0 < usd < 0.01


def test_compute_usd_gemini_31_pro_schema_extraction_usage():
    usd = compute_usd("gemini", "gemini-3.1-pro-preview", tokens_in=1_136, tokens_out=252)
    assert usd == 0.005296


def test_compute_usd_gemini_31_flash_lite_schema_extraction_usage():
    usd = compute_usd(
        "gemini",
        "gemini-3.1-flash-lite",
        tokens_in=1_136,
        tokens_out=252,
    )
    assert usd == 0.000662


def test_compute_usd_gemini_31_flash_lite_preview_schema_extraction_usage():
    usd = compute_usd(
        "gemini",
        "gemini-3.1-flash-lite-preview",
        tokens_in=1_136,
        tokens_out=252,
    )
    assert usd == 0.000331


def test_compute_usd_unknown_model_returns_none():
    assert compute_usd("openai", "gpt-nonexistent-99", 100, 100) is None


def test_compute_usd_is_case_insensitive_on_provider():
    a = compute_usd("OpenAI", "gpt-5.4", 1000, 1000)
    b = compute_usd("openai", "gpt-5.4", 1000, 1000)
    assert a == b


def test_is_priced():
    assert is_priced("anthropic", "claude-haiku-4-5")
    assert not is_priced("anthropic", "claude-fake-1")
