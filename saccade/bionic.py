"""Bionic-reading text transformation.

"Bionic Reading" (a technique popularised by Renato Casutt) guides the eye by
bolding the first part of every word -- the *fixation point*.  The artificial
fixation lets the brain fill in the rest of the word, which speeds up word
recognition for many readers.

This module is intentionally free of third-party dependencies and of GUI code
so it can be unit-tested and reused (CLI, HTML export, ...).

The bolding rule follows the widely used "fixation table", which gives the
number of bolded characters as a function of the word length::

    length:  1  2  3  4  5  6  7  8  9 10 11 12 13 14+
    bolded:  1  1  2  2  3  3  4  4  5  5  6  6  7  8

The table corresponds to :data:`DEFAULT_INTENSITY`; any other intensity scales
the table up (longer fixation) or down (lighter fixation).
"""

from __future__ import annotations

import re
import unicodedata

__all__ = [
    "DEFAULT_INTENSITY",
    "MIN_INTENSITY",
    "MAX_INTENSITY",
    "fixation_length",
    "split_word",
    "bold_spans",
    "to_html",
    "to_html_fragment",
    "to_ansi",
    "to_marked",
    "word_count",
]

#: Slider-friendly intensity bounds.
MIN_INTENSITY = 0.2
MAX_INTENSITY = 0.8
DEFAULT_INTENSITY = 0.5

#: Word length -> number of bolded leading characters (classic fixation table).
_FIXATION_TABLE = {
    1: 1, 2: 1, 3: 2, 4: 2, 5: 3, 6: 3, 7: 4,
    8: 4, 9: 5, 10: 5, 11: 6, 12: 6, 13: 7,
}
#: Longest fixation used for words of 14 or more characters.
_FIXATION_MAX_WORD = 8

#: A "word": letters only, optionally joined by apostrophes or hyphens.
#: ``[^\W\d_]`` means "any letter in any alphabet" (``\w`` minus digits/underscore).
_WORD_RE = re.compile(r"[^\W\d_]+(?:['\u2019\-\u2010\u2011][^\W\d_]+)*", re.UNICODE)

#: Characters that join two word fragments ("don't", "well-known").
_JOINERS_RE = re.compile(r"['\u2019\-\u2010\u2011]+")

#: Ligatures and oddities frequently produced by PDF text extraction.
_REPLACEMENTS = {
    "\u00ad": "",      # soft hyphen
    "\u200b": "",      # zero width space
    "\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl",
    "\ufb03": "ffi", "\ufb04": "ffl",
    "\ufb05": "st", "\ufb06": "st",
}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def fixation_length(length: int, intensity: float = DEFAULT_INTENSITY) -> int:
    """Return how many leading characters of a word of *length* get bolded.

    The result is always ``>= 1`` for non-empty words, and always leaves at
    least one unbolded character for words of two or more characters (a fully
    bolded word carries no visual contrast).
    """
    if length <= 0:
        return 0
    if length == 1:
        return 1

    base = _FIXATION_TABLE.get(length, _FIXATION_MAX_WORD)
    intensity = _clamp(float(intensity), MIN_INTENSITY, MAX_INTENSITY)
    scaled = int(round(base * (intensity / DEFAULT_INTENSITY)))
    # Never bold the whole word: the "saccade" (tail) must stay visible.
    return max(1, min(scaled, length - 1))


def split_word(word: str) -> list[str]:
    """Split a word into fragments that each get their own fixation point.

    ``"don't"`` -> ``["don", "'", "t"]``, ``"well-known"`` -> ``["well", "-", "known"]``.
    The joiners are kept so the text can be reassembled losslessly.
    """
    if not word:
        return []
    pieces: list[str] = []
    pos = 0
    for part in _JOINERS_RE.split(word):
        if part:
            pieces.append(part)
            pos += len(part)
        match = _JOINERS_RE.match(word, pos)
        if match:
            pieces.append(match.group(0))
            pos = match.end()
    return pieces or [word]


def bold_spans(word: str, intensity: float = DEFAULT_INTENSITY) -> list[tuple[str, bool]]:
    """Return ``(text, is_bold)`` spans covering *word* completely.

    Only genuine word fragments receive a fixation point, so punctuation,
    apostrophes and hyphens are preserved verbatim.
    """
    spans: list[tuple[str, bool]] = []
    for piece in split_word(word):
        if _JOINERS_RE.fullmatch(piece):
            spans.append((piece, False))
            continue
        cut = fixation_length(len(piece), intensity)
        if cut:
            spans.append((piece[:cut], True))
        if cut < len(piece):
            spans.append((piece[cut:], False))
    return spans


def _fix(text: str) -> str:
    for bad, good in _REPLACEMENTS.items():
        if bad in text:
            text = text.replace(bad, good)
    return text


def normalize_text(text: str) -> str:
    """NFC-normalise *text* and expand PDF ligatures / drop soft hyphens."""
    return _fix(unicodedata.normalize("NFC", text or ""))


def _html_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _spans_to_html(text: str, intensity: float, enabled: bool) -> str:
    """Convert one paragraph of text to escaped HTML with ``<b>`` fixations."""
    out: list[str] = []
    pos = 0
    for match in _WORD_RE.finditer(text):
        out.append(_html_escape(text[pos:match.start()]))
        if enabled:
            for chunk, is_bold in bold_spans(match.group(0), intensity):
                escaped = _html_escape(chunk)
                out.append(f"<b>{escaped}</b>" if is_bold else escaped)
        else:
            out.append(_html_escape(match.group(0)))
        pos = match.end()
    out.append(_html_escape(text[pos:]))
    return "".join(out)


def to_html_fragment(text: str, intensity: float = DEFAULT_INTENSITY, *,
                     enabled: bool = True) -> str:
    """Bionic fixations for a single run of text, with no paragraph tag.

    The layout renderer emits its own blocks (paragraphs and table cells), so it
    needs just the inline markup.  Newlines become ``<br />`` because a single
    run may still span several visual lines.
    """
    text = normalize_text(text)
    if not text:
        return ""
    return "<br />".join(
        _spans_to_html(line, intensity, enabled) for line in text.split("\n")
    )


def to_html(
    text: str,
    intensity: float = DEFAULT_INTENSITY,
    *,
    enabled: bool = True,
    paragraph_tag: str = "p",
) -> str:
    """Render *text* as an HTML fragment with bionic fixations.

    Blank lines separate paragraphs, single newlines become line breaks.  With
    ``enabled=False`` the text is only escaped and tagged, which is what the
    "bionic off" mode of the reader shows.
    """
    text = normalize_text(text)
    if not text.strip():
        return ""

    html: list[str] = []
    for block in re.split(r"\n[ \t]*\n+", text):
        block = block.strip("\n")
        if not block.strip():
            continue
        inner = "<br />".join(
            _spans_to_html(line.strip(), intensity, enabled) for line in block.split("\n")
        )
        html.append(f"<{paragraph_tag}>{inner}</{paragraph_tag}>")
    return "\n".join(html)


def to_ansi(text: str, intensity: float = DEFAULT_INTENSITY, *, enabled: bool = True) -> str:
    """Bionic text for a terminal (ANSI bold); used by the CLI."""
    return _mark(text, intensity, "\033[1m", "\033[0m", enabled)


def to_marked(
    text: str,
    intensity: float = DEFAULT_INTENSITY,
    *,
    open_marker: str = "[",
    close_marker: str = "]",
    enabled: bool = True,
) -> str:
    """Debug/bionic-marked plain text, e.g. ``[Bio]nic reading``."""
    return _mark(text, intensity, open_marker, close_marker, enabled)


def _mark(
    text: str, intensity: float, open_marker: str, close_marker: str, enabled: bool
) -> str:
    if not enabled:
        return text
    out: list[str] = []
    pos = 0
    for match in _WORD_RE.finditer(text):
        out.append(text[pos:match.start()])
        for chunk, is_bold in bold_spans(match.group(0), intensity):
            out.append(f"{open_marker}{chunk}{close_marker}" if is_bold else chunk)
        pos = match.end()
    out.append(text[pos:])
    return "".join(out)


def word_count(text: str) -> int:
    """Number of real words in *text* (used for reading-time estimates)."""
    return sum(1 for _ in _WORD_RE.finditer(text or ""))
