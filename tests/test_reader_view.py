"""The reading column must wrap to the width it is actually shown at."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from saccade.theme import get_theme
from saccade.ui.reader_view import ReadingView


class ColumnWidthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def make_view(self, column: int) -> ReadingView:
        view = ReadingView()
        self.addCleanup(view.deleteLater)
        view.resize(900, 600)
        view.show()
        self.app.processEvents()
        view.configure(theme=get_theme("paper"), family="DejaVu Serif", size_pt=14,
                       line_height=1.5, justify=False, column_width=column)
        view.show_page("<p>" + "word " * 400 + "</p>")
        self.app.processEvents()
        return view

    def make_view_configured_before_show(self, column: int) -> ReadingView:
        """The order the real window uses: set up first, shown afterwards."""
        view = ReadingView()
        self.addCleanup(view.deleteLater)
        view.configure(theme=get_theme("paper"), family="DejaVu Serif", size_pt=14,
                       line_height=1.5, justify=False, column_width=column)
        view.show_page("<p>" + "word " * 400 + "</p>")
        view.resize(900, 600)
        view.show()
        self.app.processEvents()
        return view

    def assert_wraps_to_viewport(self, view: ReadingView) -> None:
        self.assertEqual(view.viewport().width(), view._column_width)
        self.assertLessEqual(view.document().textWidth(), view.viewport().width())

    def test_text_wraps_to_the_column_not_the_whole_view(self) -> None:
        """Otherwise the end of every line is cut off, with no way to scroll."""
        self.assert_wraps_to_viewport(self.make_view(600))

    def test_text_wraps_when_set_up_before_the_window_appears(self) -> None:
        self.assert_wraps_to_viewport(self.make_view_configured_before_show(600))

    def test_changing_the_column_rewraps_the_text(self) -> None:
        view = self.make_view(600)
        view.set_column_width(500)
        self.app.processEvents()
        self.assert_wraps_to_viewport(view)

    def test_resizing_the_window_keeps_the_column(self) -> None:
        view = self.make_view(600)
        view.resize(1200, 600)
        self.app.processEvents()
        self.assert_wraps_to_viewport(view)
