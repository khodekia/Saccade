"""Faithful page-layout reconstruction for PDF pages.

Re-flowing a page into a single column of paragraphs loses the *structure* of
the page: display type shrinks to body size, colour is dropped, blocks that sit
side by side (a table of contents and its page numbers, two newspaper columns)
are merged into one blob, and artwork disappears entirely.

This module rebuilds a page roughly the way it was typeset.  It imports neither
Qt nor PyMuPDF, so it stays unit-testable head-less and reusable by the CLI:
the caller hands it a :class:`PageLayout` -- text spans and images with their
geometries, in PDF points -- and gets an HTML fragment back.

The reconstruction has four steps:

1. spans are grouped into *lines*: spans that share a vertical band;
2. lines are split into *segments* at horizontal gaps greater than a threshold,
   which is what separates a table-of-contents entry from its page number;
3. segments are grouped into *bands*: cells that sit next to each other on the
   same baseline.  This is how two-column layouts and right-aligned folios
   survive the conversion;
4. every band becomes either one paragraph or one single-row table, preceded by
   a spacer that reproduces the original vertical gap.

Qt's rich-text engine has no absolute positioning, so percentages of the page
width and ``<table>`` cells are the layout primitives; for the same reason the
fonts are scaled relative to the book's dominant body size instead of being
pinned to the PDF's own point sizes.
"""

from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import dataclass, replace
from functools import partial

from . import bionic

__all__ = [
    "BIONIC_MAX_SCALE",
    "ImageBox",
    "PageLayout",
    "Span",
    "body_size",
    "flow_html",
    "natural_width",
    "plain_text",
    "to_html",
]

#: Fixations are only added to text up to this multiple of the body size.
#: Display type is already visually distinct, and bolding it looks broken.
BIONIC_MAX_SCALE = 1.8

#: A new segment starts after a gap of this many ems ...
_SEGMENT_GAP_EM = 0.9
#: ... or this fraction of the page width, whichever is larger.
_SEGMENT_GAP_PAGE = 0.02
#: Spans separated by less than this many ems are joined without a space.
_JOIN_GAP_EM = 0.18
#: Spans overlapping vertically by more than this ratio share a line/band.
_OVERLAP_RATIO = 0.5
#: PDF points -> CSS pixels.
_PX_PER_PT = 96.0 / 72.0
#: The page is scaled down a little so it fits an ordinary window.
_FIT = 0.92
#: Margins count as "balanced" within this fraction of the page width.
_CENTRED_TOLERANCE = 0.045
#: A single line is only centred when it is narrower than this.
_CENTRED_MAX_WIDTH = 0.78
#: Text this much larger than the body size counts as display type.
_DISPLAY_SCALE = 1.15
#: Vertical gaps are clamped to this many lines of body text.
_MAX_GAP_LINES = 4.0
#: Horizontal offsets of single-cell bands are clamped to this fraction.
_MAX_OFFSET = 0.25


@dataclass(frozen=True)
class Span:
    """One run of characters sharing a font, a size and a colour.

    Coordinates are PDF points with the origin in the top-left corner of the
    page, which is what every backend reports.
    """

    text: str
    size: float
    font: str = ""
    bold: bool = False
    italic: bool = False
    color: int = 0
    x0: float = 0.0
    y0: float = 0.0
    x1: float = 0.0
    y1: float = 0.0
    #: Baseline y, when the backend reports it (used to spot sub/superscripts).
    origin_y: float | None = None
    #: The backend's own block/line indices, in its reading order; -1 if unknown.
    block: int = -1
    line: int = -1
    #: 0-based page an internal PDF link on this span jumps to.
    link_page: int | None = None
    #: Measured ink extent of a big math glyph, whose nominal box is too short.
    ink_y0: float | None = None
    ink_y1: float | None = None

    @property
    def top(self) -> float:
        return self.y0 if self.ink_y0 is None else self.ink_y0

    @property
    def bottom(self) -> float:
        return self.y1 if self.ink_y1 is None else self.ink_y1

    @property
    def width(self) -> float:
        return max(0.0, self.x1 - self.x0)

    @property
    def height(self) -> float:
        return max(0.0, self.y1 - self.y0)

    @property
    def y_centre(self) -> float:
        return (self.y0 + self.y1) / 2.0


@dataclass(frozen=True)
class ImageBox:
    """An image placed on the page, with its already-encoded bytes."""

    data: bytes
    mime: str = "image/png"
    x0: float = 0.0
    y0: float = 0.0
    x1: float = 0.0
    y1: float = 0.0
    pixel_width: int = 0
    pixel_height: int = 0

    @property
    def width(self) -> float:
        return max(0.0, self.x1 - self.x0)

    @property
    def height(self) -> float:
        return max(0.0, self.y1 - self.y0)


@dataclass(frozen=True)
class PageLayout:
    """Everything drawn on one page: text spans plus placed images."""

    width: float
    height: float
    spans: tuple[Span, ...] = ()
    images: tuple[ImageBox, ...] = ()
    #: Thin horizontal lines drawn on the page, as ``(x0, y0, x1, y1)``.
    #: Fraction bars are drawings, not text, and a formula that loses its bar
    #: changes meaning, so they are collected and folded into the crop.
    rules: tuple[tuple[float, float, float, float], ...] = ()
    #: True when the page is a scan: one big image with a text layer over it.
    is_scan: bool = False

    @property
    def is_empty(self) -> bool:
        return not self.spans and not self.images


# --------------------------------------------------------------------------- #
# Measuring
# --------------------------------------------------------------------------- #

def body_size(spans, default: float = 11.0) -> float:
    """Dominant text size of *spans*, weighted by how many characters use it.

    The most-used size (not the average) is the body size: a page with a huge
    title still reads as a body-text page, because its paragraphs contain far
    more characters than its headline.
    """
    weights: dict[float, int] = {}
    for span in spans:
        text = (span.text or "").strip()
        if not text or span.size <= 0:
            continue
        key = round(float(span.size), 1)
        weights[key] = weights.get(key, 0) + len(text)
    if not weights:
        return default
    # Heaviest total wins; ties go to the smaller size, because a page whose
    # body text and footnotes share a size reads mostly at the smaller one.
    return min(weights.items(), key=lambda item: (-item[1], item[0]))[0]


def _metrics(page: PageLayout, base_pt: float, body_pt: float | None):
    """Return ``(body_pt, scale, px_per_pt)`` for a page and a target size."""
    body = body_pt if body_pt and body_pt > 0 else (body_size(page.spans) or 11.0)
    scale = max(0.35, min(3.0, float(base_pt) / body))
    return body, scale, scale * _PX_PER_PT * _FIT


def natural_width(
    page: PageLayout,
    *,
    base_pt: float = 13.0,
    body_pt: float | None = None,
    minimum: int = 360,
    maximum: int = 1100,
) -> int:
    """Width in pixels at which *page* renders at true scale (used to centre)."""
    if page.width <= 0:
        return minimum
    _, _, px_per_pt = _metrics(page, base_pt, body_pt)
    return int(max(minimum, min(maximum, page.width * px_per_pt)))


# --------------------------------------------------------------------------- #
# Grouping: spans -> lines -> segments -> bands
# --------------------------------------------------------------------------- #

def _overlap_ratio(a0: float, a1: float, b0: float, b1: float) -> float:
    """Vertical overlap of two ranges, relative to the shorter one."""
    shorter = min(a1 - a0, b1 - b0)
    if shorter <= 0:
        return 0.0
    return max(0.0, min(a1, b1) - max(a0, b0)) / shorter


class _Box:
    """Mutable bounding box shared by the grouping helpers."""

    __slots__ = ("x0", "y0", "x1", "y1")

    def __init__(self, x0: float, y0: float, x1: float, y1: float) -> None:
        self.x0, self.y0, self.x1, self.y1 = x0, y0, x1, y1

    def extend(self, other: "_Box") -> None:
        self.x0 = min(self.x0, other.x0)
        self.y0 = min(self.y0, other.y0)
        self.x1 = max(self.x1, other.x1)
        self.y1 = max(self.y1, other.y1)

    def accepts(self, other: "_Box", ratio: float = _OVERLAP_RATIO) -> bool:
        """True when *other* sits vertically in line with this box."""
        return _overlap_ratio(self.y0, self.y1, other.y0, other.y1) > ratio


class _Line(_Box):
    """Spans that share a baseline band."""

    __slots__ = ("spans",)

    def __init__(self, span: Span) -> None:
        super().__init__(span.x0, span.y0, span.x1, span.y1)
        self.spans: list[Span] = [span]

    def add(self, span: Span) -> None:
        self.spans.append(span)
        self.extend(_Box(span.x0, span.y0, span.x1, span.y1))


@dataclass(frozen=True)
class _Segment:
    """A run of text that must not be split: one cell of a page band."""

    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    size: float
    bold: bool
    italic: bool
    color: int
    font: str
    link_page: int | None = None

    @property
    def width(self) -> float:
        return max(0.0, self.x1 - self.x0)

    @property
    def y_centre(self) -> float:
        return (self.y0 + self.y1) / 2.0


class _Band(_Box):
    """Segments that sit next to each other on the same baseline band."""

    __slots__ = ("segments",)

    def __init__(self, segment: _Segment) -> None:
        super().__init__(segment.x0, segment.y0, segment.x1, segment.y1)
        self.segments: list[_Segment] = [segment]

    def add(self, segment: _Segment) -> None:
        self.segments.append(segment)
        self.extend(_Box(segment.x0, segment.y0, segment.x1, segment.y1))


def _lines(spans) -> list[_Line]:
    """Group spans into lines, tolerating slightly misaligned baselines."""
    lines: list[_Line] = []
    for span in sorted(spans, key=lambda s: (s.y_centre, s.x0)):
        box = _Box(span.x0, span.y0, span.x1, span.y1)
        for line in lines:
            if line.accepts(box):
                line.add(span)
                break
        else:
            lines.append(_Line(span))
    return lines


def _join(spans: list[Span]) -> str:
    """Join the spans of one line, restoring the spaces between them."""
    out = ""
    previous: Span | None = None
    for span in spans:
        text = span.text or ""
        if not text:
            continue
        if previous is not None and out and not out.endswith(" ") and not text.startswith(" "):
            if span.x0 - previous.x1 > _JOIN_GAP_EM * max(span.size, previous.size):
                out += " "
        out += text
        previous = span
    return out


def _segment(line: _Line, page_width: float) -> list[_Segment]:
    """Split a line into segments at the horizontal gaps between its spans.

    A wide gap is a layout feature, not a word space: it is what separates a
    table-of-contents entry from its page number, or one newspaper column from
    the next.
    """
    spans = sorted(line.spans, key=lambda s: s.x0)
    groups: list[list[Span]] = [[spans[0]]]
    for span in spans[1:]:
        previous = groups[-1][-1]
        limit = max(
            _SEGMENT_GAP_EM * max(span.size, previous.size),
            _SEGMENT_GAP_PAGE * max(page_width, 1.0),
        )
        if span.x0 - previous.x1 > limit:
            groups.append([span])
        else:
            groups[-1].append(span)

    segments: list[_Segment] = []
    for group in groups:
        text = _join(group).strip()
        if not text:
            continue
        biggest = max(group, key=lambda s: s.size)
        links = {s.link_page for s in group if s.link_page is not None}
        segments.append(_Segment(
            text=text,
            x0=min(s.x0 for s in group),
            y0=min(s.y0 for s in group),
            x1=max(s.x1 for s in group),
            y1=max(s.y1 for s in group),
            size=biggest.size,
            bold=any(s.bold for s in group),
            italic=any(s.italic for s in group),
            color=biggest.color,
            font=biggest.font,
            link_page=links.pop() if len(links) == 1 else None,
        ))
    return segments


def _bands(segments) -> list[_Band]:
    """Group segments into horizontal bands, ordered top to bottom."""
    bands: list[_Band] = []
    for segment in sorted(segments, key=lambda s: (s.y_centre, s.x0)):
        box = _Box(segment.x0, segment.y0, segment.x1, segment.y1)
        for band in bands:
            if band.accepts(box):
                band.add(segment)
                break
        else:
            bands.append(_Band(segment))
    for band in bands:
        band.segments.sort(key=lambda s: s.x0)
    return sorted(bands, key=lambda band: band.y0)


#: An annotation segment must be set meaningfully smaller than the segment it
#: sits under -- body text lines share one size, so this is what tells a
#: limit apart from an ordinary next line that happens to align with the one
#: above.
_ANNOTATION_MAX_SIZE_RATIO = 0.85


def _page_bands(page: PageLayout) -> list[_Band]:
    """Every text band of a page, in reading order."""
    segments: list[_Segment] = []
    for line in _lines([s for s in page.spans if s.text.strip()]):
        segments.extend(_segment(line, page.width))
    bands = _bands(segments)
    return _fold_stacked_limits(bands)


def _fold_stacked_limits(bands: list[_Band]) -> list[_Band]:
    """Fold operator limits (``\\bigcup_{A in J}``, and the like) back into
    the segment they are stacked under, instead of leaving them as their own
    page-wide row.

    A band is otherwise read as a full row spanning the page, so a limit
    sitting just below a big operator becomes a new row of its own; reading
    several such formulas side by side back out top-to-bottom then dumps
    every formula's limit into one garbled row after all of the formulas,
    rather than keeping each limit with its own operator.
    """
    folded: list[_Band] = []
    for band in bands:
        if folded and _fold_into(folded[-1], band):
            continue
        folded.append(band)
    return folded


def _fold_into(target: _Band, candidate: _Band) -> bool:
    """Try to fold *candidate* into *target* in place; ``True`` on success."""
    gap = candidate.y0 - target.y1
    matches: list[tuple[int, _Segment]] = []
    for seg in candidate.segments:
        found = _nesting_host(target, seg)
        if found is None:
            return False
        index, host = found
        if seg.size >= _ANNOTATION_MAX_SIZE_RATIO * host.size:
            return False
        if seg.width > host.width:
            return False
        if gap > 0.5 * host.size:
            return False
        matches.append((index, seg))

    # Segments landing on the same host combine left to right, so e.g. "A"
    # and "∈ J" (split by a segment gap of their own) read as one limit.
    by_host: dict[int, list[_Segment]] = {}
    for index, seg in matches:
        by_host.setdefault(index, []).append(seg)
    for index, pieces in by_host.items():
        pieces.sort(key=lambda s: s.x0)
        host = target.segments[index]
        target.segments[index] = _Segment(
            text=host.text + " " + " ".join(piece.text for piece in pieces),
            x0=host.x0, y0=host.y0,
            x1=max(host.x1, max(p.x1 for p in pieces)),
            y1=max(host.y1, max(p.y1 for p in pieces)),
            size=host.size, bold=host.bold, italic=host.italic,
            color=host.color, font=host.font, link_page=host.link_page,
        )
    target.extend(_Box(candidate.x0, candidate.y0, candidate.x1, candidate.y1))
    return True


def _nesting_host(band: _Band, segment: _Segment) -> tuple[int, _Segment] | None:
    """The segment of *band* that *segment* sits (roughly) below, if any."""
    centre = segment.x0 + segment.width / 2.0
    for index, host in enumerate(band.segments):
        pad = max(2.0, 0.15 * host.width)
        if host.x0 - pad <= centre <= host.x1 + pad:
            return index, host
    return None


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #

def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


@dataclass(frozen=True)
class _Context:
    """Everything the renderers need to know about the page being built."""

    page: PageLayout
    body: float
    scale: float
    px_per_pt: float
    base_pt: float
    ink: str
    dark: bool
    bionic_enabled: bool
    intensity: float
    max_image_px: int


def _colour(segment: _Segment, ctx: _Context) -> str:
    """The segment's own colour, unless the theme would make it unreadable."""
    value = segment.color & 0xFFFFFF
    red, green, blue = (value >> 16) & 255, (value >> 8) & 255, value & 255
    luminance = 0.299 * red + 0.587 * green + 0.114 * blue
    if (ctx.dark and luminance < 96) or (not ctx.dark and luminance > 200):
        return ctx.ink
    return f"#{value:06x}"


def _size_pt(segment: _Segment, ctx: _Context) -> float:
    """The segment's size, rescaled so body text matches the user's setting."""
    size = segment.size * ctx.scale
    return max(5.0, min(size, ctx.base_pt * 3.0))


def _cell(segment: _Segment, ctx: _Context) -> tuple[str, str]:
    """Return ``(inline CSS, HTML)`` for one segment."""
    style = f"font-size:{_size_pt(segment, ctx):.1f}pt; color:{_colour(segment, ctx)};"
    # Text the book already sets in bold gets no fixations: there is no
    # regular/bold contrast left to exploit, and nested ``<b><b>`` looks broken.
    if (
        ctx.bionic_enabled
        and not segment.bold
        and segment.size <= BIONIC_MAX_SCALE * ctx.body
    ):
        text = bionic.to_html_fragment(segment.text, ctx.intensity, enabled=True)
    else:
        text = _escape(segment.text)
    if segment.italic:
        text = f"<i>{text}</i>"
    if segment.bold:
        text = f"<b>{text}</b>"
    if segment.link_page is not None:
        text = _link(text, segment.link_page)
    return style, text


def _link(inner_html: str, page: int) -> str:
    """Wrap *inner_html* in an internal link the reading view turns into a jump."""
    return f'<a href="page:{int(page)}">{inner_html}</a>'


def _alignment(segment: _Segment, ctx: _Context) -> str:
    """``left``/``right``/``center``, inferred from the segment's own margins."""
    page = ctx.page
    if page.width <= 0:
        return "left"
    left = segment.x0 / page.width
    right = (page.width - segment.x1) / page.width
    if right <= 0.05 and left > 0.05:
        return "right"
    if (
        abs(left - right) <= _CENTRED_TOLERANCE
        and segment.width / page.width <= _CENTRED_MAX_WIDTH
        and segment.size >= _DISPLAY_SCALE * ctx.body
    ):
        return "center"
    return "left"


def _gap_px(gap_pt: float, ctx: _Context) -> float:
    """Vertical whitespace, in pixels, clamped to a sane number of lines."""
    return min(max(0.0, gap_pt) * ctx.px_per_pt, ctx.base_pt * _MAX_GAP_LINES)


def _band_html(band: _Band, gap_pt: float, ctx: _Context) -> str:
    """One band as HTML: a paragraph, or a single-row table when it has cells."""
    gap = _gap_px(gap_pt, ctx)
    page_width = max(ctx.page.width, 1.0)

    if len(band.segments) == 1:
        segment = band.segments[0]
        style, inner = _cell(segment, ctx)
        offset = min(max(0.0, segment.x0) / page_width, _MAX_OFFSET) * 100.0
        return (
            f'<p style="margin-top:{gap:.1f}px; margin-bottom:0; '
            f"margin-left:{offset:.2f}%; text-align:{_alignment(segment, ctx)}; "
            f'{style}">{inner}</p>'
        )

    cells: list[str] = []
    cursor = 0.0
    for segment in band.segments:
        left = min(max(0.0, segment.x0) / page_width, 1.0) * 100.0
        width = max(1.0, min(segment.width / page_width, 1.0) * 100.0)
        style, inner = _cell(segment, ctx)
        if left - cursor > 0.2:
            cells.append(f'<td width="{left - cursor:.2f}%"></td>')
        cells.append(
            f'<td width="{width:.2f}%" align="{_alignment(segment, ctx)}" '
            f'valign="middle"><span style="{style}">{inner}</span></td>'
        )
        cursor = left + width
    if cursor < 99.5:
        cells.append(f'<td width="{max(0.1, 100.0 - cursor):.2f}%"></td>')

    return (
        '<table width="100%" cellspacing="0" cellpadding="0" border="0" '
        f'style="margin-top:{gap:.1f}px; margin-bottom:0">'
        f"<tr>{''.join(cells)}</tr></table>"
    )


def _image_html(image: ImageBox, gap_pt: float, ctx: _Context, align: str) -> str:
    """One placed image, scaled to the page's own scale factor."""
    if not image.data:
        return ""
    natural = image.width * ctx.px_per_pt
    width = max(24.0, min(natural, float(ctx.max_image_px)))
    ratio = image.height / image.width if image.width > 0 else 1.0
    payload = base64.b64encode(image.data).decode("ascii")
    if align == "left":
        holder = f'text-align:left; max-width:{width:.0f}px'
    else:
        holder = "text-align:center"
    return (
        f'<p style="margin-top:{_gap_px(gap_pt, ctx):.1f}px; margin-bottom:0; '
        f'{holder}"><img src="data:{image.mime};base64,{payload}" '
        f'width="{width:.0f}" height="{width * ratio:.0f}" alt="" /></p>'
    )


def _image_align(image: ImageBox, ctx: _Context) -> str:
    """Centre images that sit in the middle of the text column."""
    page = ctx.page
    if page.width <= 0:
        return "center"
    left = image.x0 / page.width
    right = (page.width - image.x1) / page.width
    if abs(left - right) <= _CENTRED_TOLERANCE and image.width / page.width <= 0.9:
        return "center"
    if left <= 0.1:
        return "left"
    if right <= 0.1:
        return "right"
    return "center"


def to_html(
    page: PageLayout,
    *,
    base_pt: float = 13.0,
    body_pt: float | None = None,
    bionic_enabled: bool = True,
    intensity: float = bionic.DEFAULT_INTENSITY,
    ink: str = "#000000",
    dark: bool = False,
    max_image_px: int = 640,
) -> str:
    """Render *page* as structure-preserving HTML.

    *base_pt* is the reading size the user chose; it becomes the body size of
    the page, and everything else keeps its proportion to it.  Pass *body_pt*
    (see :func:`body_size`) to keep one book-wide scale: otherwise a title page
    with only a 48 pt headline would rescale the text of the whole book.
    """
    if page.is_empty:
        return ""
    body, scale, px_per_pt = _metrics(page, base_pt, body_pt)
    ctx = _Context(
        page=page,
        body=body,
        scale=scale,
        px_per_pt=px_per_pt,
        base_pt=float(base_pt),
        ink=ink,
        dark=bool(dark),
        bionic_enabled=bool(bionic_enabled),
        intensity=float(intensity),
        max_image_px=int(max_image_px),
    )

    blocks: list[tuple[float, float, Callable[[float], str]]] = []
    for band in _page_bands(page):
        blocks.append((band.y0, band.y1, partial(_band_html, band, ctx=ctx)))
    for image in page.images:
        align = _image_align(image, ctx)
        blocks.append((image.y0, image.y1, partial(_image_html, image, ctx=ctx, align=align)))
    blocks.sort(key=lambda block: block[0])

    pieces: list[str] = []
    bottom: float | None = None
    for top, low, make in blocks:
        gap = 0.0 if bottom is None else max(0.0, top - bottom)
        html = make(gap)
        if html:
            pieces.append(html)
        bottom = low if bottom is None else max(bottom, low)
    return "\n".join(pieces)


# --------------------------------------------------------------------------- #
# Structured flow: paragraphs in the backend's reading order
# --------------------------------------------------------------------------- #
#
# Geometric reconstruction (to_html) keeps where text sits but can misread the
# order of dense, symbol-heavy lines. Flow keeps the backend's own reading
# order (which is right for those pages) and re-wraps text into the reader's
# column, while still carrying over what makes a page readable: headings at
# their relative size, bold/italic, sub/superscripts and internal links.

#: Lines whose size differs from the paragraph by more than this start anew.
_FLOW_SIZE_TOLERANCE = 0.12
#: A vertical gap of more than this many line-heights starts a new paragraph.
_FLOW_GAP_LINES = 0.6
#: A first-line indent between these many ems starts a new paragraph.
_FLOW_INDENT_EM = (0.8, 5.0)
#: Paragraphs this much larger than body text are headings (no fixations).
_FLOW_HEADING_SCALE = 1.15


@dataclass
class _FlowLine:
    spans: list[Span]
    x0: float
    y0: float
    x1: float
    y1: float
    size: float
    baseline: float | None


@dataclass
class _Paragraph:
    lines: list[_FlowLine]
    size: float
    left: float


def _flow_lines(spans) -> list[_FlowLine]:
    """Spans grouped into lines, in the order the backend reported them."""
    groups: list[list[Span]] = []
    if spans and all(s.line < 0 for s in spans):
        groups = [sorted(line.spans, key=lambda s: s.x0) for line in _lines(spans)]
    else:
        key = None
        for span in spans:
            current = (span.block, span.line)
            if current != key:
                groups.append([])
                key = current
            groups[-1].append(span)

    lines: list[_FlowLine] = []
    for group in groups:
        size = body_size(group, default=max(s.size for s in group))
        main = next((s for s in group if round(s.size, 1) == size), group[0])
        lines.append(_FlowLine(
            spans=group,
            x0=min(s.x0 for s in group), y0=min(s.y0 for s in group),
            x1=max(s.x1 for s in group), y1=max(s.y1 for s in group),
            size=size, baseline=main.origin_y,
        ))
    return lines


def _starts_paragraph(line: _FlowLine, previous: _FlowLine, para: _Paragraph) -> bool:
    gap = line.y0 - previous.y1
    if gap > _FLOW_GAP_LINES * line.size:
        return True
    if abs(line.size - para.size) > _FLOW_SIZE_TOLERANCE * max(line.size, para.size):
        # A smaller line set flush under the previous one is the limits row of
        # a display formula, not a new (footnote-sized) paragraph.
        tight = gap <= 0.3 * para.size
        return not (line.size < para.size and tight)
    if line.y0 < previous.y1 - 0.3 * line.size:
        return False  # continues the same row (side-by-side pieces of a formula)
    lead = line.spans[0]
    indent = line.x0 - para.left
    low, high = _FLOW_INDENT_EM
    # A line led by a small span is a limit or subscript row, not an indent.
    return lead.size >= 0.85 * line.size and low * line.size < indent < high * line.size


def _paragraphs(lines: list[_FlowLine]) -> list[_Paragraph]:
    paragraphs: list[_Paragraph] = []
    previous: _FlowLine | None = None
    for line in lines:
        if not "".join(s.text for s in line.spans).strip():
            continue
        if previous is None or _starts_paragraph(line, previous, paragraphs[-1]):
            paragraphs.append(_Paragraph([line], line.size, line.x0))
        else:
            para = paragraphs[-1]
            para.lines.append(line)
            para.left = min(para.left, line.x0)
        previous = line
    return paragraphs


def _clean(text: str) -> str:
    """Drop control characters: glyphs a PDF font never mapped to Unicode."""
    return "".join(ch for ch in text if ch >= " " or ch == "\t")


def _span_html(span: Span, line: _FlowLine, para_size: float, fixations: bool,
               intensity: float) -> str:
    text = _clean(span.text)
    if not text:
        return ""
    if fixations and not span.bold:
        inner = bionic.to_html_fragment(text, intensity, enabled=True)
    else:
        inner = _escape(bionic.normalize_text(text))
    if span.italic:
        inner = f"<i>{inner}</i>"
    if span.bold:
        inner = f"<b>{inner}</b>"
    if (
        line.baseline is not None
        and span.origin_y is not None
        and span.size < 0.85 * para_size
        and text.strip()
    ):
        shift = span.origin_y - line.baseline
        if shift < -0.15 * line.size:
            inner = f"<sup>{inner}</sup>"
        elif shift > 0.15 * line.size:
            inner = f"<sub>{inner}</sub>"
    if span.link_page is not None:
        inner = _link(inner, span.link_page)
    return inner


def _paragraph_html(para: _Paragraph, body: float, base_pt: float,
                    bionic_enabled: bool, intensity: float,
                    formulas: "_Formulas | None" = None) -> str:
    ratio = para.size / body if body > 0 else 1.0
    heading = ratio >= _FLOW_HEADING_SCALE
    size_pt = max(base_pt * 0.75, min(base_pt * ratio, base_pt * 2.2))
    fixations = bionic_enabled and not heading

    lines = [list(line.spans) for line in para.lines]
    joins: list[str] = []
    for index in range(1, len(lines)):
        prev_spans, next_spans = lines[index - 1], lines[index]
        last = max((i for i, s in enumerate(prev_spans) if s.text.strip()), default=None)
        prev_text = "".join(s.text for s in prev_spans)
        next_text = "".join(s.text for s in next_spans)
        if (
            last is not None
            and prev_spans[last].text.rstrip().endswith(_HYPHENS)
            and next_text.lstrip()[:1].islower()
        ):
            span = prev_spans[last]
            prev_spans[last] = replace(span, text=span.text.rstrip()[:-1])
            joins.append("")
        elif prev_text.endswith(" ") or next_text.startswith(" "):
            joins.append("")
        else:
            joins.append(" ")

    pieces: list[str] = []
    formula_count, loose_text = 0, 0
    for index, (line, spans) in enumerate(zip(para.lines, lines)):
        if index:
            pieces.append(joins[index - 1])
        for span in spans:
            if formulas is not None and formulas.owns(span):
                image = formulas.html(span)
                formula_count += bool(image)
                pieces.append(image)
                continue
            loose_text += len(span.text.strip())
            pieces.append(_span_html(span, line, para.size, fixations, intensity))
    # Formulas with at most a connective ("and", "for all") between them.
    display = formula_count > 0 and loose_text <= 8
    body_html = "".join(pieces).strip()
    if not body_html:
        return ""
    style = f"font-size:{size_pt:.1f}pt;"
    if heading:
        style += f" margin-top:{base_pt * 0.8:.0f}px;"
    if display:
        style += " text-align:center;"
    return f'<p style="{style}">{body_html}</p>'


_HYPHENS = ("-", "‐", "‑")


# --------------------------------------------------------------------------- #
# Formulas: shown as crops of the typeset page
# --------------------------------------------------------------------------- #
#
# A PDF holds no LaTeX, only glyphs placed at coordinates, so formulas cannot
# be re-typeset (KaTeX and friends need the source). Extracted as text they
# lose their 2-D structure: limits, fractions, big operators, unmapped glyphs.
# Instead every formula is found from its fonts and shown as a crop of the
# page itself, tinted to the reading theme, inline where it occurs.

#: Font families that only ever set mathematics (subset prefix stripped).
_MATH_FONT_PREFIXES = (
    "cmmi", "cmsy", "cmex", "cmbsy", "msam", "msbm", "eufm", "eusm", "euex",
    "rsfs", "blmi", "blsy", "blex", "rblmi", "rblsy", "mtmi", "mtsy", "mtex",
    "txmi", "txsy", "txex", "pxmi", "pxsy", "pxex", "ntxmi", "ntxsy",
    "lmmi", "lmsy", "lmex", "wasy", "esint",
)
#: Characters that join a formula when they sit right next to one.
_MATH_JOINERS = frozenset("()[]{}=+-−<>|/*^_',.:;!0123456789′″")
#: Horizontal gap (in ems) still inside one formula; display operators are
#: followed by a thin space wider than a word space.
_MATH_GAP_EM = 0.7
#: Vertical gap (in ems) between a formula and a small row stacked on it.
_MATH_STACK_EM = 0.45
#: Tallest a formula may be, in lines of body text, before it is not believed.
_MATH_MAX_LINES = 5.0
#: How far above/below a fraction bar its numerator and denominator sit (ems).
_MATH_FRACTION_EM = 1.1
#: Widest a line may be, as a fraction of the page, and still be a fraction bar.
_MATH_RULE_MAX_WIDTH = 0.45
#: How far two baselines may differ (ems) and still count as the same line.
_MATH_BASELINE_EM = 0.55

#: ``(x0, y0, x1, y1), css_px_per_pt, pad_top_pt, pad_bottom_pt ->
#: (image src, width_px, height_px)``. The caller renders at the screen's own
#: pixel density so the view never rescales (rescaling is what blurs formulas).
MathRenderer = Callable[
    [tuple[float, float, float, float], float, float, float],
    "tuple[str, float, float] | None",
]


#: Name fragments that mark a font as ordinary *text*.  Anything else that is
#: not the page's body font is assumed to be mathematics: publishers embed
#: formulas in privately-encoded fonts ("WWDOC01") whose extracted text is
#: wrong ("m = m0" comes out as "m 5 m0"), and those must be shown as crops.
_TEXT_FONT_HINTS = (
    "times", "roman", "italic", "oblique", "bold", "serif", "sans", "arial",
    "helvetica", "calibri", "cambria", "georgia", "verdana", "tahoma", "courier",
    "mono", "liberation", "dejavu", "noto", "charter", "palatino", "utopia",
    "century", "garamond", "caslon", "baskerville", "minion", "myriad", "lato",
    "nimbus", "frutiger", "univers", "futura", "gill", "optima", "book",
    "cmr", "cmti", "cmbx", "cmsl", "cmss", "cmtt", "cmcsc", "lmroman", "lmsans",
    "opendyslexic", "atkinson", "lexend", "andika", "comic",
)
#: An unrecognised font is only read as maths for runs this short; a whole
#: paragraph in an unknown font is just a typeface this list does not name.
_UNKNOWN_FONT_MAX_CHARS = 12


def _is_math_font(font: str) -> bool:
    name = font.rsplit("+", 1)[-1].lower()
    return name.startswith(_MATH_FONT_PREFIXES) or "math" in name or name.startswith("symbol")


def _is_text_font(font: str) -> bool:
    name = font.rsplit("+", 1)[-1].lower()
    return any(hint in name for hint in _TEXT_FONT_HINTS)


def _body_fonts(spans) -> frozenset[str]:
    """Fonts that carry the bulk of a page: its text, whatever they are named."""
    counts: dict[str, int] = {}
    total = 0
    for span in spans:
        length = len(span.text.strip())
        if length:
            counts[span.font] = counts.get(span.font, 0) + length
            total += length
    if not total:
        return frozenset()
    return frozenset(font for font, n in counts.items() if n / total >= 0.12)


def _is_math_char(ch: str) -> bool:
    code = ord(ch)
    if ch in "−∗∙":  # minus/asterisk/bullet also appear in prose
        return False
    return (
        code < 0x20
        or 0x2200 <= code <= 0x22FF
        or 0x27C0 <= code <= 0x27EF
        or 0x2980 <= code <= 0x2AFF
    )


def _math_core(span: Span, body_fonts: frozenset[str] = frozenset()) -> bool:
    text = span.text.strip()
    if not text:
        return False
    if _is_math_font(span.font) or any(_is_math_char(c) for c in text):
        return True
    return (
        span.font not in body_fonts
        and not _is_text_font(span.font)
        and len(text) <= _UNKNOWN_FONT_MAX_CHARS
    )


def _math_joiner(span: Span, body: float) -> bool:
    text = "".join(span.text.split())
    if not text:
        return False
    # A lone character touching a formula is one of its variables: books often
    # set "v" and "c" of a fraction in the body italic, not in a maths font.
    return (
        len(text) == 1
        or all(c in _MATH_JOINERS for c in text)
        or (_small(span, body) and len(text) <= 4)
    )


def _small(span: Span, body: float) -> bool:
    """Set noticeably smaller than body text (a script or a limits row).

    Some math fonts report a nonsense size (4 pt for a full-size brace); when
    the span's own box is body-height, the box is trusted over the size.
    """
    if span.size >= 0.85 * body:
        return False
    return not (span.size < 0.6 * body and span.height >= 1.2 * body)


def _normalised(span: Span, body: float) -> Span:
    """Replace a nonsense size and box (see :func:`_small`) with body-size
    metrics around the span's own baseline."""
    if span.origin_y is None or _small(span, body) or span.size >= 0.6 * body:
        return span
    return replace(
        span, size=body,
        ink_y0=span.origin_y - 0.8 * body, ink_y1=span.origin_y + 0.25 * body,
    )


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    shorter = min(a1 - a0, b1 - b0)
    return max(0.0, min(a1, b1) - max(a0, b0)) / shorter if shorter > 0 else 0.0


def _side_by_side(a: Span, b: Span, body: float = 0.0) -> bool:
    size = max(a.size, b.size)
    if _overlap(a.top, a.bottom, b.top, b.bottom) <= 0.3:
        return False
    if max(a.x0, b.x0) - min(a.x1, b.x1) > _MATH_GAP_EM * size:
        return False
    # Consecutive lines overlap slightly, because a span's box includes the
    # ascender and descender. Without a baseline test, the small fragments of
    # a numbered exercise list chain down a whole column and the crop swallows
    # the prose between the exercises. Scripts sit about half a line off the
    # baseline, so they still pass; the next line does not.
    if body > 0 and a.ink_y0 is None and b.ink_y0 is None:
        if a.origin_y is not None and b.origin_y is not None:
            return abs(a.origin_y - b.origin_y) <= _MATH_BASELINE_EM * body
    return True


def _baseline(span: Span) -> float:
    return span.origin_y if span.origin_y is not None else span.y1 - 0.2 * span.size


def _script_of(small: Span, base: Span) -> bool:
    """*small* is a sub/superscript set right beside *base* on its line."""
    left_gap = small.x0 - base.x1
    right_gap = base.x0 - small.x1
    beside = (-0.5 <= left_gap <= 0.3 * base.size) or (-0.5 <= right_gap <= 0.3 * base.size)
    return beside and abs(_baseline(small) - _baseline(base)) <= 0.8 * base.size


def _stacked(small: Span, other: Span) -> bool:
    """*small* sits directly under or over *other* (limits of an operator)."""
    centre = (small.x0 + small.x1) / 2.0
    vgap = max(small.y0, other.top) - min(small.y1, other.bottom)
    if other.top <= small.y_centre <= other.bottom:
        vgap = 0.0  # a limit tucked inside the glyph's own drawn height
    return (
        other.x0 - 1.0 <= centre <= other.x1 + 1.0
        and 0.0 <= vgap + 0.3 * small.size
        and vgap <= _MATH_STACK_EM * other.size
    )


def _math_regions(spans, body: float, rules=(), page_width: float = 0.0
                  ) -> tuple[dict[int, int], dict[int, list]]:
    """Map span index -> formula id, plus the rules each formula contains."""
    fonts = _body_fonts(spans)
    eligible = [
        i for i, s in enumerate(spans)
        if _math_core(s, fonts) or _math_joiner(s, body)
    ]
    parent = {i: i for i in eligible}

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    # A small span beside full-size text is an inline sub/superscript; only
    # small spans *not* attached that way can be a stacked row of limits.
    # The base may be ordinary text (books that set variables in plain
    # Times-Italic), so every full-size span counts here, not just math ones.
    full_size = [s for s in spans if not _small(s, body) and s.text.strip()]
    inline_script = {
        i for i in eligible
        if _small(spans[i], body)
        and any(
            _side_by_side(spans[i], base, body) or _script_of(spans[i], base)
            for base in full_size
        )
    }
    for pos, a in enumerate(eligible):
        for b in eligible[pos + 1:]:
            sa, sb = spans[a], spans[b]
            linked = _side_by_side(sa, sb, body)
            if not linked:
                for small, big, i in ((sa, sb, a), (sb, sa, b)):
                    if (
                        _small(small, body)
                        and not _small(big, body)
                        and i not in inline_script
                        and _math_core(big, fonts)
                        and _stacked(small, big)
                    ):
                        linked = True
                        break
            if linked:
                parent[find(a)] = find(b)

    # A fraction bar binds what is written above it to what is written below.
    # Pages are full of other thin horizontal lines -- the rule under a running
    # head, table borders, footer separators -- so a line only counts as a
    # fraction bar when it is short and has something on *both* sides of it.
    rule_of: dict[int, list] = {}
    for rule in rules:
        rx0, ry0, rx1, ry1 = rule
        ry = (ry0 + ry1) / 2.0
        if page_width > 0 and (rx1 - rx0) > _MATH_RULE_MAX_WIDTH * page_width:
            continue
        # A fraction bar is drawn as wide as the wider of its two parts, so
        # anything bound to it fits within the bar. A span that sticks far out
        # belongs to the surrounding line, not to this fraction.
        margin = 0.5 * body
        near = [
            i for i in eligible
            if spans[i].x0 >= rx0 - margin and spans[i].x1 <= rx1 + margin
            and abs(spans[i].y_centre - ry) <= _MATH_FRACTION_EM * body
        ]
        # Only the row directly above and the row directly below belong to
        # this bar. Reaching further chains stacked fractions in an exercise
        # list into one crop that then covers the text between them.
        above = _rule_row([i for i in near if spans[i].y_centre < ry], spans, ry, body)
        below = _rule_row([i for i in near if spans[i].y_centre > ry], spans, ry, body)
        bound = above + below
        if not above or not below:
            continue
        root = find(bound[0])
        for i in bound[1:]:
            parent[find(i)] = root
        rule_of.setdefault(find(bound[0]), []).append(rule)

    groups: dict[int, list[int]] = {}
    for i in eligible:
        groups.setdefault(find(i), []).append(i)
    rules_by_root: dict[int, list] = {}
    for root, found in rule_of.items():
        rules_by_root.setdefault(find(root), []).extend(found)
    return {
        i: root
        for root, members in groups.items()
        # A fraction bar with something above and below it is mathematics even
        # when the book sets the whole fraction in its ordinary text font.
        if (any(_math_core(spans[m], fonts) for m in members) or root in rules_by_root)
        and _plausible_formula([spans[m] for m in members], body)
        for i in members
    }, rules_by_root


def _plausible_formula(members: list[Span], body: float) -> bool:
    """Reject a run-away cluster.

    Even a displayed fraction stays a few lines tall. Anything taller means the
    grouping went wrong, and a wrong crop swallows the page: showing the
    extracted text instead is the safer failure."""
    top = min(s.top for s in members)
    bottom = max(s.bottom for s in members)
    return bottom - top <= _MATH_MAX_LINES * body


def _rule_row(candidates: list[int], spans, ry: float, body: float) -> list[int]:
    """The single row of spans closest to a fraction bar, on one side of it."""
    if not candidates:
        return []
    nearest = min(candidates, key=lambda i: abs(spans[i].y_centre - ry))
    row = spans[nearest].y_centre
    return [i for i in candidates if abs(spans[i].y_centre - row) <= 0.5 * body]


def _formula_rect(members: list[Span], body: float, rules=()):
    """Tight crop box plus blank padding (top, bottom) that centres the crop on
    the formula's own text line, so a middle-aligned image sits on the
    surrounding baseline. Padding is blank rather than more of the page, which
    would drag fragments of neighbouring lines into the crop."""
    x0 = min(s.x0 for s in members) - 0.3
    x1 = max(s.x1 for s in members) + 0.3
    y0 = min(s.top for s in members) - 0.5
    y1 = max(s.bottom for s in members) + 0.5
    for rx0, ry0, rx1, ry1 in rules:
        x0, x1 = min(x0, rx0 - 0.3), max(x1, rx1 + 0.3)
        y0, y1 = min(y0, ry0 - 0.5), max(y1, ry1 + 0.5)
    full = [s for s in members if not _small(s, body)] or members
    centres = sorted(s.y_centre for s in full)
    mid = centres[len(centres) // 2]
    above, below = mid - y0, y1 - mid
    half = max(above, below)
    return (x0, y0, x1, y1), half - above, half - below


def flow_html(
    page: PageLayout,
    *,
    base_pt: float = 13.0,
    body_pt: float | None = None,
    bionic_enabled: bool = True,
    intensity: float = bionic.DEFAULT_INTENSITY,
    math_renderer: MathRenderer | None = None,
) -> str:
    """Render *page* as re-flowed paragraphs that keep headings and emphasis.

    With *math_renderer*, formulas are shown as crops of the page instead of
    as extracted text.
    """
    if not page.spans:
        return ""
    body, _scale, _px = _metrics(page, base_pt, body_pt)
    formulas = None
    if math_renderer is not None:
        formulas = _Formulas(page.spans, body, float(base_pt), math_renderer,
                             page.rules, page.width)
    rendered = (
        _paragraph_html(para, body, float(base_pt), bool(bionic_enabled),
                        float(intensity), formulas)
        for para in _paragraphs(_flow_lines(page.spans))
    )
    return "\n".join(html for html in rendered if html)


class _Formulas:
    """Formula crops of one page, emitted once each at their first span."""

    def __init__(self, spans, body: float, base_pt: float, renderer: MathRenderer,
                 page_rules=(), page_width: float = 0.0) -> None:
        index_of = {id(span): i for i, span in enumerate(spans)}
        spans = [_normalised(span, body) for span in spans]
        regions, rules = _math_regions(spans, body, page_rules, page_width)
        members: dict[int, list[Span]] = {}
        for i, root in regions.items():
            members.setdefault(root, []).append(spans[i])
        self._rects = {
            root: _formula_rect(group, body, rules.get(root, ()))
            for root, group in members.items()
        }
        bands = {
            root: (min(s.top for s in group), max(s.bottom for s in group))
            for root, group in members.items()
        }
        # Text inside a formula's own box and text band is already visible in
        # its crop (spaces between runs, words like "and" set in the formula).
        self._owner: dict[int, int] = {}
        for i, span in enumerate(spans):
            root = regions.get(i)
            if root is None and not span.text.strip():
                # Only the spaces between runs are absorbed; words keep their
                # own place in the text, even when a crop overlaps them.
                cx, cy = (span.x0 + span.x1) / 2.0, span.y_centre
                for candidate, ((x0, _y0, x1, _y1), _top, _bottom) in self._rects.items():
                    band_top, band_bottom = bands[candidate]
                    if x0 <= cx <= x1 and band_top <= cy <= band_bottom:
                        root = candidate
                        break
            if root is not None:
                self._owner[i] = root
        self._index_of = index_of
        self._emitted: set[int] = set()
        self._renderer = renderer
        self._px_per_pt = base_pt / body * 96.0 / 72.0 if body > 0 else 96.0 / 72.0

    def owns(self, span: Span) -> bool:
        index = self._index_of.get(id(span))
        return index is not None and index in self._owner

    def html(self, span: Span) -> str:
        """The crop for *span*'s formula the first time it is reached."""
        root = self._owner[self._index_of[id(span)]]
        if root in self._emitted:
            return ""
        self._emitted.add(root)
        rect, pad_top, pad_bottom = self._rects[root]
        result = self._renderer(rect, self._px_per_pt, pad_top, pad_bottom)
        if not result:
            return _escape(span.text)
        src, width, height = result
        return (
            f'<img src="{_escape(src)}" width="{width:.2f}" '
            f'height="{height:.2f}" style="vertical-align: middle" alt="" />'
        )


def plain_text(page: PageLayout) -> str:
    """The page's text in reading order (used for search and word counts)."""
    lines = []
    for band in _page_bands(page):
        cells = [segment.text.strip() for segment in band.segments]
        lines.append(" ".join(cell for cell in cells if cell))
    return "\n".join(lines)

