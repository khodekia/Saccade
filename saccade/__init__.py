"""Saccade -- read PDF books on Linux with bionic-reading fixations.

The package is split into dependency-light layers:

``saccade.bionic``
    Pure text -> bionic-fixation transformation (no dependencies).
``saccade.document``
    PDF loading, page-text extraction and re-flowing (PyMuPDF / pypdf / pdftotext).
``saccade.theme``
    Colour palettes and the CSS used by the reading view.
``saccade.settings``
    Persisted preferences (``QSettings``) and per-book reading positions.
``saccade.ui``
    The PyQt6 user interface.
"""

from __future__ import annotations

__version__ = "0.9.1"
__all__ = ["__version__"]
