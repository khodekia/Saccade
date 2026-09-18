"""Side panel: table of contents, bookmarks and search results."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..document import TocEntry
from .search import SearchHit

__all__ = ["Sidebar"]

_PAGE_ROLE = Qt.ItemDataRole.UserRole


class _ChaptersPanel(QWidget):
    """The PDF outline as a nested tree."""

    page_requested = pyqtSignal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._tree = QTreeWidget(self)
        self._tree.setHeaderLabels(["Chapter", "Page"])
        self._tree.setColumnCount(2)
        self._tree.setRootIsDecorated(True)
        self._tree.setUniformRowHeights(True)
        # Titles give up width (and elide) before the page column does, so a
        # narrow panel never pushes page numbers out of view.
        header = self._tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._tree.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._tree.itemClicked.connect(self._on_clicked)
        self._tree.itemActivated.connect(self._on_clicked)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._tree)
        self._entries: list[TocEntry] = []

    def set_entries(self, entries: list[TocEntry]) -> None:
        self._tree.clear()
        self._entries = list(entries)
        stack: list[QTreeWidgetItem] = []
        for entry in self._entries:
            item = QTreeWidgetItem([entry.title or "(untitled)", str(entry.page + 1)])
            item.setData(0, _PAGE_ROLE, entry.page)
            item.setToolTip(0, entry.title)
            level = max(1, entry.level)
            while len(stack) >= level:
                stack.pop()
            if stack:
                stack[-1].addChild(item)
            else:
                self._tree.addTopLevelItem(item)
            stack.append(item)
        # Expand the first two levels so chapters are visible immediately.
        self._tree.expandToDepth(1)

    def has_entries(self) -> bool:
        return bool(self._entries)

    def highlight_page(self, page: int) -> None:
        """Select the last chapter that starts at or before *page*."""
        best: QTreeWidgetItem | None = None
        for entry, item in zip(self._entries, self._iter_flat()):
            if entry.page <= page:
                best = item
            else:
                break
        if best is not None:
            self._tree.blockSignals(True)
            self._tree.setCurrentItem(best)
            self._tree.scrollToItem(best)
            self._tree.blockSignals(False)

    def _iter_flat(self):
        """Every tree item in outline order (matching :attr:`_entries`)."""

        def walk(item: QTreeWidgetItem):
            yield item
            for index in range(item.childCount()):
                yield from walk(item.child(index))

        for index in range(self._tree.topLevelItemCount()):
            yield from walk(self._tree.topLevelItem(index))

    def _on_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        page = item.data(0, _PAGE_ROLE)
        if page is not None:
            self.page_requested.emit(int(page))


class _BookmarksPanel(QWidget):
    """Saved pages, with add/remove buttons."""

    page_requested = pyqtSignal(int)
    add_requested = pyqtSignal()
    remove_requested = pyqtSignal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._list = QListWidget(self)
        self._list.itemActivated.connect(self._on_activated)
        self._list.itemClicked.connect(self._on_activated)

        add = QPushButton("Add current page", self)
        add.setToolTip("Bookmark the current page (Ctrl+B)")
        add.clicked.connect(self.add_requested.emit)
        remove = QPushButton("Remove", self)
        remove.setToolTip("Remove the selected bookmark (Delete)")
        remove.clicked.connect(self._on_remove)

        buttons = QHBoxLayout()
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(buttons)
        layout.addWidget(self._list)

    def set_marks(self, marks: list[tuple[int, str]]) -> None:
        self._list.clear()
        for page, label in marks:
            text = f"Page {page + 1}" + (f" \u2014 {label}" if label else "")
            item = QListWidgetItem(text)
            item.setData(_PAGE_ROLE, page)
            item.setToolTip(label)
            self._list.addItem(item)

    def _on_activated(self, item: QListWidgetItem) -> None:
        page = item.data(_PAGE_ROLE)
        if page is not None:
            self.page_requested.emit(int(page))

    def _on_remove(self) -> None:
        item = self._list.currentItem()
        if item is not None and item.data(_PAGE_ROLE) is not None:
            self.remove_requested.emit(int(item.data(_PAGE_ROLE)))


class _ResultsPanel(QWidget):
    """Search results; clicking a row jumps to that match."""

    page_requested = pyqtSignal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._list = QListWidget(self)
        self._list.itemActivated.connect(self._on_activated)
        self._list.itemClicked.connect(self._on_activated)
        self._hits: list[SearchHit] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._list)

    def set_results(self, hits: list[SearchHit]) -> None:
        self._hits = list(hits)
        self._list.clear()
        if not hits:
            self._list.addItem(QListWidgetItem("No matches"))
            return
        for hit in hits:
            item = QListWidgetItem(f"p. {hit.page + 1} \u2014 {hit.snippet}")
            item.setData(_PAGE_ROLE, hit.page)
            item.setToolTip(hit.snippet)
            self._list.addItem(item)
        self._list.setCurrentRow(0)

    def set_message(self, text: str) -> None:
        self._hits = []
        self._list.clear()
        self._list.addItem(QListWidgetItem(text))

    def _on_activated(self, item: QListWidgetItem) -> None:
        page = item.data(_PAGE_ROLE)
        if page is not None:
            self.page_requested.emit(int(page))

    @property
    def hits(self) -> list[SearchHit]:
        return self._hits

    @property
    def current_index(self) -> int:
        return self._list.currentRow()

    def select_index(self, index: int) -> SearchHit | None:
        """Select result *index* (clamped) and return it."""
        if not self._hits:
            return None
        index = max(0, min(index, len(self._hits) - 1))
        self._list.setCurrentRow(index)
        return self._hits[index]

    def select_page(self, page: int) -> SearchHit | None:
        """Select the first result on *page*, if any."""
        for index, hit in enumerate(self._hits):
            if hit.page == page:
                return self.select_index(index)
        return None


class Sidebar(QTabWidget):
    """Chapters / Bookmarks / Results dock content."""

    page_requested = pyqtSignal(int)
    bookmark_add_requested = pyqtSignal()
    bookmark_remove_requested = pyqtSignal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.chapters = _ChaptersPanel(self)
        self.bookmarks = _BookmarksPanel(self)
        self.results = _ResultsPanel(self)
        self.addTab(self.chapters, "Chapters")
        self.addTab(self.bookmarks, "Bookmarks")
        self.addTab(self.results, "Results")

        for panel in (self.chapters, self.bookmarks, self.results):
            panel.page_requested.connect(self.page_requested)
        self.bookmarks.add_requested.connect(self.bookmark_add_requested)
        self.bookmarks.remove_requested.connect(self.bookmark_remove_requested)

    def show_results(self, hits: list[SearchHit]) -> None:
        self.results.set_results(hits)
        self.setCurrentWidget(self.results)

    def show_message(self, text: str) -> None:
        """Show an explanatory message in the results tab."""
        self.results.set_message(text)
        self.setCurrentWidget(self.results)

    def show_chapters(self) -> None:
        self.setCurrentWidget(self.chapters)

    def show_bookmarks(self) -> None:
        self.setCurrentWidget(self.bookmarks)