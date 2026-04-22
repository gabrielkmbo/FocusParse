"""Tests for `focusparse.retrieval.text_index.TextIndex`.

Covers BM25 ranking, top_k truncation, cache round-trip, empty-corpus and
empty-query edge cases, porter-stemming, punctuation-heavy queries, and
cache isolation between docs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from focusparse.retrieval.text_index import TextIndex, _sanitize_fts_query


def _build(tmp_path: Path, doc_id: str, pages: dict[int, str]) -> TextIndex:
    idx = TextIndex(doc_id=doc_id, cache_dir=tmp_path)
    idx.build(pages)
    return idx


# ---------------------------------------------------------------------------
# BM25 ranking
# ---------------------------------------------------------------------------


def test_query_returns_matching_pages_ranked_by_bm25(tmp_path):
    idx = _build(
        tmp_path,
        "doc-a",
        {
            1: "Introduction. This datasheet covers general power requirements.",
            2: "VCC maximum rating is 3.6 volts. Exceeding VCC may damage the device.",
            3: "Ordering information and package dimensions.",
            4: "VCC typical is 3.3 volts under nominal load.",
        },
    )
    hits = idx.query("VCC maximum", top_k=4)
    pages_hit = [p for p, _ in hits]
    # Page 2 has both tokens ("VCC" and "maximum"); it should outrank page 4
    # which only has "VCC" and page 1/3 which have neither/none.
    assert pages_hit[0] == 2
    assert 4 in pages_hit  # page 4 still matches on "VCC"
    assert 3 not in pages_hit  # ordering info has no match
    # Scores are positive and monotonically non-increasing (higher is better).
    scores = [s for _, s in hits]
    assert all(s > 0 for s in scores)
    assert scores == sorted(scores, reverse=True)


def test_query_top_k_truncates_results(tmp_path):
    idx = _build(
        tmp_path,
        "doc-b",
        {i: "alpha beta gamma" for i in range(1, 11)},
    )
    hits = idx.query("alpha", top_k=3)
    assert len(hits) == 3


def test_query_omits_non_matching_pages(tmp_path):
    idx = _build(
        tmp_path,
        "doc-c",
        {
            1: "red fish blue fish",
            2: "one fish two fish",
            3: "completely unrelated text",
        },
    )
    hits = idx.query("red", top_k=5)
    assert [p for p, _ in hits] == [1]


# ---------------------------------------------------------------------------
# Empty + pathological inputs
# ---------------------------------------------------------------------------


def test_empty_pages_text_still_allows_query(tmp_path):
    idx = TextIndex(doc_id="empty", cache_dir=tmp_path)
    idx.build({})  # empty corpus
    assert idx.query("anything") == []


def test_empty_query_returns_empty(tmp_path):
    idx = _build(tmp_path, "doc-d", {1: "some text"})
    assert idx.query("") == []
    assert idx.query("   ") == []


def test_punctuation_only_query_returns_empty(tmp_path):
    idx = _build(tmp_path, "doc-e", {1: "some text"})
    # "?!" has no alphanumeric content after sanitization.
    assert idx.query("?!") == []


def test_query_tolerates_special_characters_in_question(tmp_path):
    """Real questions contain `V(CC)`, units, quotes — must not crash FTS."""
    idx = _build(
        tmp_path,
        "doc-f",
        {1: "VCC maximum is 3.6V", 2: "GND reference level"},
    )
    # Wouldn't parse as raw FTS MATCH; sanitizer strips the parens.
    hits = idx.query("what's V(CC) maximum?")
    assert [p for p, _ in hits] == [1]


def test_query_before_build_raises(tmp_path):
    idx = TextIndex(doc_id="doc-g", cache_dir=tmp_path)
    with pytest.raises(RuntimeError):
        idx.query("anything")


# ---------------------------------------------------------------------------
# Stemming + case
# ---------------------------------------------------------------------------


def test_query_uses_porter_stemming(tmp_path):
    idx = _build(
        tmp_path,
        "doc-h",
        {
            1: "The capacitor stores charge efficiently.",
            2: "Nothing relevant here.",
        },
    )
    # Porter stems "stores" and "storing" to a common root.
    hits = idx.query("storing charge")
    assert [p for p, _ in hits] == [1]


def test_query_is_case_insensitive(tmp_path):
    idx = _build(tmp_path, "doc-i", {1: "VCC maximum"})
    assert [p for p, _ in idx.query("vcc")] == [1]
    assert [p for p, _ in idx.query("VCC")] == [1]


# ---------------------------------------------------------------------------
# Cache semantics
# ---------------------------------------------------------------------------


def test_build_is_idempotent_and_caches_on_disk(tmp_path):
    pages = {1: "VCC maximum 3.6 volts", 2: "GND reference"}
    idx1 = _build(tmp_path, "doc-j", pages)
    idx1.close()
    files_after_first = list(tmp_path.glob("*.sqlite"))
    assert len(files_after_first) == 1
    cached = files_after_first[0]
    cached_mtime = cached.stat().st_mtime

    # Second build with the same doc_id + same text: same file, no rewrite.
    idx2 = TextIndex(doc_id="doc-j", cache_dir=tmp_path)
    idx2.build(pages)
    hits = idx2.query("VCC")
    assert [p for p, _ in hits] == [1]
    idx2.close()

    files_after_second = list(tmp_path.glob("*.sqlite"))
    assert files_after_second == [cached]
    # Mtime should be unchanged (we didn't rewrite).
    assert cached.stat().st_mtime == cached_mtime


def test_cache_key_changes_when_text_changes(tmp_path):
    idx1 = _build(tmp_path, "doc-k", {1: "VCC maximum"})
    idx1.close()
    idx2 = TextIndex(doc_id="doc-k", cache_dir=tmp_path)
    idx2.build({1: "VCC minimum"})  # same doc_id, different text
    idx2.close()
    # Two distinct cache files despite same doc_id.
    assert len(list(tmp_path.glob("*.sqlite"))) == 2


def test_cache_key_changes_when_doc_id_changes(tmp_path):
    pages = {1: "identical text"}
    _build(tmp_path, "doc-l", pages).close()
    _build(tmp_path, "doc-m", pages).close()
    assert len(list(tmp_path.glob("*.sqlite"))) == 2


# ---------------------------------------------------------------------------
# Sanitizer (exposed for unit testing)
# ---------------------------------------------------------------------------


def test_sanitize_fts_query_strips_operators():
    # Operators like * and " break bare FTS MATCH — must be stripped/quoted.
    assert _sanitize_fts_query("VCC*") == '"VCC"'
    assert _sanitize_fts_query('foo "bar" baz') == '"foo" OR "bar" OR "baz"'


def test_sanitize_fts_query_drops_pure_punctuation_tokens():
    assert _sanitize_fts_query("what ?!") == '"what"'


def test_sanitize_fts_query_ors_tokens_for_recall():
    # The router wants recall, not precision — OR across tokens.
    assert _sanitize_fts_query("alpha beta") == '"alpha" OR "beta"'
