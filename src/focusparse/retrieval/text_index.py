"""Per-document sqlite FTS5 index over page text.

Each row is one page, keyed on 1-indexed `page` number, with its extracted
text. Queries use FTS5 + BM25 and return `(page, bm25_score)` tuples ranked
most-relevant first.

The index is cached on disk under `<cache_dir>/<doc_sha>.sqlite`, keyed by
SHA-256 of `(doc_id + "\0" + joined page texts)` so re-indexing is skipped
when the same doc + same text arrives again. Wipe `cache/text_index/` to
force a rebuild.

`TextIndex` deliberately knows nothing about *where* page text comes from
(PyMuPDF native text layer, Tesseract OCR, or pre-extracted JSON). The
caller owns that pipeline — the router just consumes whatever text is
available, and falls back to the skeleton "all pages" response when no
text is provided.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path


class TextIndex:
    """A per-doc sqlite FTS5 index over page text, with disk caching.

    Usage:
        idx = TextIndex(doc_id="Arm_EE382N_4", cache_dir=Path("cache/text_index"))
        idx.build(pages_text={1: "...", 2: "...", ...})
        hits = idx.query("VCC maximum rating", top_k=5)
        # hits == [(page, bm25_score), ...] sorted by bm25_score DESC
    """

    _SCHEMA_VERSION = 1

    def __init__(self, doc_id: str, cache_dir: Path | str) -> None:
        self.doc_id = doc_id
        self.cache_dir = Path(cache_dir)
        self._db_path: Path | None = None
        self._conn: sqlite3.Connection | None = None

    # -- construction --------------------------------------------------------

    def build(self, pages_text: dict[int, str]) -> None:
        """Build (or load) the FTS5 index for `pages_text`.

        `pages_text` maps 1-indexed page number -> plain text. Pages with
        empty/whitespace text are indexed with an empty document so queries
        still return a consistent page universe.

        Idempotent: if the on-disk cache matches `(doc_id, pages_text)` we
        skip the rebuild and just open the existing DB.
        """
        if not pages_text:
            # Empty corpus — still create an in-memory DB so query() returns
            # []-shaped results instead of raising.
            self._conn = sqlite3.connect(":memory:")
            self._init_schema(self._conn)
            return

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        digest = self._corpus_fingerprint(pages_text)
        self._db_path = self.cache_dir / f"{digest}.sqlite"

        if self._db_path.exists():
            # Cache hit: schema version is baked into the digest, so we can
            # trust the file's structure matches.
            self._conn = sqlite3.connect(self._db_path)
            return

        # Cache miss: build into a temp path, then atomic-rename into place
        # so a concurrent reader never sees a half-populated DB.
        tmp_path = self._db_path.with_suffix(".sqlite.tmp")
        if tmp_path.exists():
            tmp_path.unlink()
        conn = sqlite3.connect(tmp_path)
        self._init_schema(conn)
        with conn:
            conn.executemany(
                "INSERT INTO pages (page, content) VALUES (?, ?)",
                sorted((int(p), (t or "")) for p, t in pages_text.items()),
            )
        conn.close()
        tmp_path.replace(self._db_path)
        self._conn = sqlite3.connect(self._db_path)

    # -- query ---------------------------------------------------------------

    def query(self, q: str, top_k: int = 5) -> list[tuple[int, float]]:
        """Return up to `top_k` `(page, bm25_score)` tuples ranked by BM25.

        `bm25_score` is flipped to "higher is better" (the raw sqlite score
        is lower-is-better) so downstream code can merge with other positive
        scores without inverting the sign.

        Empty or all-stopword queries return []. Pages with no match are
        omitted rather than returned with score 0 — the router adds a
        deterministic fallback when fewer than `top_k` pages match.
        """
        if self._conn is None:
            raise RuntimeError("TextIndex.build() must be called before query().")
        sanitized = _sanitize_fts_query(q)
        if not sanitized:
            return []
        try:
            rows = self._conn.execute(
                "SELECT page, bm25(pages) AS score "
                "FROM pages WHERE pages MATCH ? "
                "ORDER BY score LIMIT ?",
                (sanitized, int(top_k)),
            ).fetchall()
        except sqlite3.OperationalError:
            # Malformed FTS query (e.g. unbalanced quotes after sanitization)
            # — treat as no match rather than propagating the error into the
            # router. Callers already handle the empty-result path.
            return []
        # Flip sign so higher == more relevant.
        return [(int(page), -float(score)) for page, score in rows]

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # -- internals -----------------------------------------------------------

    def _init_schema(self, conn: sqlite3.Connection) -> None:
        # `page` is stored as UNINDEXED so BM25 scores the content column only.
        # `tokenize=porter unicode61 remove_diacritics 2` gives us stemming +
        # unicode-aware tokenization, which is what we want for datasheet-y
        # English text with occasional accented characters.
        with conn:
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS pages "
                "USING fts5(page UNINDEXED, content, "
                "tokenize='porter unicode61 remove_diacritics 2')"
            )

    def _corpus_fingerprint(self, pages_text: dict[int, str]) -> str:
        h = hashlib.sha256()
        h.update(f"v{self._SCHEMA_VERSION}\0".encode())
        h.update(self.doc_id.encode("utf-8"))
        h.update(b"\0")
        for page in sorted(pages_text):
            h.update(str(page).encode("ascii"))
            h.update(b"\0")
            h.update((pages_text[page] or "").encode("utf-8"))
            h.update(b"\0")
        return h.hexdigest()[:32]


def _sanitize_fts_query(q: str) -> str:
    """Produce an FTS5 MATCH expression from arbitrary user input.

    FTS5 treats a number of characters as operators (`"`, `*`, `(`, `)`,
    `^`, `+`, `-`, `:`). Letting them flow through unescaped means a user
    question like `what's V(CC)?` raises `OperationalError`. We split on
    whitespace, drop anything that has no alphanumeric content, quote each
    token, and OR-combine — it's a recall-biased query that matches the
    router's "give me candidate pages" shape.
    """
    tokens: list[str] = []
    for raw in q.split():
        cleaned = "".join(ch for ch in raw if ch.isalnum())
        if not cleaned:
            continue
        tokens.append(f'"{cleaned}"')
    return " OR ".join(tokens)
