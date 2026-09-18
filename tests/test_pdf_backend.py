"""Integration tests for PDF loading, extraction, re-flowing and caching.

The tests build their own small PDF with PyMuPDF and then check every installed
backend against it, so they run on any machine that has at least one engine.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from saccade.document import (
    DocumentError,
    PyMuPdfBackend,
    PdftotextBackend,
    PypdfBackend,
    available_backends,
    open_document,
)

from . import pdf_fixture


@unittest.skipUnless(pdf_fixture.available(), "PyMuPDF is needed to build the fixture")
class DocumentTests(unittest.TestCase):
    """Tests that need a real (tiny) PDF file."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.pdf = pdf_fixture.build_book(os.path.join(cls._tmp.name, "book.pdf"))
        cls.scanned = pdf_fixture.build_scanned(
            os.path.join(cls._tmp.name, "scanned.pdf")
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    # ------------------------------------------------------------------ #
    def test_page_count_and_metadata(self) -> None:
        with open_document(self.pdf) as document:
            self.assertEqual(document.page_count, 3)
            self.assertEqual(document.metadata["title"], pdf_fixture.TITLE)
            self.assertEqual(document.metadata["author"], pdf_fixture.AUTHOR)
            self.assertEqual(document.display_title, pdf_fixture.TITLE)
            self.assertEqual(document.name, "book.pdf")

    def test_page_text_and_reflow(self) -> None:
        with open_document(self.pdf) as document:
            first = document.page_text(0)
            self.assertIn("Bionic reading is a technique", first)
            # The hyphenated line break must be re-joined by reflow().
            second = document.page_text(1)
            self.assertIn("example", second)
            self.assertNotIn("exam-", second)
            self.assertIn("don't", second)

    def test_pages_are_cached(self) -> None:
        with open_document(self.pdf) as document:
            self.assertIs(document.page_text(0), document.page_text(0))
            self.assertIs(document.raw_text(0), document.raw_text(0))

    def test_outline(self) -> None:
        with open_document(self.pdf) as document:
            entries = document.toc
            if document.backend_name == PdftotextBackend.name:
                self.assertEqual(entries, [])  # poppler CLI has no outline
                return
            self.assertEqual([entry.title for entry in entries],
                             ["Chapter One", "Chapter Two", "A Subsection"])
            self.assertEqual([entry.level for entry in entries], [1, 1, 2])
            self.assertEqual([entry.page for entry in entries], [0, 1, 2])

    def test_out_of_range_pages_are_empty(self) -> None:
        with open_document(self.pdf) as document:
            self.assertEqual(document.page_text(-1), "")
            self.assertEqual(document.page_text(99), "")

    def test_word_count_and_reading_state(self) -> None:
        with open_document(self.pdf) as document:
            self.assertGreater(document.words_on_page(0), 20)
            self.assertFalse(document.looks_scanned)

    def test_scanned_pdf_is_detected(self) -> None:
        with open_document(self.scanned) as document:
            self.assertTrue(document.looks_scanned)
            self.assertEqual(document.page_text(0), "")

    def test_missing_file(self) -> None:
        with self.assertRaises(DocumentError):
            open_document(os.path.join(self._tmp.name, "nope.pdf"))

    def test_directory_is_rejected(self) -> None:
        with self.assertRaises(DocumentError):
            open_document(self._tmp.name)

    def test_unknown_backend_is_rejected(self) -> None:
        with self.assertRaises(DocumentError):
            open_document(self.pdf, backend="telepathy")

    def test_every_available_backend_reads_the_book(self) -> None:
        names = available_backends()
        self.assertTrue(names, "at least one backend should be installed")
        for name in names:
            with self.subTest(backend=name), open_document(self.pdf, backend=name) as doc:
                self.assertEqual(doc.page_count, 3)
                self.assertIn("Bionic reading", doc.page_text(0))

    def test_smart_paragraphs_can_be_toggled(self) -> None:
        with open_document(self.pdf) as document:
            paragraphs = document.page_text(1).count("\n\n")
            document.set_smart_paragraphs(False)
            self.assertLessEqual(document.page_text(1).count("\n\n"), paragraphs)

    def test_backend_names_are_stable(self) -> None:
        self.assertEqual(
            [PyMuPdfBackend.name, PypdfBackend.name, PdftotextBackend.name],
            ["PyMuPDF", "pypdf", "pdftotext"],
        )


if __name__ == "__main__":
    unittest.main()

@unittest.skipUnless(pdf_fixture.available(), "PyMuPDF is needed to build the fixture")
class ScannedPageTests(unittest.TestCase):
    """A page that is one big image is a scan, whatever its text layer says."""

    def test_scan_is_recognised_and_normal_pages_are_not(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            scan = pdf_fixture.build_scan(os.path.join(folder, "scan.pdf"))
            book = pdf_fixture.build_book(os.path.join(folder, "book.pdf"))
            with open_document(scan) as document:
                self.assertTrue(document.page_layout(0).is_scan)
            with open_document(book) as document:
                self.assertFalse(document.page_layout(0).is_scan)
