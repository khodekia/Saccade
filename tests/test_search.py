"""The background full-book search must actually find text."""

from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from saccade.document import open_document
from saccade.ui.search import SearchWorker

from . import pdf_fixture


@unittest.skipUnless(pdf_fixture.available(), "PyMuPDF is needed to build the fixture")
class SearchWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        cls.tmp = tempfile.TemporaryDirectory()
        cls.path = os.path.join(cls.tmp.name, "book.pdf")
        pdf_fixture.build_book(cls.path)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def search(self, query: str, **kwargs) -> list:
        with open_document(self.path) as document:
            worker = SearchWorker(document, query, **kwargs)
            results: list = []
            worker.hits_found.connect(results.append)
            worker.start()
            worker.wait(15000)
            self.app.processEvents()
        self.assertEqual(len(results), 1)
        return results[0]

    def test_finds_a_word_on_its_page(self) -> None:
        hits = self.search("hyphenated")
        self.assertEqual([hit.page for hit in hits], [1])
        self.assertIn("hyphenated", hits[0].snippet)

    def test_case_sensitive_search_respects_case(self) -> None:
        self.assertEqual(self.search("HYPHENATED", case_sensitive=True), [])
        self.assertEqual(len(self.search("HYPHENATED")), 1)
