"""Persisted preferences, reading positions and bookmarks.

Everything lives in ``QSettings`` (``~/.config/saccade/saccade.conf``
on Linux), so the reader remembers how you like to read and where you stopped.
Per-book data is keyed by a hash of the absolute path, which keeps keys short
and safe for book titles containing slashes or colons.
"""

from __future__ import annotations

import hashlib
import os

from PyQt6.QtCore import QByteArray, QSettings

from . import bionic
from .theme import DEFAULT_THEME

__all__ = [
    "Settings", "DEFAULT_FONT_FAMILY", "FONT_CHOICES",
    "ACCESSIBLE_FONTS", "available_fonts", "installed_accessible_fonts",
]

ORG_NAME = "saccade"
APP_NAME = "saccade"

#: Body fonts that ship with (almost) every Linux desktop and render bold well.
#: Bionic reading lives or dies by the contrast between regular and bold text,
#: so only fonts with a real bold face are offered.
FONT_CHOICES = (
    "DejaVu Serif",
    "DejaVu Sans",
    "Liberation Serif",
    "Liberation Sans",
    "Noto Serif",
    "Noto Sans",
    "Bitstream Vera Serif",
    "FreeSerif",
    "Nimbus Roman",
)

#: Fonts made for easier reading, best first.  Dyslexic readers often read
#: faster with wide, unambiguous letterforms (a "b" that cannot be mistaken for
#: a "d"); these are offered at the top of the font list when installed.
ACCESSIBLE_FONTS = (
    "OpenDyslexic",
    "OpenDyslexic3",
    "Atkinson Hyperlegible",
    "Lexend",
    "Lexend Deca",
    "Andika",
    "Comic Neue",
    "Verdana",
    "Tahoma",
)

#: How to install the fonts above, shown in the Help dialog.
FONT_PACKAGES = (
    ("OpenDyslexic", "Arch: yay -S ttf-opendyslexic  ·  Debian/Ubuntu: fonts-opendyslexic"),
    ("Atkinson Hyperlegible", "Arch: yay -S ttf-atkinson-hyperlegible  ·  Debian/Ubuntu: fonts-atkinson-hyperlegible"),
    ("Lexend", "Arch: yay -S ttf-lexend  ·  Debian/Ubuntu: fonts-lexend"),
)

DEFAULT_FONT_FAMILY = "DejaVu Serif"
DEFAULT_FONT_SIZE = 13
MIN_FONT_SIZE = 8
MAX_FONT_SIZE = 40
DEFAULT_LINE_HEIGHT = 1.5
DEFAULT_COLUMN_WIDTH = 700  # pixels; the text column is centred at this width
#: Extra space between letters and words, in pixels (0 = the font's own).
DEFAULT_LETTER_SPACING = 0.0
MAX_LETTER_SPACING = 6.0
DEFAULT_WORD_SPACING = 0.0
MAX_WORD_SPACING = 14.0


def installed_accessible_fonts() -> list[str]:
    """The easier-reading fonts from :data:`ACCESSIBLE_FONTS` present here."""
    from PyQt6.QtGui import QFontDatabase

    families = set(QFontDatabase.families())
    return [name for name in ACCESSIBLE_FONTS if name in families]


def available_fonts() -> list[str]:
    """Reading fonts to offer, easier-reading ones first."""
    accessible = installed_accessible_fonts()
    rest = [name for name in FONT_CHOICES if name not in accessible]
    return accessible + rest


class Settings:
    """Typed wrapper around :class:`QSettings`."""

    def __init__(self, settings: QSettings | None = None) -> None:
        self._s = settings or QSettings(ORG_NAME, APP_NAME)

    # ------------------------------------------------------------------ #
    # Reading preferences
    # ------------------------------------------------------------------ #
    @property
    def bionic_enabled(self) -> bool:
        return self._s.value("reading/bionic", True, type=bool)

    @bionic_enabled.setter
    def bionic_enabled(self, value: bool) -> None:
        self._s.setValue("reading/bionic", bool(value))

    @property
    def intensity(self) -> float:
        value = self._s.value("reading/intensity", bionic.DEFAULT_INTENSITY, type=float)
        return min(max(value, bionic.MIN_INTENSITY), bionic.MAX_INTENSITY)

    @intensity.setter
    def intensity(self, value: float) -> None:
        self._s.setValue("reading/intensity", float(value))

    @property
    def font_family(self) -> str:
        return self._s.value("reading/font_family", DEFAULT_FONT_FAMILY, type=str)

    @font_family.setter
    def font_family(self, value: str) -> None:
        self._s.setValue("reading/font_family", str(value))

    @property
    def font_size(self) -> int:
        value = self._s.value("reading/font_size", DEFAULT_FONT_SIZE, type=int)
        return min(max(value, MIN_FONT_SIZE), MAX_FONT_SIZE)

    @font_size.setter
    def font_size(self, value: int) -> None:
        self._s.setValue(
            "reading/font_size", min(max(int(value), MIN_FONT_SIZE), MAX_FONT_SIZE)
        )

    @property
    def line_height(self) -> float:
        value = self._s.value("reading/line_height", DEFAULT_LINE_HEIGHT, type=float)
        return min(max(value, 1.0), 2.5)

    @line_height.setter
    def line_height(self, value: float) -> None:
        self._s.setValue("reading/line_height", float(value))

    @property
    def theme(self) -> str:
        return self._s.value("reading/theme", DEFAULT_THEME, type=str)

    @theme.setter
    def theme(self, value: str) -> None:
        self._s.setValue("reading/theme", str(value))

    @property
    def justify(self) -> bool:
        return self._s.value("reading/justify", False, type=bool)

    @justify.setter
    def justify(self, value: bool) -> None:
        self._s.setValue("reading/justify", bool(value))

    @property
    def smart_paragraphs(self) -> bool:
        return self._s.value("reading/smart_paragraphs", True, type=bool)

    @smart_paragraphs.setter
    def smart_paragraphs(self, value: bool) -> None:
        self._s.setValue("reading/smart_paragraphs", bool(value))

    @property
    def faithful_layout(self) -> bool:
        """Keep each page's original layout instead of re-flowing its text.

        Off by default: the geometric reconstruction reads books with plain
        prose and simple tables fine, but on symbol-dense pages (inline math,
        footnote markers, stacked operator limits) it can misjudge which text
        runs belong on the same line and scramble the reading order, while
        plain re-flowed text stays in the PDF's own, correct extraction order.
        """
        return self._s.value("reading/faithful_layout", False, type=bool)

    @faithful_layout.setter
    def faithful_layout(self, value: bool) -> None:
        self._s.setValue("reading/faithful_layout", bool(value))

    @property
    def letter_spacing(self) -> float:
        """Extra pixels between letters; wider tracking helps dyslexic readers."""
        value = self._s.value("reading/letter_spacing", DEFAULT_LETTER_SPACING, type=float)
        return min(max(value, 0.0), MAX_LETTER_SPACING)

    @letter_spacing.setter
    def letter_spacing(self, value: float) -> None:
        self._s.setValue(
            "reading/letter_spacing", min(max(float(value), 0.0), MAX_LETTER_SPACING)
        )

    @property
    def word_spacing(self) -> float:
        """Extra pixels between words, which makes word shapes easier to pick out."""
        value = self._s.value("reading/word_spacing", DEFAULT_WORD_SPACING, type=float)
        return min(max(value, 0.0), MAX_WORD_SPACING)

    @word_spacing.setter
    def word_spacing(self, value: float) -> None:
        self._s.setValue(
            "reading/word_spacing", min(max(float(value), 0.0), MAX_WORD_SPACING)
        )

    @property
    def focus_mode(self) -> bool:
        """Dim every paragraph but the one being read."""
        return self._s.value("reading/focus_mode", False, type=bool)

    @focus_mode.setter
    def focus_mode(self, value: bool) -> None:
        self._s.setValue("reading/focus_mode", bool(value))

    @property
    def column_width(self) -> int:
        return self._s.value("reading/column_width", DEFAULT_COLUMN_WIDTH, type=int)

    @column_width.setter
    def column_width(self, value: int) -> None:
        self._s.setValue("reading/column_width", int(value))

    # ------------------------------------------------------------------ #
    # Window state
    # ------------------------------------------------------------------ #
    def window_geometry(self) -> QByteArray | None:
        value = self._s.value("window/geometry")
        return value if isinstance(value, QByteArray) and not value.isEmpty() else None

    def set_window_geometry(self, blob: QByteArray) -> None:
        self._s.setValue("window/geometry", blob)

    def window_state(self) -> QByteArray | None:
        value = self._s.value("window/state")
        return value if isinstance(value, QByteArray) and not value.isEmpty() else None

    def set_window_state(self, blob: QByteArray) -> None:
        self._s.setValue("window/state", blob)

    @property
    def sidebar_visible(self) -> bool:
        return self._s.value("window/sidebar", True, type=bool)

    @sidebar_visible.setter
    def sidebar_visible(self, value: bool) -> None:
        self._s.setValue("window/sidebar", bool(value))

    # ------------------------------------------------------------------ #
    # Per-book data
    # ------------------------------------------------------------------ #
    @staticmethod
    def _book_key(path: str) -> str:
        digest = hashlib.sha1(os.path.abspath(path).encode("utf-8")).hexdigest()[:16]
        return f"books/{digest}"

    def last_page(self, path: str) -> int:
        """0-based page the reader was last on, or 0."""
        return self._s.value(f"{self._book_key(path)}/page", 0, type=int)

    def set_last_page(self, path: str, page: int) -> None:
        self._s.setValue(f"{self._book_key(path)}/page", int(page))

    def bookmarks(self, path: str) -> list[tuple[int, str]]:
        """Saved bookmarks as ``(page, label)`` pairs, sorted by page."""
        raw = self._s.value(f"{self._book_key(path)}/bookmarks", [], type=list) or []
        marks: list[tuple[int, str]] = []
        for item in raw:
            page_str, _, label = str(item).partition("\t")
            try:
                marks.append((int(page_str), label))
            except ValueError:
                continue
        return sorted(marks)

    def set_bookmarks(self, path: str, marks: list[tuple[int, str]]) -> None:
        payload = [f"{int(page)}\t{label}" for page, label in sorted(marks)]
        self._s.setValue(f"{self._book_key(path)}/bookmarks", payload)

    def add_bookmark(self, path: str, page: int, label: str) -> list[tuple[int, str]]:
        """Add/replace the bookmark of *page*; returns the new list."""
        marks = [m for m in self.bookmarks(path) if m[0] != page]
        marks.append((int(page), label))
        self.set_bookmarks(path, marks)
        return sorted(marks)

    def remove_bookmark(self, path: str, page: int) -> list[tuple[int, str]]:
        marks = [m for m in self.bookmarks(path) if m[0] != page]
        self.set_bookmarks(path, marks)
        return marks

    # ------------------------------------------------------------------ #
    # Recent files
    # ------------------------------------------------------------------ #
    def recent_files(self, limit: int = 10) -> list[str]:
        raw = self._s.value("recent/files", [], type=list) or []
        return [str(item) for item in raw if os.path.exists(str(item))][:limit]

    def add_recent_file(self, path: str, limit: int = 10) -> None:
        path = os.path.abspath(path)
        files = [p for p in self.recent_files(limit * 2) if p != path]
        files.insert(0, path)
        self._s.setValue("recent/files", files[:limit])

    def clear_recent_files(self) -> None:
        self._s.setValue("recent/files", [])

    def sync(self) -> None:
        self._s.sync()
