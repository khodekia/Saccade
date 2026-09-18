"""Full-book text search running in a background thread.

Extracting every page of a 900 page book takes a moment, so the search runs in
a :class:`QThread` and reports progress; the GUI stays responsive and the search
can be cancelled at any time.
"""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import QThread, pyqtSignal

from ..document import Document, open_document

__all__ = ["SearchHit", "SearchWorker"]


@dataclass(frozen=True)
class SearchHit:
    """One match: 0-based *page*, a context *snippet* and the match offset."""

    page: int
    snippet: str
    offset: int


class SearchWorker(QThread):
    """Scans the pages of *document* for *query*.

    Signals
    -------
    progress(done, total)
        Emitted while scanning, to drive a progress indicator.
    hits_found(list)
        Emitted once, with the list of :class:`SearchHit` (may be empty).
    """

    progress = pyqtSignal(int, int)
    hits_found = pyqtSignal(list)

    #: Keep the context readable in the results list.
    SNIPPET_RADIUS = 60
    #: Stop after this many matches; more is not useful in a sidebar.
    MAX_HITS = 500

    def __init__(
        self,
        document: Document,
        query: str,
        *,
        case_sensitive: bool = False,
        start_page: int = 0,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._document = document
        self._query = query
        self._case_sensitive = case_sensitive
        self._start_page = max(0, start_page)
        self._cancelled = False

    def cancel(self) -> None:
        """Ask the worker to stop as soon as possible."""
        self._cancelled = True

    # ------------------------------------------------------------------ #
    def run(self) -> None:  # noqa: D102 (Qt entry point)
        query = self._query
        if not query:
            self.hits_found.emit([])
            return

        # A private handle: MuPDF documents must not be read from two threads,
        # and the window keeps rendering pages while the search runs.
        try:
            document = open_document(
                self._document.path,
                backend=self._document.backend_name,
                smart_paragraphs=self._document.smart_paragraphs,
            )
        except Exception:
            self.hits_found.emit([])
            return
        try:
            self._scan(document, query)
        finally:
            document.close()

    def _scan(self, document: Document, query: str) -> None:
        total = document.page_count
        needle = query if self._case_sensitive else query.casefold()
        order = list(range(self._start_page, total)) + list(range(0, self._start_page))
        hits: list[SearchHit] = []

        for index, page in enumerate(order, start=1):
            if self._cancelled:
                return
            try:
                text = document.page_text(page)
            except Exception:
                text = ""
            haystack = text if self._case_sensitive else text.casefold()
            position = haystack.find(needle)
            while position != -1:
                hits.append(
                    SearchHit(
                        page=page,
                        snippet=self._snippet(text, position, len(query)),
                        offset=position,
                    )
                )
                if len(hits) >= self.MAX_HITS:
                    break
                position = haystack.find(needle, position + len(needle))
            if index % 8 == 0 or index == len(order):
                self.progress.emit(index, len(order))
            if len(hits) >= self.MAX_HITS:
                break

        if self._cancelled:
            return
        hits.sort(key=lambda hit: (hit.page, hit.offset))
        self.hits_found.emit(hits)

    def _snippet(self, text: str, position: int, length: int) -> str:
        """A whitespace-collapsed window of text around the match."""
        start = max(0, position - self.SNIPPET_RADIUS)
        end = min(len(text), position + length + self.SNIPPET_RADIUS)
        snippet = " ".join(text[start:end].split())
        if start > 0:
            snippet = "\u2026" + snippet
        if end < len(text):
            snippet = snippet + "\u2026"
        return snippet