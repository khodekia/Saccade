"""Build small PDF files on the fly, for tests and for a demo book.

Requires PyMuPDF (which is the reader's primary text engine anyway); the tests
that use these helpers skip themselves when it is missing.
"""

from __future__ import annotations

import os

#: Three short "book" pages.  Page two deliberately contains a word split over
#: a hyphenated line break, which is what :func:`document.reflow` must undo.
BOOK_PAGES = (
    "Chapter One\n\n"
    "Bionic reading is a technique that bolds the beginning of every word so "
    "that the eye is guided from fixation point to fixation point. The brain "
    "fills in the remaining letters, which many readers find faster and more "
    "comfortable than reading every letter consciously.\n",
    "Chapter Two\n\n"
    "This second page exists to test the reader: it contains a long "
    "exam-\n"
    "ple of a hyphenated word broken across two lines, plus punctuation, "
    "numbers like 42 and 1,000, and an apostrophe: don't.\n",
    "A Subsection\n\n"
    "The final page is short. It ends the sample book so that page navigation, "
    "progress reporting and search all have something to work with.\n",
)

TITLE = "The Bionic Sample"
AUTHOR = "Test Author"

OUTLINE = (
    (1, "Chapter One", 1),
    (1, "Chapter Two", 2),
    (2, "A Subsection", 3),
)


def _pymupdf():
    from saccade.document import _pymupdf as resolver

    module = resolver()
    if module is None:  # pragma: no cover - depends on the environment
        raise ImportError("PyMuPDF is not installed")
    return module


def available() -> bool:
    """True when PyMuPDF can be imported (needed to write the fixtures)."""
    try:
        _pymupdf()
    except Exception:
        return False
    return True


def build_book(path: str, *, pages: tuple[str, ...] = BOOK_PAGES,
               with_outline: bool = True) -> str:
    """Write a small multi-page PDF with metadata (and an outline) to *path*."""
    pymupdf = _pymupdf()
    document = pymupdf.open()
    for text in pages:
        page = document.new_page()
        page.insert_textbox(
            pymupdf.Rect(72, 72, 523, 720), text, fontsize=11, fontname="helv"
        )
    if with_outline:
        document.set_toc([list(entry) for entry in OUTLINE])
    document.set_metadata({"title": TITLE, "author": AUTHOR})
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    document.save(path)
    document.close()
    return path


def build_scanned(path: str) -> str:
    """Write a one-page PDF that has only graphics, i.e. no text layer."""
    pymupdf = _pymupdf()
    document = pymupdf.open()
    page = document.new_page()
    shape = page.new_shape()
    for index in range(12):
        top = 80 + index * 40
        shape.draw_rect(pymupdf.Rect(72, top, 520, top + 8))
    shape.finish(fill=(0.2, 0.2, 0.2))
    shape.commit()
    document.save(path)
    document.close()
    return path


#: A page with the kind of layout a real book has: a large centred title, a
#: table-of-contents row whose page number is set flush right, and a two-column
#: body.  ``document.reflow`` throws all of that away; ``layout.to_html`` must
#: keep it, so the tests need a PDF that really contains it.
def build_magazine(path: str) -> str:
    """Write a 2-page PDF with a title, a TOC row and two columns of text."""
    pymupdf = _pymupdf()
    document = pymupdf.open()

    # -- page 1: display title + a table-of-contents row ------------------- #
    page = document.new_page()
    page.insert_textbox(
        pymupdf.Rect(60, 90, 535, 150), "Combating Surveillance",
        fontsize=30, fontname="hebo", align=pymupdf.TEXT_ALIGN_CENTER,
    )
    page.insert_text(pymupdf.Point(60, 250), "What are CCTV Cameras?", fontsize=12)
    page.insert_text(pymupdf.Point(500, 250), "5", fontsize=12)
    page.insert_text(pymupdf.Point(60, 280), "Why destroy them?", fontsize=12)
    page.insert_text(pymupdf.Point(500, 280), "9", fontsize=12)

    # -- page 2: two columns of ordinary body text ------------------------- #
    page = document.new_page()
    left = (
        "Cameras watch the street from every corner. A camera that nobody "
        "watches is still a camera that somebody could watch, and the "
        "recording outlives the moment it was made."
    )
    right = (
        "Records are copied, shared and stored. What is captured once can be "
        "replayed forever, so the question is not what a camera sees today but "
        "what its footage will mean later."
    )
    page.insert_textbox(pymupdf.Rect(50, 100, 290, 400), left, fontsize=11)
    page.insert_textbox(pymupdf.Rect(320, 100, 560, 400), right, fontsize=11)

    document.set_metadata({"title": "Surveillance Sample"})
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    document.save(path)
    document.close()
    return path

def build_scan(path: str, *, pages: int = 2) -> str:
    """Write a PDF that looks like a scan: a full-page image per page.

    Scanned books are the case where the text layer comes from OCR, so the
    reader must recognise them and show the page itself.
    """
    pymupdf = _pymupdf()
    document = pymupdf.open()
    for number in range(pages):
        page = document.new_page()
        pixmap = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 800, 1000), False)
        pixmap.clear_with(235)
        page.insert_image(page.rect, pixmap=pixmap)
        page.insert_text((72, 96), f"scanned page {number + 1}", fontsize=11)
    document.save(path)
    document.close()
    return path
