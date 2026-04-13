"""Per-document sqlite FTS5 index over PDF text + OCR text.

Built once per doc, cached on disk under cache/text_index/<doc_sha>.sqlite.
Router queries it with BM25 over question keywords + family priors.

TODO(Phase 2): wire sqlite FTS5 + BM25 ranking + caching.
"""

from __future__ import annotations

from pathlib import Path


class TextIndex:
    def __init__(self, doc_id: str, cache_dir: Path | str) -> None:
        self.doc_id = doc_id
        self.cache_dir = Path(cache_dir)

    def build(self, pages_text: list[str]) -> None:
        raise NotImplementedError("TextIndex.build — wire in Phase 2")

    def query(self, q: str, top_k: int = 5) -> list[tuple[int, float]]:
        raise NotImplementedError("TextIndex.query — wire in Phase 2")
