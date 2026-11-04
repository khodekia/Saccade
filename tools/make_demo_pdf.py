"""Write docs/demo.pdf: a small book-like document to try Saccade on.

The screenshots in the README are taken from this file rather than from a real
textbook, so nothing copyrighted ships with the project. It is built to
exercise the parts that are easy to get wrong: a display fraction whose bar is
a drawn line rather than a character, an integral with limits above and below,
a superscript, headings that must survive re-flowing, and an outline so the
chapter sidebar has something in it.

Run it with:  python tools/make_demo_pdf.py
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SERIF = "/usr/share/fonts/TTF/DejaVuSerif.ttf"
SERIF_ITALIC = "/usr/share/fonts/TTF/DejaVuSerif-Italic.ttf"
SANS = "/usr/share/fonts/TTF/DejaVuSans.ttf"

BODY = 11.0
LEADING = 17.0
LEFT = 72.0
RIGHT = 523.0
TOP = 84.0

PAGES = [
    (
        "1. Reading, and what gets in the way",
        [
            "Reading on a screen asks more of you than reading on paper. The "
            "line you are on looks like every other line, so when your "
            "attention slips there is nothing to slip back to. Bionic reading "
            "gives each word a handle: the first few letters are bolder than "
            "the rest, and your eye lands on them instead of hunting for a "
            "place to start.",
            "None of it is magic, and none of it works for everybody. The "
            "slider in the toolbar decides how much of each word is bolded, "
            "and one key turns the whole thing off so you can judge for "
            "yourself whether it helps.",
            "Focus mode is the other half. It dims every paragraph except the "
            "one you are reading, so a long page stops being a wall and "
            "becomes one line at a time.",
        ],
    ),
    (
        "2. Why formulas break",
        [
            "A PDF does not store an equation. It stores glyphs at "
            "coordinates, and a fraction bar is not a character at all but a "
            "line drawn across the page. Pull the text out and the meaning "
            "goes with it: a quotient turns into a product, and the limits of "
            "an integral end up in the wrong sentence.",
        ],
        "formulas",
    ),
    (
        "3. Scanned books",
        [
            "A scanned book carries a picture of each page and a layer of "
            "text that optical recognition guessed at. The guesses are good "
            "enough for searching and poor enough to ruin mathematics, which "
            "is why a scanned page is shown as the scan itself.",
            "You can still search it, and you can still jump to a chapter. "
            "What you cannot have is the bolding, because there is no real "
            "text to embolden.",
        ],
    ),
]


def wrap(text: str, width: int = 72) -> list[str]:
    words, lines, line = text.split(), [], ""
    for word in words:
        if len(line) + len(word) + 1 > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        lines.append(line)
    return lines


def build(path: str) -> str:
    import pymupdf

    serif = pymupdf.Font(fontfile=SERIF)
    document = pymupdf.open()

    for entry in PAGES:
        title, paragraphs = entry[0], entry[1]
        with_formulas = len(entry) > 2

        page = document.new_page()
        page.insert_font(fontname="body", fontfile=SERIF)
        page.insert_font(fontname="ital", fontfile=SERIF_ITALIC)
        page.insert_font(fontname="head", fontfile=SANS)

        def text(x: float, y: float, value: str, size: float = BODY,
                 font: str = "body") -> None:
            page.insert_text((x, y), value, fontname=font, fontsize=size)

        y = TOP
        text(LEFT, y, title, size=17, font="head")
        y += 34

        for paragraph in paragraphs:
            for line in wrap(paragraph):
                text(LEFT, y, line)
                y += LEADING
            y += 9

        if with_formulas:
            centre = (LEFT + RIGHT) / 2
            y += 8

            def run(x: float, baseline: float, tokens) -> float:
                """Lay out a formula one token at a time.

                Real PDFs emit a separate run whenever the font changes, which
                in a formula is almost every character; writing whole strings
                instead would not exercise the same code.
                """
                for token, font, size, rise in tokens:
                    text(x, baseline - rise, token, size=size, font=font)
                    x += serif.text_length(token, size) + 1.2
                return x

            # A displayed fraction, set the way a typesetter sets one: the bar
            # is a drawn line, and the parts are variables.
            numerator = [("x", "ital", BODY, 0), ("2", "body", 7.0, 5),
                         ("+", "body", BODY, 0), ("1", "body", BODY, 0)]
            denominator = [("x", "ital", BODY, 0), ("−", "body", BODY, 0),
                           ("3", "body", BODY, 0)]
            width_of = lambda toks: sum(
                serif.text_length(t, s) + 1.2 for t, _f, s, _r in toks)
            bar_width = max(width_of(numerator), width_of(denominator)) + 10
            bar_x0 = centre - 30
            run(bar_x0 - 70, y + 4, [("f", "ital", BODY, 0), ("(", "body", BODY, 0),
                                     ("x", "ital", BODY, 0), (")", "body", BODY, 0),
                                     ("=", "body", BODY, 0)])
            run(bar_x0 + (bar_width - width_of(numerator)) / 2, y - 5, numerator)
            page.draw_line(pymupdf.Point(bar_x0, y),
                           pymupdf.Point(bar_x0 + bar_width, y), width=0.6)
            run(bar_x0 + (bar_width - width_of(denominator)) / 2, y + 13, denominator)
            y += 44

            for line in wrap(
                "The bar carries the whole meaning. An integral hides its "
                "limits in the same way, above and below a sign that is one "
                "character tall in the file and three lines tall on the page:"
            ):
                text(LEFT, y, line)
                y += LEADING
            y += 20

            text(centre - 70, y, "∫", size=20, font="head")
            text(centre - 62, y - 14, "n", size=7, font="ital")
            text(centre - 62, y + 9, "0", size=7)
            run(centre - 46, y, [
                ("f", "ital", BODY, 0), ("(", "body", BODY, 0),
                ("t", "ital", BODY, 0), (")", "body", BODY, 0),
                # A thin space in the other face, so the bracket and the
                # differential stay separate runs the way a real book emits
                # them, rather than merging into one ")d".
                (" ", "ital", BODY, 0),
                ("d", "body", BODY, 0), ("t", "ital", BODY, 0),
                ("≈", "head", BODY, 0), ("S", "ital", BODY, 0),
                ("2", "body", 7.0, 5),
            ])
            y += 34

            text(LEFT, y, "for every x ∈ S, which is the point.", size=BODY)
            y += LEADING

    document.set_toc([[1, title, number + 1]
                      for number, (title, *_rest) in enumerate(PAGES)])
    document.set_metadata({"title": "Saccade demo", "author": "Saccade"})
    os.makedirs(os.path.dirname(path), exist_ok=True)
    document.subset_fonts()
    document.save(path, garbage=4, deflate=True)
    document.close()
    return path


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "docs", "demo.pdf")
    print("wrote", build(out))
