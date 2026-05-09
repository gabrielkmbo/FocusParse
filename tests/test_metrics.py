"""Tests for `focusparse.eval.metrics` — Phase 1 of the headline-table plan.

Covers:
  * `_domain_stem` normalizes enum/string/None to lowercase stems
  * `bootstrap_ci` is reproducible (same seed → same result) and bounded
  * `bootstrap_ci` returns (0, 0) for n < 2
  * `aggregate` carries CIs alongside the existing point estimates
  * `aggregate_by_domain` buckets correctly and always includes `_overall`
  * Per-domain CIs are wider on smaller buckets (n=47 vs n=101)
"""

from __future__ import annotations

import pytest

from focusparse.eval.metrics import (
    AggregateMetrics,
    _bootstrap_usd_per_correct_ci,
    _domain_stem,
    aggregate,
    aggregate_by_domain,
    bootstrap_ci,
)

# ---------------------------------------------------------------------------
# _domain_stem
# ---------------------------------------------------------------------------


def test_domain_stem_handles_enum_repr():
    assert _domain_stem("Domain.DATASHEET") == "datasheet"
    assert _domain_stem("Domain.FINANCE") == "finance"


def test_domain_stem_handles_bare_string():
    assert _domain_stem("datasheet") == "datasheet"
    assert _domain_stem("FINANCE") == "finance"


def test_domain_stem_handles_none_and_empty():
    assert _domain_stem(None) == "?"
    assert _domain_stem("") == "?"


def test_domain_stem_lowercases():
    assert _domain_stem("Domain.SCHEMATIC") == "schematic"


# ---------------------------------------------------------------------------
# bootstrap_ci
# ---------------------------------------------------------------------------


def test_bootstrap_ci_is_reproducible_with_same_seed():
    values = [0.0, 1.0, 1.0, 0.0, 1.0]
    ci1 = bootstrap_ci(values, n_resamples=200, seed=42)
    ci2 = bootstrap_ci(values, n_resamples=200, seed=42)
    assert ci1 == ci2


def test_bootstrap_ci_differs_with_different_seed():
    # Continuous values give the bootstrap a non-degenerate distribution; with
    # tiny binary samples two seeds can land on the same percentile slot.
    values = [0.12, 0.34, 0.56, 0.78, 0.91, 0.23, 0.67, 0.45]
    ci1 = bootstrap_ci(values, n_resamples=200, seed=42)
    ci2 = bootstrap_ci(values, n_resamples=200, seed=43)
    assert ci1 != ci2


def test_bootstrap_ci_bounded_by_data_range():
    values = [0.3, 0.4, 0.5, 0.6, 0.7]
    lo, hi = bootstrap_ci(values, n_resamples=500, seed=42)
    assert 0.3 <= lo <= 0.7
    assert 0.3 <= hi <= 0.7
    assert lo <= hi


def test_bootstrap_ci_returns_zero_for_singleton():
    assert bootstrap_ci([1.0]) == (0.0, 0.0)
    assert bootstrap_ci([]) == (0.0, 0.0)


def test_bootstrap_ci_widens_with_smaller_n():
    """CI on the same mean should be wider when n is smaller."""
    small = [0.0, 1.0, 0.0, 1.0, 0.0]  # mean=0.4, n=5
    large = [0.0, 1.0, 0.0, 1.0, 0.0] * 20  # same mean, n=100
    lo_s, hi_s = bootstrap_ci(small, n_resamples=500, seed=42)
    lo_l, hi_l = bootstrap_ci(large, n_resamples=500, seed=42)
    assert (hi_s - lo_s) > (hi_l - lo_l)


# ---------------------------------------------------------------------------
# _bootstrap_usd_per_correct_ci
# ---------------------------------------------------------------------------


def test_usd_per_correct_ci_handles_zero_correct():
    """No correct examples → CI is None (divide-by-zero)."""
    correct = [0.0, 0.0, 0.0]
    usd = [0.01, 0.02, 0.01]
    assert _bootstrap_usd_per_correct_ci(correct, usd) is None


def test_usd_per_correct_ci_returns_bounded_range():
    correct = [1.0, 0.0, 1.0, 1.0, 0.0]
    usd = [0.02, 0.01, 0.03, 0.04, 0.02]
    ci = _bootstrap_usd_per_correct_ci(correct, usd, n_resamples=500, seed=42)
    assert ci is not None
    lo, hi = ci
    assert lo <= hi
    # Point estimate is sum(usd) / sum(correct) = 0.12 / 3 = 0.04
    # CI should at least contain values near that.
    assert 0.0 < lo < 0.15
    assert 0.0 < hi < 0.15


# ---------------------------------------------------------------------------
# aggregate
# ---------------------------------------------------------------------------


def _record(
    *,
    correct: float = 1.0,
    usd: float = 0.01,
    page_recall: float = 1.0,
    bbox_iou: float = 0.5,
    domain: str | None = "Domain.DATASHEET",
    is_lazy: int = 0,
    tool_calls: int = 1,
    latency_ms: float = 1000.0,
) -> dict:
    return {
        "answer_correct": correct,
        "usd": usd,
        "page_recall": page_recall,
        "bbox_iou": bbox_iou,
        "evidence_reward": 0.0,
        "is_lazy": is_lazy,
        "tool_calls": tool_calls,
        "tokens_in": 100,
        "tokens_out": 10,
        "latency_ms": latency_ms,
        "domain": domain,
    }


def test_aggregate_carries_accuracy_ci():
    records = [_record(correct=c) for c in [1.0, 1.0, 0.0, 1.0, 0.0, 1.0]]
    m = aggregate(records, bootstrap_resamples=500)
    assert m.accuracy == pytest.approx(4 / 6, abs=1e-9)
    lo, hi = m.accuracy_ci
    assert lo <= m.accuracy <= hi


def test_aggregate_usd_per_correct_ci_present_when_correct_exist():
    records = [
        _record(correct=1.0, usd=0.01),
        _record(correct=0.0, usd=0.02),
        _record(correct=1.0, usd=0.03),
    ]
    m = aggregate(records, bootstrap_resamples=500)
    assert m.usd_per_correct is not None
    assert m.usd_per_correct_ci is not None


def test_aggregate_carries_latency_mean():
    records = [_record(latency_ms=1000.0), _record(latency_ms=3000.0)]
    m = aggregate(records, bootstrap_resamples=100)
    assert m.latency_ms_mean == pytest.approx(2000.0)


def test_aggregate_returns_zero_metrics_for_empty():
    m = aggregate([])
    assert m.n == 0
    assert m.accuracy == 0.0
    assert m.usd_per_correct is None
    assert m.latency_ms_mean == 0.0


# ---------------------------------------------------------------------------
# aggregate_by_domain
# ---------------------------------------------------------------------------


def test_aggregate_by_domain_buckets_correctly():
    records = [
        _record(correct=1.0, domain="Domain.DATASHEET"),
        _record(correct=1.0, domain="Domain.DATASHEET"),
        _record(correct=0.0, domain="Domain.DATASHEET"),
        _record(correct=1.0, domain="Domain.FINANCE"),
        _record(correct=0.0, domain="Domain.FINANCE"),
    ]
    out = aggregate_by_domain(records, bootstrap_resamples=200)
    assert "datasheet" in out
    assert "finance" in out
    assert "_overall" in out
    assert out["datasheet"].n == 3
    assert out["finance"].n == 2
    assert out["_overall"].n == 5
    # Datasheet accuracy = 2/3, Finance = 1/2
    assert out["datasheet"].accuracy == pytest.approx(2 / 3, abs=1e-9)
    assert out["finance"].accuracy == pytest.approx(1 / 2, abs=1e-9)


def test_aggregate_by_domain_handles_missing_domain():
    """Records with domain=None get bucketed as '?' rather than raising."""
    records = [
        _record(correct=1.0, domain=None),
        _record(correct=0.0, domain="Domain.DATASHEET"),
    ]
    out = aggregate_by_domain(records, bootstrap_resamples=200)
    assert "?" in out
    assert out["?"].n == 1
    assert out["datasheet"].n == 1
    assert out["_overall"].n == 2


def test_aggregate_by_domain_finance_ci_wider_than_datasheet():
    """Smaller bucket → wider CI on the same accuracy. Pins the property
    that downstream paper-reading depends on."""
    # Datasheet bucket: 60 records at 50% accuracy
    ds = [_record(correct=float(i % 2 == 0), domain="Domain.DATASHEET") for i in range(60)]
    # Finance bucket: 20 records, same 50% accuracy
    fin = [_record(correct=float(i % 2 == 0), domain="Domain.FINANCE") for i in range(20)]
    out = aggregate_by_domain(ds + fin, bootstrap_resamples=500)
    ds_lo, ds_hi = out["datasheet"].accuracy_ci
    fin_lo, fin_hi = out["finance"].accuracy_ci
    assert (fin_hi - fin_lo) > (ds_hi - ds_lo)


def test_aggregate_by_domain_returns_aggregate_metrics_objects():
    """Sanity: each bucket value is an `AggregateMetrics`, not a dict."""
    records = [_record(domain="Domain.DATASHEET")]
    out = aggregate_by_domain(records, bootstrap_resamples=100)
    assert isinstance(out["_overall"], AggregateMetrics)
    assert isinstance(out["datasheet"], AggregateMetrics)
