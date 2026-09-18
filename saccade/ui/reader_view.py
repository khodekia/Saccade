"""The reading surface: a scrollable, centred, themable text column."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QImage,
    QKeyEvent,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextOption,
)
from PyQt6.QtWidgets import QTextBrowser, QTextEdit

from ..theme import Theme

__all__ = ["ReadingView"]


def _find_flags(case_sensitive: bool) -> QTextDocument.FindFlag:
    """Qt search flags for *case_sensitive* matching."""
    flags = QTextDocument.FindFlag(0)
    if case_sensitive:
        flags |= QTextDocument.FindFlag.FindCaseSensitively
    return flags


class ReadingView(QTextBrowser):
    """Shows one page of bionic text.

    Besides rendering the HTML it behaves like an e-reader:

    * :kbd:`Up`/:kbd:`Down`/:kbd:`Space` scroll, and scrolling past either end
      requests the previous/next page through :attr:`page_turn_requested`;
    * :kbd:`Ctrl`+wheel changes the font size (:attr:`zoom_requested`);
    * the text column is centred and width-limited, because short lines are
      easier to read;
    * one PDF page is shown at a time, which keeps the reading position stable
      and makes the progress indicator meaningful.
    """

    #: ``+1`` for "next page", ``-1`` for "previous page".
    page_turn_requested = pyqtSignal(int)
    #: ``+1``/``-1`` when the user asks for a larger/smaller font.
    zoom_requested = pyqtSignal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setOpenExternalLinks(False)
        self.setOpenLinks(False)
        self.setFrameShape(QTextBrowser.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)

        self._theme: Theme | None = None
        self._family = "DejaVu Serif"
        self._size_pt = 13
        self._line_height = 1.5
        self._justify = False
        self._column_width = 700
        self._document_margin = 28
        self._layout_mode = False
        self._page_heading = ""
        self._body_html = ""
        self._search_term = ""
        self._case_sensitive = False
        self._images: dict[str, QImage] = {}
        self._letter_spacing = 0.0
        self._word_spacing = 0.0
        self._focus_mode = False
        self._focus_block = -1
        self._dim_selections: list[QTextEdit.ExtraSelection] = []
        self._search_selections: list[QTextEdit.ExtraSelection] = []
        self.setMouseTracking(True)
        self.verticalScrollBar().valueChanged.connect(self._follow_scroll)

    # ------------------------------------------------------------------ #
    # Appearance
    # ------------------------------------------------------------------ #
    def configure(
        self,
        *,
        theme: Theme,
        family: str,
        size_pt: int,
        line_height: float,
        justify: bool,
        column_width: int,
        letter_spacing: float = 0.0,
        word_spacing: float = 0.0,
        rerender: bool = True,
    ) -> None:
        """Apply the reading preferences and re-render the current page.

        Pass ``rerender=False`` when the caller is about to render a fresh page
        anyway -- re-rendering the *old* HTML first would show it at the wrong
        size, which is visible in layout mode.
        """
        self._theme = theme
        self._family = family
        self._size_pt = size_pt
        self._line_height = line_height
        self._justify = justify
        self._column_width = column_width
        self._letter_spacing = letter_spacing
        self._word_spacing = word_spacing
        self._apply_spacing()
        self._apply_column_margins()
        self.setStyleSheet(
            f"QTextBrowser {{ background-color: {theme.paper}; border: none; }}"
        )
        if self._body_html and rerender:
            self.re_render()

    def set_column_width(self, width: int) -> None:
        """Set the width of the text column (structure mode scales it per page)."""
        width = max(240, int(width))
        if width == self._column_width:
            return
        self._column_width = width
        self._apply_column_margins()

    def set_layout_mode(self, enabled: bool) -> None:
        """Tell the view whether the page is shown in its original layout.

        In layout mode the page brings its own vertical rhythm -- every block
        carries the margin the PDF gave it -- so the reading line-height from
        the preferences is not applied.  Stretching reconstructed pages to 1.5
        line spacing is exactly what made them look re-flowed.
        """
        enabled = bool(enabled)
        if enabled == self._layout_mode:
            return
        self._layout_mode = enabled
        self._apply_line_height()

    def set_document_margin(self, margin: int) -> None:
        """Set the document margin; structure mode keeps it small."""
        margin = max(0, int(margin))
        if margin == self._document_margin:
            return
        self._document_margin = margin
        if self._body_html:
            self.document().setDocumentMargin(margin)

    def _apply_spacing(self) -> None:
        """Push letter/word spacing onto the document's base font.

        Qt's rich-text CSS has no ``letter-spacing``, but spacing set on the
        default font survives the per-page CSS, which only changes the family
        and the size.
        """
        font = QFont(self._family, self._size_pt)
        if self._letter_spacing > 0:
            font.setLetterSpacing(
                QFont.SpacingType.AbsoluteSpacing, float(self._letter_spacing)
            )
        if self._word_spacing > 0:
            font.setWordSpacing(float(self._word_spacing))
        self.document().setDefaultFont(font)

    def _css(self) -> str:
        theme = self._theme
        assert theme is not None
        return theme.document_css(
            family=self._family,
            size_pt=self._size_pt,
            line_height=self._line_height,
            justify=self._justify,
        )

    def _apply_column_margins(self) -> None:
        """Centre the text column inside the viewport (short lines read better).

        The spare space is derived from the *content* width (viewport plus the
        margins we are about to change) rather than the raw viewport width:
        calling ``setViewportMargins`` resizes the viewport, which fires
        ``resizeEvent`` again -- deriving the target from the viewport alone
        would make the two states oscillate (and eventually blow the stack).
        """
        margins = self.viewportMargins()
        content_width = max(self.viewport().width(), 1) + margins.left() + margins.right()
        spare = max(0, content_width - self._column_width)
        left = spare // 2
        if (left, spare - left) == (margins.left(), margins.right()):
            return
        self.setViewportMargins(left, 0, spare - left, 0)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        super().resizeEvent(event)
        self._apply_column_margins()

    # ------------------------------------------------------------------ #
    # Page content
    # ------------------------------------------------------------------ #
    def show_page(self, body_html: str, *, heading: str = "") -> None:
        """Render one page: *body_html* plus an optional dimmed *heading*."""
        self._body_html = body_html
        self._page_heading = heading
        self._render()

    def re_render(self) -> None:
        """Re-render the current page, keeping the scroll position."""
        scroll = self.verticalScrollBar().value()
        self._render()
        self.verticalScrollBar().setValue(scroll)

    def clear_page(self) -> None:
        self._body_html = ""
        self._page_heading = ""
        self.clear()

    def _render(self) -> None:
        theme = self._theme
        if theme is None:
            return
        heading = ""
        if self._page_heading:
            safe = (
                self._page_heading.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )
            heading = f'<p class="pageinfo">{safe}</p>\n'
        self.setHtml(
            "<html><head><style>%s</style></head><body>%s%s</body></html>"
            % (self._css(), heading, self._body_html or "<p>&nbsp;</p>")
        )
        self.document().setDocumentMargin(self._document_margin)
        self._apply_line_height()
        if self._focus_mode:
            self._focus_block = -1
            self._focus_at(self.viewport().rect().center())
        if self._search_term:
            self.highlight_all(self._search_term, case_sensitive=self._case_sensitive)

    def _apply_line_height(self) -> None:
        """Set proportional line spacing on every block.

        Qt's rich-text engine does not implement CSS ``line-height`` reliably,
        so the block format is the dependable route.
        """
        try:
            cursor = QTextCursor(self.document())
            cursor.select(QTextCursor.SelectionType.Document)
            block_format = QTextBlockFormat()
            # Layout mode keeps the page's own spacing: the reconstructed page
            # encodes the PDF's vertical gaps as block margins.
            block_format.setLineHeight(
                (1.0 if self._layout_mode else self._line_height) * 100.0,
                QTextBlockFormat.LineHeightTypes.ProportionalHeight.value,
            )
            cursor.mergeBlockFormat(block_format)
        except Exception:
            # Line spacing is a nicety; never let it break page rendering.
            pass

    # ------------------------------------------------------------------ #
    # Formula images
    # ------------------------------------------------------------------ #
    def clear_images(self) -> None:
        self._images.clear()

    def add_image(self, png: bytes, device_pixel_ratio: float) -> tuple[str, float, float] | None:
        """Register a PNG rendered at *device_pixel_ratio*; returns
        ``(src, width, height)`` in logical pixels for an ``<img>`` tag."""
        image = QImage.fromData(png, "PNG")
        if image.isNull():
            return None
        image.setDevicePixelRatio(device_pixel_ratio)
        name = f"saccade-image:{len(self._images)}"
        self._images[name] = image
        return (name, image.width() / device_pixel_ratio,
                image.height() / device_pixel_ratio)

    def loadResource(self, kind: int, name: QUrl):  # noqa: N802 (Qt naming)
        image = self._images.get(name.toString())
        if image is not None:
            return image
        return super().loadResource(kind, name)

    @property
    def plain_text(self) -> str:
        """The text currently shown (without fixations)."""
        return self.document().toPlainText()

    # ------------------------------------------------------------------ #
    # Focus mode
    # ------------------------------------------------------------------ #
    def set_focus_mode(self, enabled: bool) -> None:
        """Dim every paragraph except the one being read.

        Long pages are hard to hold on to when attention wanders: dimming the
        surroundings gives the eye one obvious place to return to. The bright
        paragraph follows the mouse, and the middle of the page while scrolling,
        so it needs no keys of its own.
        """
        enabled = bool(enabled)
        if enabled == self._focus_mode:
            return
        self._focus_mode = enabled
        self._focus_block = -1
        if enabled:
            self._focus_at(self.viewport().rect().center())
        else:
            self._dim_selections = []
            self._apply_selections()

    @property
    def focus_mode(self) -> bool:
        return self._focus_mode

    def _focus_at(self, point) -> None:
        """Move the focus to the paragraph under *point* (viewport coords)."""
        block = self.cursorForPosition(point).blockNumber()
        if block != self._focus_block:
            self._focus_block = block
            self._rebuild_dimming()

    def _follow_scroll(self) -> None:
        if self._focus_mode:
            self._focus_at(self.viewport().rect().center())

    def _rebuild_dimming(self) -> None:
        theme = self._theme
        if not self._focus_mode or theme is None:
            return
        dim = QColor(theme.dim)
        selections: list[QTextEdit.ExtraSelection] = []
        document = self.document()
        block = document.begin()
        while block.isValid():
            if block.blockNumber() != self._focus_block and block.length() > 1:
                cursor = QTextCursor(block)
                cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
                selection = QTextEdit.ExtraSelection()
                selection.cursor = cursor
                fmt = QTextCharFormat()
                fmt.setForeground(dim)
                selection.format = fmt
                selections.append(selection)
            block = block.next()
        self._dim_selections = selections
        self._apply_selections()

    def _apply_selections(self) -> None:
        """Dimming first, so search highlights always paint on top."""
        self.setExtraSelections(self._dim_selections + self._search_selections)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        if self._focus_mode:
            self._focus_at(event.position().toPoint())
        super().mouseMoveEvent(event)

    # ------------------------------------------------------------------ #
    # Search highlighting
    # ------------------------------------------------------------------ #
    def highlight_all(self, term: str, *, case_sensitive: bool = False) -> int:
        """Highlight every occurrence of *term* on the current page."""
        self._search_term = term
        self._case_sensitive = case_sensitive
        self._search_selections = []
        if not term:
            self._apply_selections()
            return 0

        theme = self._theme
        background = QColor(theme.accent if theme else "#FFE08A")
        foreground = QColor(theme.paper if theme else "#1B1B1B")

        selections: list[QTextEdit.ExtraSelection] = []
        cursor = QTextCursor(self.document())
        while True:
            cursor = self.document().find(term, cursor, _find_flags(case_sensitive))
            if cursor.isNull():
                break
            selection = QTextEdit.ExtraSelection()
            selection.cursor = cursor
            fmt = QTextCharFormat()
            fmt.setBackground(background)
            fmt.setForeground(foreground)
            selection.format = fmt
            selections.append(selection)
        self._search_selections = selections
        self._apply_selections()
        return len(selections)

    def clear_highlights(self) -> None:
        """Remove all search highlights."""
        self._search_term = ""
        self._search_selections = []
        self._apply_selections()

    def find_next(
        self, term: str, *, backwards: bool = False, case_sensitive: bool = False
    ) -> bool:
        """Move the cursor to the next occurrence on this page (no wrapping)."""
        flags = _find_flags(case_sensitive)
        if backwards:
            flags |= QTextDocument.FindFlag.FindBackward
        cursor = self.document().find(term, self.textCursor(), flags)
        if cursor.isNull():
            return False
        self.setTextCursor(cursor)
        self.ensureCursorVisible()
        return True

    def find_first(self, term: str, *, case_sensitive: bool = False) -> bool:
        """Move the cursor to the first occurrence on this page."""
        self.moveCursor(QTextCursor.MoveOperation.Start)
        return self.find_next(term, case_sensitive=case_sensitive)

    # ------------------------------------------------------------------ #
    # Scrolling / paging behaviour
    # ------------------------------------------------------------------ #
    def at_bottom(self) -> bool:
        bar = self.verticalScrollBar()
        return bar.value() >= bar.maximum() - 2

    def at_top(self) -> bool:
        return self.verticalScrollBar().value() <= 2

    def scroll_by_screen(self, direction: int) -> None:
        bar = self.verticalScrollBar()
        step = max(40, self.viewport().height() - 60)
        bar.setValue(bar.value() + direction * step)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 (Qt naming)
        key = event.key()
        if key in (Qt.Key.Key_Space, Qt.Key.Key_Down):
            if self.at_bottom():
                self.page_turn_requested.emit(+1)
            else:
                self.scroll_by_screen(+1)
            event.accept()
            return
        if key == Qt.Key.Key_Up:
            if self.at_top():
                self.page_turn_requested.emit(-1)
            else:
                self.scroll_by_screen(-1)
            event.accept()
            return
        if key == Qt.Key.Key_Backspace:
            self.page_turn_requested.emit(-1)
            event.accept()
            return
        super().keyPressEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                self.zoom_requested.emit(1 if delta > 0 else -1)
            event.accept()
            return
        super().wheelEvent(event)
