"""PDF loading and page-text extraction with pluggable backends.

Reading a book with bionic fixations only needs the *text* of each page, not a
rendered bitmap, so this module focuses on fast, lazy text extraction.

Three interchangeable backends are supported and probed in this order:

1. :class:`PyMuPdfBackend` -- best text quality/reading order (``pip install pymupdf``).
2. :class:`PypdfBackend`   -- pure Python, no build tools needed (``pip install pypdf``).
3. :class:`PdftotextBackend` -- the poppler ``pdftotext`` binary, so the app still
   works on a machine where no Python wheel could be installed.

:func:`open_document` picks the first available backend that can actually open
the file, and :class:`Document` adds re-flowing (de-hyphenation, paragraph
detection) plus caching on top of it.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import unicodedata
from dataclasses import dataclass

from .bionic import normalize_text, word_count
from .layout import ImageBox, PageLayout, Span
from .layout import body_size, plain_text as layout_plain_text

__all__ = [
    "BackendUnavailable",
    "Document",
    "DocumentError",
    "TocEntry",
    "available_backends",
    "backend_names",
    "reflow",
]


class DocumentError(RuntimeError):
    """Raised when a document cannot be opened or read."""


class BackendUnavailable(DocumentError):
    """Raised when a backend's dependency is not installed."""


def _pymupdf():
    """Return the PyMuPDF module, or ``None`` when it is not installed.

    Newer releases are imported as ``pymupdf``; the historical ``fitz`` name
    still works but emits a ``DeprecationWarning``, so it is only used as a
    fallback for older versions.
    """
    try:
        import pymupdf

        return pymupdf
    except Exception:  # pragma: no cover - depends on the environment
        pass
    try:
        import fitz

        return fitz
    except Exception:
        return None


@dataclass(frozen=True)
class TocEntry:
    """One entry of the PDF outline; ``page`` is a 0-based page index."""

    level: int
    title: str
    page: int


# --------------------------------------------------------------------------- #
# Text re-flowing
# --------------------------------------------------------------------------- #

_HYPHEN_CHARS = ("-", "\u2010", "\u2011")

#: Horizontal whitespace (including the non-breaking spaces poppler emits).
_WHITESPACE_RE = re.compile(r"[ \t\u00a0\u2000-\u200a]+")


def reflow(raw: str, *, smart_paragraphs: bool = True, dehyphenate: bool = True) -> str:
    """Turn the line-per-line text of a PDF page into readable paragraphs.

    * lines ending in ``-`` are joined with the following line (``exam-`` +
      ``ple`` -> ``example``), which is how books are typeset;
    * an indented line starts a new paragraph (typographic first-line indent),
      which is the only reliable paragraph signal in extracted book text;
    * blank lines always separate paragraphs;
    * runs of spaces/tabs are collapsed, because PDF extraction of justified
      text frequently yields double and triple spaces;
    * paragraphs are separated by a blank line so that
      :func:`saccade.bionic.to_html` re-splits them.
    """
    text = normalize_text(raw).replace("\r\n", "\n").replace("\r", "\n")
    paragraphs: list[str] = []
    current: list[str] = []

    for line in text.split("\n"):
        stripped = _WHITESPACE_RE.sub(" ", line).strip()
        if not stripped:
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue

        if not current:
            current.append(stripped)
            continue

        if smart_paragraphs and line[:1] in (" ", "\t"):
            paragraphs.append(" ".join(current))
            current = [stripped]
            continue

        if (
            dehyphenate
            and current[-1].endswith(_HYPHEN_CHARS)
            and stripped[:1].islower()
        ):
            current[-1] = current[-1][:-1] + stripped
            continue

        current.append(stripped)

    if current:
        paragraphs.append(" ".join(current))
    return "\n\n".join(paragraphs)


# --------------------------------------------------------------------------- #
# Backends
# --------------------------------------------------------------------------- #


class PdfBackend:
    """Common interface implemented by every extraction backend."""

    #: Human readable name, shown in the status bar.
    name = "?"
    #: ``pip``/system package that would provide this backend.
    requirement = ""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = os.fspath(path)
        self.page_count = 0

    @classmethod
    def available(cls) -> bool:
        """True when the backend's dependency is importable/present."""
        raise NotImplementedError

    def raw_page_text(self, index: int) -> str:
        """Verbatim text of page *index* (0-based), as the backend sees it."""
        raise NotImplementedError

    def page_layout(self, index: int) -> PageLayout | None:
        """Geometry of page *index*: text spans and placed images.

        Backends that cannot report positions return ``None``, and the reader
        falls back to showing re-flowed text for that document.
        """
        return None

    def toc(self) -> list[TocEntry]:
        """Outline of the document, empty list when the PDF has none."""
        return []

    def metadata(self) -> dict[str, str]:
        """Document metadata (``title``, ``author``); may be empty."""
        return {}

    def close(self) -> None:
        """Release resources."""


def _font_flags(flags: int, font: str) -> tuple[bool, bool]:
    """``(bold, italic)`` for a PyMuPDF span, from its flags and font name."""
    name = (font or "").lower()
    bold = bool(flags & 16) or any(
        token in name for token in ("bold", "black", "heavy", "semibold", "demibold")
    )
    italic = bool(flags & 2) or any(
        token in name for token in ("italic", "oblique", "slanted")
    )
    return bold, italic


#: Math "extension" fonts: big operators, radicals and growing delimiters.
_BIG_GLYPH_FONTS = ("cmex", "blex", "mtex", "txex", "pxex", "lmex", "euex", "esint")


def _is_big_glyph_font(font: str) -> bool:
    return font.rsplit("+", 1)[-1].lower().startswith(_BIG_GLYPH_FONTS)


def _is_stretched_glyph(text: str, font: str, height: float, size: float) -> bool:
    """True for a glyph whose reported box cannot be trusted.

    Grown delimiters, radicals and big operators (a root sign drawn around a
    whole fraction) report the font's nominal box, which is both far taller
    than the mark and often in the wrong place, so their real ink is measured.
    """
    if _is_big_glyph_font(font):
        return True
    return len(text.strip()) <= 2 and size > 0 and height > 2.5 * size


def _link_target(links, x0: float, y0: float, x1: float, y1: float) -> int | None:
    """Target page of the link whose area contains the span's centre, if any."""
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    for lx0, ly0, lx1, ly1, target in links:
        if lx0 - 1 <= cx <= lx1 + 1 and ly0 - 1 <= cy <= ly1 + 1:
            return target
    return None


#: Image containers Qt can display, by the extension PyMuPDF reports.
_IMAGE_MIME = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "bmp": "image/bmp",
    "webp": "image/webp",
}


class PyMuPdfBackend(PdfBackend):
    """PyMuPDF (``fitz``): fastest and best quality, used when installed."""

    name = "PyMuPDF"
    requirement = "pymupdf"

    @classmethod
    def available(cls) -> bool:
        return _pymupdf() is not None

    def __init__(self, path: str | os.PathLike[str]) -> None:
        super().__init__(path)
        fitz = _pymupdf()
        if fitz is None:  # pragma: no cover - guarded by available()
            raise BackendUnavailable("PyMuPDF is not installed")
        self._fitz = fitz
        self._doc = fitz.open(self.path)
        self.page_count = int(self._doc.page_count)

    def raw_page_text(self, index: int) -> str:
        if not 0 <= index < self.page_count:
            return ""
        return self._doc.load_page(index).get_text("text") or ""

    def page_layout(self, index: int) -> PageLayout | None:
        """Spans and images of page *index* with their exact geometry."""
        if not 0 <= index < self.page_count:
            return None
        page = self._doc.load_page(index)
        rect = page.rect
        spans: list[Span] = []
        try:
            payload = page.get_text("dict")
        except Exception:
            return None
        links = self._page_links(page)
        for block_no, block in enumerate(payload.get("blocks", ())):
            if block.get("type") != 0:
                continue
            for line_no, line in enumerate(block.get("lines", ())):
                for item in line.get("spans", ()):
                    text = item.get("text") or ""
                    # Keep whitespace-only spans: they are the word spaces
                    # between runs that flow mode joins back together.
                    if not text:
                        continue
                    x0, y0, x1, y1 = item.get("bbox", (0, 0, 0, 0))
                    font = str(item.get("font") or "")
                    bold, italic = _font_flags(int(item.get("flags") or 0), font)
                    origin = item.get("origin")
                    ink = (None, None)
                    size = float(item.get("size") or 10.0)
                    if text.strip() and _is_stretched_glyph(text, font, y1 - y0, size):
                        ink = self._ink_extent(page, x0, y0, x1, y1, size)
                    spans.append(Span(
                        text=text,
                        size=float(item.get("size") or 0.0),
                        font=font,
                        bold=bold,
                        italic=italic,
                        color=int(item.get("color") or 0),
                        x0=float(x0), y0=float(y0), x1=float(x1), y1=float(y1),
                        origin_y=float(origin[1]) if origin else None,
                        ink_y0=ink[0],
                        ink_y1=ink[1],
                        block=block_no,
                        line=line_no,
                        link_page=_link_target(links, x0, y0, x1, y1),
                    ))
        return PageLayout(
            width=float(rect.width),
            height=float(rect.height),
            spans=tuple(spans),
            images=self._page_images(page),
            rules=self._page_rules(page),
            is_scan=self._is_scan(page),
        )

    def _is_scan(self, page) -> bool:
        """True when the page is a photograph of a page with text laid over it.

        Scanned books carry an OCR text layer whose mathematics is unreliable
        ("x \u2208 \u2124" comes back as "x E Z"), so the reader shows the scan
        itself rather than re-flowing a bad transcription.
        """
        try:
            infos = page.get_image_info()
        except Exception:
            return False
        area = page.rect.width * page.rect.height
        if area <= 0:
            return False
        for info in infos:
            x0, y0, x1, y1 = info.get("bbox", (0, 0, 0, 0))
            if (x1 - x0) * (y1 - y0) >= 0.7 * area and int(info.get("width") or 0) >= 500:
                return True
        return False

    def _page_rules(self, page) -> tuple[tuple[float, float, float, float], ...]:
        """Thin horizontal lines: fraction bars, radicals' overbars, rules."""
        found: list[tuple[float, float, float, float]] = []
        try:
            drawings = page.get_drawings()
        except Exception:
            return ()
        for drawing in drawings:
            rect = drawing.get("rect")
            if rect is None or rect.height > 2.0 or rect.width < 3.0:
                continue
            found.append((float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)))
            if len(found) >= 400:  # a ruled table, not formulas
                return ()
        return tuple(found)

    def _ink_extent(self, page, x0: float, y0: float, x1: float, y1: float,
                    size: float) -> tuple[float, float]:
        """True vertical extent of a big math glyph (``\\bigcup``, ``\\sum``,
        large delimiters).

        Their fonts report a nominal line box, far shorter than the glyph that
        is drawn. A glyph like that is one connected stroke, so flood-filling
        the ink that touches the reported box -- inside the glyph's own column
        -- recovers its real height without picking up neighbouring lines.
        """
        zoom = 4.0
        fitz = self._fitz
        top, bottom = y0 - 1.5 * size, y1 + 2.0 * size
        try:
            pix = page.get_pixmap(
                matrix=fitz.Matrix(zoom, zoom), clip=fitz.Rect(x0, top, x1, bottom),
                colorspace=fitz.csGRAY, alpha=False,
            )
        except Exception:
            return y0, y1
        width, height, samples = pix.width, pix.height, pix.samples
        if not width or not height:
            return y0, y1
        dark = lambda px, py: samples[py * width + px] < 160  # noqa: E731
        seed_top = max(0, int((y0 - top) * zoom))
        seed_bottom = min(height, int((y1 - top) * zoom) + 1)
        seeds = [(px, py) for py in range(seed_top, seed_bottom) for px in range(width)
                 if dark(px, py)]
        seen: set[tuple[int, int]] = set()
        best = (0, 0, 0)  # (pixels, low, high) of the largest shape
        for seed in seeds:
            if seed in seen:
                continue
            seen.add(seed)
            stack, count, low, high = [seed], 0, height, 0
            while stack:
                px, py = stack.pop()
                count += 1
                low, high = min(low, py), max(high, py)
                for nx in (px - 1, px, px + 1):
                    for ny in (py - 1, py, py + 1):
                        if (0 <= nx < width and 0 <= ny < height
                                and (nx, ny) not in seen and dark(nx, ny)):
                            seen.add((nx, ny))
                            stack.append((nx, ny))
            # The reported box can be shifted onto a neighbouring line's
            # letters; the glyph itself is the biggest connected shape.
            if count > best[0]:
                best = (count, low, high)
        if not best[0]:
            return y0, y1
        return top + best[1] / zoom, top + (best[2] + 1) / zoom

    def render_clip(self, index: int, rect, zoom: float, ink: int, paper: int,
                    pad_top: float = 0.0, pad_bottom: float = 0.0) -> bytes | None:
        """PNG of *rect* on page *index* with blank padding above/below (in
        points); black is mapped to *ink* and white to *paper*."""
        if not 0 <= index < self.page_count:
            return None
        fitz = self._fitz
        try:
            page = self._doc.load_page(index)
            clip = fitz.Rect(*rect) & page.rect
            if clip.is_empty:
                return None
            crop = page.get_pixmap(
                matrix=fitz.Matrix(zoom, zoom), clip=clip, alpha=False,
                colorspace=fitz.csRGB,
            )
            top = int(round(pad_top * zoom))
            bottom = int(round(pad_bottom * zoom))
            canvas = fitz.Pixmap(
                fitz.csRGB, fitz.IRect(0, 0, crop.width, crop.height + top + bottom), False
            )
            canvas.clear_with(255)
            crop.set_origin(0, top)
            canvas.copy(crop, crop.irect)
            canvas.tint_with(ink, paper)
            return canvas.tobytes("png")
        except Exception:
            return None

    def _page_links(self, page) -> list[tuple[float, float, float, float, int]]:
        """Internal jumps on *page* as ``(x0, y0, x1, y1, target_page)``."""
        found: list[tuple[float, float, float, float, int]] = []
        try:
            links = page.get_links()
        except Exception:
            return found
        for link in links:
            target = link.get("page")
            rect = link.get("from")
            if not isinstance(target, int) or not 0 <= target < self.page_count or rect is None:
                continue
            found.append((float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1), target))
        return found

    def _page_images(self, page) -> tuple[ImageBox, ...]:
        """Placed images of a page, smallest first, as embedded bytes."""
        boxes: list[ImageBox] = []
        seen: set[tuple[int, int, int, int, int]] = set()
        try:
            infos = page.get_image_info(xrefs=True)
        except Exception:
            return ()
        for info in infos:
            xref = int(info.get("xref") or 0)
            x0, y0, x1, y1 = (float(value) for value in info.get("bbox", (0, 0, 0, 0)))
            pixel_w = int(info.get("width") or 0)
            pixel_h = int(info.get("height") or 0)
            # Ignore hairlines, spacer graphics and duplicate placements.
            if xref <= 0 or x1 - x0 < 6 or y1 - y0 < 6 or pixel_w < 8 or pixel_h < 8:
                continue
            key = (xref, int(x0), int(y0), int(x1), int(y1))
            if key in seen:
                continue
            seen.add(key)
            try:
                payload = self._doc.extract_image(xref)
            except Exception:
                continue
            data = payload.get("image") if payload else None
            mime = _IMAGE_MIME.get(str((payload or {}).get("ext") or "").lower())
            if not data or mime is None:
                continue  # an image format Qt cannot show (e.g. JPEG 2000)
            boxes.append(ImageBox(
                data=data,
                mime=mime,
                x0=x0, y0=y0, x1=x1, y1=y1,
                pixel_width=pixel_w,
                pixel_height=pixel_h,
            ))
        boxes.sort(key=lambda box: box.x0)
        return tuple(boxes)

    def toc(self) -> list[TocEntry]:
        entries: list[TocEntry] = []
        for item in self._doc.get_toc(simple=True) or []:
            try:
                level, title, page = item[0], item[1], item[2]
            except (TypeError, IndexError):
                continue
            entries.append(TocEntry(int(level), str(title).strip(), max(0, int(page) - 1)))
        return entries

    def metadata(self) -> dict[str, str]:
        meta = self._doc.metadata or {}
        return {
            "title": (meta.get("title") or "").strip(),
            "author": (meta.get("author") or "").strip(),
        }

    def close(self) -> None:
        try:
            self._doc.close()
        except Exception:
            pass


class PypdfBackend(PdfBackend):
    """pypdf: pure Python fallback, no compiler or system library required."""

    name = "pypdf"
    requirement = "pypdf"

    @classmethod
    def available(cls) -> bool:
        try:
            import pypdf  # noqa: F401
        except Exception:
            return False
        return True

    def __init__(self, path: str | os.PathLike[str]) -> None:
        super().__init__(path)
        from pypdf import PdfReader

        self._reader = PdfReader(self.path)
        if getattr(self._reader, "is_encrypted", False):
            # Many books are "encrypted" with an empty user password.
            try:
                self._reader.decrypt("")
            except Exception as exc:  # pragma: no cover - depends on the file
                raise DocumentError(
                    "This PDF is password protected; the reader cannot open it."
                ) from exc
        self.page_count = len(self._reader.pages)

    def raw_page_text(self, index: int) -> str:
        if not 0 <= index < self.page_count:
            return ""
        try:
            return self._reader.pages[index].extract_text() or ""
        except Exception:
            return ""

    def toc(self) -> list[TocEntry]:
        try:
            outline = self._reader.outline
        except Exception:
            return []
        entries: list[TocEntry] = []

        def walk(items: list, level: int) -> None:
            for item in items:
                if isinstance(item, list):
                    walk(item, level + 1)
                    continue
                title = getattr(item, "title", None)
                if not title:
                    continue
                try:
                    page = self._reader.get_destination_page_number(item)
                except Exception:
                    page = 0
                entries.append(TocEntry(level, str(title).strip(), max(0, int(page))))

        try:
            walk(list(outline), 1)
        except Exception:
            return entries
        return entries

    def metadata(self) -> dict[str, str]:
        try:
            meta = self._reader.metadata or {}
        except Exception:
            return {}
        return {
            "title": str(meta.get("/Title") or "").strip(),
            "author": str(meta.get("/Author") or "").strip(),
        }


class PdftotextBackend(PdfBackend):
    """poppler's ``pdftotext`` command line tool.

    Used as a last resort so that the reader works even when no Python PDF
    library could be installed.  The whole book is extracted in one call and
    split on the form-feed characters poppler inserts between pages.
    """

    name = "pdftotext"
    requirement = "poppler (pdftotext)"

    @classmethod
    def available(cls) -> bool:
        return shutil.which("pdftotext") is not None

    def __init__(self, path: str | os.PathLike[str]) -> None:
        super().__init__(path)
        self._pages: list[str] | None = None
        self.page_count = self._pdfinfo_pages() or 0

    def _pdfinfo_pages(self) -> int:
        if shutil.which("pdfinfo") is None:
            return 0
        try:
            out = subprocess.run(
                ["pdfinfo", self.path],
                capture_output=True, text=True, errors="replace", timeout=30,
                check=False,
            ).stdout
        except Exception:
            return 0
        match = re.search(r"^Pages:\s*(\d+)", out, re.MULTILINE)
        return int(match.group(1)) if match else 0

    def _extract_all(self) -> list[str]:
        if self._pages is not None:
            return self._pages
        try:
            proc = subprocess.run(
                ["pdftotext", "-enc", "UTF-8", "--", self.path, "-"],
                capture_output=True, errors="replace", timeout=600, check=False,
            )
        except Exception as exc:
            raise DocumentError(f"pdftotext failed: {exc}") from exc
        if proc.returncode != 0:
            raise DocumentError(
                "pdftotext failed: "
                + (proc.stderr or b"").decode("utf-8", "replace").strip()
            )
        text = proc.stdout.decode("utf-8", "replace") if isinstance(proc.stdout, bytes) else proc.stdout
        # poppler separates pages with a form feed, which gives us pagination
        # for free.  (--nopgbrk would remove them, so it is not used.)
        pages = text.split("\f") if "\f" in text else [text]
        if pages and not pages[-1].strip():
            pages.pop()
        self._pages = pages
        if not self.page_count:
            self.page_count = len(pages)
        return self._pages

    def raw_page_text(self, index: int) -> str:
        pages = self._extract_all()
        if 0 <= index < len(pages):
            return pages[index]
        return ""

    def metadata(self) -> dict[str, str]:
        if shutil.which("pdfinfo") is None:
            return {}
        try:
            out = subprocess.run(
                ["pdfinfo", self.path],
                capture_output=True, text=True, errors="replace", timeout=30,
                check=False,
            ).stdout
        except Exception:
            return {}
        meta: dict[str, str] = {}
        for key, field in (("Title", "title"), ("Author", "author")):
            match = re.search(rf"^{key}:\s*(.*)$", out, re.MULTILINE)
            if match:
                meta[field] = match.group(1).strip()
        return meta


#: Backends in order of preference.
_BACKENDS: tuple[type[PdfBackend], ...] = (
    PyMuPdfBackend,
    PypdfBackend,
    PdftotextBackend,
)


def backend_names() -> list[str]:
    """Names of every known backend, installed or not."""
    return [cls.name for cls in _BACKENDS]


def available_backends() -> list[str]:
    """Names of the backends whose dependency is actually present."""
    return [cls.name for cls in _BACKENDS if cls.available()]


def _backend_by_name(name: str) -> type[PdfBackend] | None:
    wanted = str(name).strip().lower()
    for cls in _BACKENDS:
        if cls.name.lower() == wanted:
            return cls
    return None


# --------------------------------------------------------------------------- #
# Document
# --------------------------------------------------------------------------- #

#: How many extracted pages are kept in memory per document.
_CACHE_LIMIT = 48


class Document:
    """An opened PDF: lazy page text, caching, re-flowing, outline, metadata.

    Pages are extracted on first access only, so opening a 900 page book is
    instantaneous even though re-flowing later pages is deferred.
    """

    def __init__(
        self,
        path: str | os.PathLike[str],
        backend: PdfBackend,
        *,
        smart_paragraphs: bool = True,
    ) -> None:
        self.path = os.fspath(path)
        self._backend = backend
        self._smart_paragraphs = smart_paragraphs
        self._raw_cache: dict[int, str] = {}
        self._text_cache: dict[int, str] = {}
        self._layout_cache: dict[int, PageLayout | None] = {}
        self._layout_text_cache: dict[int, str] = {}
        self._math_cache: dict[tuple, bytes | None] = {}
        self._body_pt: float | None = None
        self._has_layout: bool | None = None
        self._toc: list[TocEntry] | None = None
        self._metadata: dict[str, str] | None = None
        self._scanned: bool | None = None

    # -- identity ---------------------------------------------------------- #
    @property
    def name(self) -> str:
        """File name without directory."""
        return os.path.basename(self.path)

    @property
    def display_title(self) -> str:
        """Book title from the PDF metadata, or the file name."""
        title = self.metadata.get("title") or ""
        return title or os.path.splitext(self.name)[0]

    @property
    def backend_name(self) -> str:
        return self._backend.name

    @property
    def page_count(self) -> int:
        return self._backend.page_count

    # -- text -------------------------------------------------------------- #
    def raw_text(self, index: int) -> str:
        """Text of page *index* exactly as extracted (line breaks preserved)."""
        if not 0 <= index < self.page_count:
            return ""
        if index not in self._raw_cache:
            try:
                text = self._backend.raw_page_text(index)
            except Exception:
                text = ""
            self._raw_cache[index] = text
            self._trim(self._raw_cache)
        return self._raw_cache[index]

    def page_text(self, index: int) -> str:
        """Re-flowed text of page *index*, ready for bionic rendering."""
        if index not in self._text_cache:
            self._text_cache[index] = reflow(
                self.raw_text(index), smart_paragraphs=self._smart_paragraphs
            )
            self._trim(self._text_cache)
        return self._text_cache[index]

    def words_on_page(self, index: int) -> int:
        return word_count(self.page_text(index))

    # -- page layout ------------------------------------------------------- #
    @property
    def has_layout(self) -> bool:
        """True when the backend can report where text sits on the page.

        Sampling a few pages is enough: a backend either reports geometry or it
        does not, and this keeps the check cheap for large books.
        """
        if self._has_layout is None:
            self._has_layout = False
            for index in self._sample_pages(limit=3):
                page = self._backend.page_layout(index)
                if page is not None and not page.is_empty:
                    self._has_layout = True
                    break
        return self._has_layout

    def page_layout(self, index: int) -> PageLayout | None:
        """Geometry of page *index*, or ``None`` when unavailable or empty."""
        if index not in self._layout_cache:
            page: PageLayout | None = None
            if 0 <= index < self.page_count:
                try:
                    page = self._backend.page_layout(index)
                except Exception:
                    page = None
            self._layout_cache[index] = page
            self._trim(self._layout_cache)
        return self._layout_cache[index]

    def math_image(self, index: int, rect: tuple[float, float, float, float],
                   zoom: float, ink: str, paper: str,
                   pad_top: float = 0.0, pad_bottom: float = 0.0) -> bytes | None:
        """A formula crop of page *index* in the theme's colours (cached)."""
        render = getattr(self._backend, "render_clip", None)
        if render is None:
            return None
        key = (index, tuple(round(v, 1) for v in rect), round(zoom, 2), ink, paper,
               round(pad_top, 1), round(pad_bottom, 1))
        if key not in self._math_cache:
            self._math_cache[key] = render(
                index, rect, zoom, int(ink.lstrip("#"), 16), int(paper.lstrip("#"), 16),
                pad_top, pad_bottom,
            )
            while len(self._math_cache) > 600:
                self._math_cache.pop(next(iter(self._math_cache)))
        return self._math_cache[key]

    def layout_text(self, index: int) -> str:
        """Page text in true reading order, from the page geometry."""
        if index not in self._layout_text_cache:
            page = self.page_layout(index)
            text = layout_plain_text(page) if page is not None else self.raw_text(index)
            self._layout_text_cache[index] = text
            self._trim(self._layout_text_cache)
        return self._layout_text_cache[index]

    def _sample_pages(self, limit: int = 8) -> list[int]:
        """Up to *limit* page indices with text, skipping front matter.

        Books open with cover and title pages that use display type; starting
        a little way in finds real body text, which is what the scale of the
        whole document is derived from.
        """
        if self.page_count <= 0:
            return []
        start = 1 if self.page_count > 3 else 0
        stop = max(start + 1, min(self.page_count, start + max(limit * 3, 24)))
        found: list[int] = []
        for index in range(start, stop):
            if self.words_on_page(index) >= 20:
                found.append(index)
                if len(found) >= limit:
                    break
        if not found:
            found = [self.page_count // 2 if self.page_count > 1 else 0]
        return found

    @property
    def body_pt(self) -> float:
        """The book's dominant body-text size, used as the scaling reference.

        One size for the whole book (the median of a few sampled pages) keeps
        every page at a consistent scale: otherwise a chapter-opening page with
        a 28 pt headline would shrink its own paragraphs to nothing.
        """
        if self._body_pt is None:
            sizes: list[float] = []
            for index in self._sample_pages():
                page = self.page_layout(index)
                if page is not None and page.spans:
                    sizes.append(body_size(page.spans))
            sizes = [size for size in sizes if size > 0]
            if not sizes:
                self._body_pt = 11.0
            else:
                sizes.sort()
                self._body_pt = sizes[len(sizes) // 2]
        return self._body_pt

    @property
    def smart_paragraphs(self) -> bool:
        return self._smart_paragraphs

    def set_smart_paragraphs(self, enabled: bool) -> None:
        """Toggle indentation-based paragraph detection and drop the cache."""
        enabled = bool(enabled)
        if enabled != self._smart_paragraphs:
            self._smart_paragraphs = enabled
            self._text_cache.clear()

    @staticmethod
    def _trim(cache: dict) -> None:
        while len(cache) > _CACHE_LIMIT:
            cache.pop(next(iter(cache)))

    # -- outline / metadata ------------------------------------------------ #
    @property
    def toc(self) -> list[TocEntry]:
        """Document outline (chapter list); empty when the PDF has none."""
        if self._toc is None:
            try:
                self._toc = list(self._backend.toc())
            except Exception:
                self._toc = []
        return self._toc

    @property
    def metadata(self) -> dict[str, str]:
        if self._metadata is None:
            try:
                self._metadata = dict(self._backend.metadata())
            except Exception:
                self._metadata = {}
            self._metadata.setdefault("title", "")
            self._metadata.setdefault("author", "")
            self._metadata["pages"] = str(self.page_count)
        return self._metadata

    @property
    def looks_scanned(self) -> bool:
        """True when the PDF has no text layer at all (image-only scan).

        Sampling the first few pages is enough and keeps this cheap.
        """
        if self._scanned is None:
            sample = min(self.page_count, 6)
            self._scanned = sample > 0 and all(
                self.words_on_page(i) == 0 for i in range(sample)
            )
        return self._scanned

    # -- lifecycle --------------------------------------------------------- #
    def close(self) -> None:
        self._backend.close()

    def __enter__(self) -> "Document":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def open_document(
    path: str | os.PathLike[str],
    *,
    backend: str | None = None,
    smart_paragraphs: bool = True,
) -> Document:
    """Open *path* using the best available backend.

    *backend* forces a backend by name (``PyMuPDF`` / ``pypdf`` / ``pdftotext``);
    the ``SACCADE_BACKEND`` environment variable does the same.  Otherwise the
    first backend that is installed *and* can open the file wins.
    """
    path = os.fspath(path)
    if not os.path.exists(path):
        raise DocumentError(f"No such file: {path}")
    if os.path.isdir(path):
        raise DocumentError(f"Not a file: {path}")

    requested = (backend or os.environ.get("SACCADE_BACKEND") or "").strip()
    if requested:
        forced = _backend_by_name(requested)
        if forced is None:
            raise DocumentError(
                f"Unknown backend {requested!r}; choose one of: {', '.join(backend_names())}"
            )
        candidates: list[type[PdfBackend]] = [forced]
    else:
        candidates = list(_BACKENDS)

    errors: list[str] = []
    for cls in candidates:
        if not cls.available():
            errors.append(f"{cls.name}: not installed (needs {cls.requirement})")
            continue
        try:
            return Document(path, cls(path), smart_paragraphs=smart_paragraphs)
        except Exception as exc:  # fall through to the next backend
            errors.append(f"{cls.name}: {exc}")

    if not available_backends():
        raise BackendUnavailable(
            "No PDF text backend is available. Install at least one of:\n"
            "  - PyMuPDF (best):  pip install pymupdf\n"
            "  - pypdf:           pip install pypdf\n"
            "  - poppler:         sudo pacman -S poppler   (provides pdftotext)"
        )
    detail = "\n".join(f"  - {line}" for line in errors)
    raise DocumentError(f"Could not read {os.path.basename(path)}:\n{detail}")