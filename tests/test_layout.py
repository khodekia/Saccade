"""Tests for the structure-preserving page renderer.

These are the tests that guard the reader's promise: a page of the PDF must
come out looking like the page of the PDF -- same alignment, same columns, same
relative sizes, same colours -- with bionic fixations added on top of the body
text rather than replacing the layout.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from saccade import layout
from saccade.layout import (
    ImageBox,
    PageLayout,
    Span,
    body_size,
    natural_width,
    plain_text,
    to_html,
)

from . import pdf_fixture


def span(text: str, *, size: float = 11.0, x0: float = 50.0, x1: float = 300.0,
         y0: float = 100.0, y1: float = 112.0, **kwargs) -> Span:
    """A span with sensible geometry, so tests only state what they care about."""
    return Span(text=text, size=size, x0=x0, x1=x1, y0=y0, y1=y1, **kwargs)


class SpanTests(unittest.TestCase):
    def test_width_and_height_are_never_negative(self) -> None:
        self.assertEqual(span("x", x0=100, x1=40).width, 0.0)
        self.assertEqual(span("x", y0=100, y1=40).height, 0.0)

    def test_y_centre(self) -> None:
        self.assertAlmostEqual(span("x", y0=100, y1=120).y_centre, 110.0)


class BodySizeTests(unittest.TestCase):
    def test_most_used_size_wins_over_the_largest(self) -> None:
        """A 30 pt headline must not define the body size of an 11 pt page."""
        spans = [span("HEADLINE", size=30)]
        spans += [span("word " * 40, size=11)]
        self.assertAlmostEqual(body_size(spans), 11.0)

    def test_empty_spans_fall_back_to_the_default(self) -> None:
        self.assertAlmostEqual(body_size([]), 11.0)
        self.assertAlmostEqual(body_size([span("   ")]), 11.0)
        self.assertAlmostEqual(body_size([span("x", size=0)]), 11.0)

    def test_ties_go_to_the_smaller_size(self) -> None:
        self.assertAlmostEqual(
            body_size([span("aaaa", size=20), span("bbbb", size=10)]), 10.0
        )


class NaturalWidthTests(unittest.TestCase):
    def test_scales_with_the_page_and_the_chosen_size(self) -> None:
        page = PageLayout(width=612, height=792, spans=(span("hello"),))
        small = natural_width(page, base_pt=10, body_pt=11)
        large = natural_width(page, base_pt=20, body_pt=11)
        self.assertLess(small, large)
        self.assertGreaterEqual(small, 360)  # clamped to a readable minimum
        self.assertLessEqual(large, 1100)    # and to a sensible maximum

    def test_empty_page_returns_the_minimum(self) -> None:
        self.assertEqual(natural_width(PageLayout(width=0, height=0)), 360)


class ReadingOrderTests(unittest.TestCase):
    """A page's text must read like the page, not like a scrambled table.

    Regression coverage for a real bug: a big operator's subscripted limit
    (``\\bigcup_{A in J}``, common in analysis textbooks) sits just below the
    operator, so the band grouper reported it as a brand-new row spanning the
    whole page. Reading two side-by-side formulas back out top-to-bottom then
    dumped both formulas' limits into one row *after* both formulas, instead
    of keeping each limit with its own operator.
    """

    def test_operator_limits_stay_with_their_own_formula(self) -> None:
        spans = [
            # "f(⋃A) = ⋃f(A)." and "f(⋂A) ⊆ ⋂f(A)." side by side.
            span("f(", size=10, x0=50, x1=62, y0=400, y1=412),
            span("⋃", size=13, x0=63, x1=76, y0=396, y1=412),
            span("A) = ", size=10, x0=77, x1=110, y0=400, y1=412),
            span("⋃", size=13, x0=111, x1=124, y0=396, y1=412),
            span("f(A).", size=10, x0=125, x1=165, y0=400, y1=412),
            span("f(", size=10, x0=230, x1=242, y0=400, y1=412),
            span("⋂", size=13, x0=243, x1=256, y0=396, y1=412),
            span("A) ⊆ ", size=10, x0=257, x1=290, y0=400, y1=412),
            span("⋂", size=13, x0=291, x1=304, y0=396, y1=412),
            span("f(A).", size=10, x0=305, x1=345, y0=400, y1=412),
            # the "A∈J" limit, once under each of the four big operators.
            span("A∈J", size=6, x0=61, x1=78, y0=413, y1=421),
            span("A∈J", size=6, x0=109, x1=126, y0=413, y1=421),
            span("A∈J", size=6, x0=241, x1=258, y0=413, y1=421),
            span("A∈J", size=6, x0=289, x1=306, y0=413, y1=421),
        ]
        page = PageLayout(width=430, height=800, spans=tuple(spans))
        text = plain_text(page)

        split = text.index("f(⋂A)")
        first_formula, second_formula = text[:split], text[split:]
        self.assertEqual(first_formula.count("A∈J"), 2)
        self.assertEqual(second_formula.count("A∈J"), 2)

    def test_consecutive_prose_lines_are_not_folded_together(self) -> None:
        """Two ordinary same-size lines set close together must stay two
        lines -- only a meaningfully *smaller*, closely-stacked span (a
        limit) gets folded into the one above it."""
        spans = [
            span("Proof. To prove the statement about unions,",
                 size=10, x0=50, x1=380, y0=700, y1=712),
            span("we first observe that since",
                 size=10, x0=50, x1=200, y0=712.5, y1=724.5),
        ]
        page = PageLayout(width=430, height=800, spans=tuple(spans))
        self.assertEqual(
            plain_text(page),
            "Proof. To prove the statement about unions,\n"
            "we first observe that since",
        )


def flow_span(text: str, *, block: int = 0, line: int = 0, size: float = 10.0,
              x0: float = 50.0, y0: float = 100.0, **kwargs) -> Span:
    """A span as PyMuPDF reports it: with block/line order and a baseline."""
    return Span(text=text, size=size, x0=x0, x1=x0 + 6 * len(text), y0=y0,
                y1=y0 + size * 1.2, origin_y=y0 + size, block=block, line=line,
                **kwargs)


class FlowHtmlTests(unittest.TestCase):
    """Flow mode re-wraps text but must keep a page's structure."""

    def render(self, spans) -> str:
        page = PageLayout(width=430, height=800, spans=tuple(spans))
        return layout.flow_html(page, base_pt=12, body_pt=10, bionic_enabled=False)

    def test_wrapped_lines_join_into_one_paragraph(self) -> None:
        html = self.render([
            flow_span("you have to understand a little bit more", line=0, y0=100),
            flow_span("about their structure.", line=1, y0=112),
        ])
        self.assertEqual(html.count("<p"), 1)
        self.assertIn("bit more about their", html)

    def test_larger_type_becomes_a_separate_heading(self) -> None:
        html = self.render([
            flow_span("Chapter 2", size=20, bold=True, block=0, y0=60),
            flow_span("Body text.", block=1, y0=100),
        ])
        paragraphs = html.split("\n")
        self.assertEqual(len(paragraphs), 2)
        self.assertIn("font-size:24.0pt", paragraphs[0])

    def test_hyphenated_line_break_is_rejoined(self) -> None:
        html = self.render([
            flow_span("a good exam-", line=0, y0=100),
            flow_span("ple of it", line=1, y0=112),
        ])
        self.assertIn("example", html)

    def test_internal_links_are_kept(self) -> None:
        html = self.render([flow_span("The URL", link_page=64)])
        self.assertIn('<a href="page:64">', html)

    def test_raised_small_span_is_a_superscript(self) -> None:
        html = self.render([
            flow_span("the inverse map f", x0=50, y0=100),
            Span(text="-1", size=7, x0=152, x1=160, y0=96, y1=104, origin_y=103,
                 block=0, line=0),
        ])
        self.assertIn("<sup>-1</sup>", html)

    def test_small_limits_row_under_a_formula_stays_in_the_paragraph(self) -> None:
        html = self.render([
            flow_span("so that f(x) is in the union", line=0, y0=100),
            flow_span("B in J", size=7, line=1, x0=120, y0=112),
        ])
        self.assertEqual(html.count("<p"), 1)


class FormulaCropTests(unittest.TestCase):
    """Formulas are shown as crops of the page, found from their fonts."""

    def render(self, spans):
        calls = []

        def renderer(rect, px_per_pt, pad_top, pad_bottom):
            calls.append(rect)
            return ("formula", 10.0, 10.0)

        page = PageLayout(width=430, height=800, spans=tuple(spans))
        html = layout.flow_html(page, base_pt=12, body_pt=10, bionic_enabled=False,
                                math_renderer=renderer)
        return html, calls

    def test_math_fonts_are_recognised(self) -> None:
        for name in ("CMMI10", "ABCDEF+CMSY7", "STIXTwoMath-Regular", "MTMI3", "rblmi0100"):
            self.assertTrue(layout._is_math_font(name), name)
        for name in ("Times-Roman", "LiberationSerif-Bold", "CMR10", "CMTI10"):
            self.assertFalse(layout._is_math_font(name), name)

    def test_inline_formula_becomes_one_image_inside_the_prose(self) -> None:
        html, calls = self.render([
            flow_span("Assume that ", font="CMR10", x0=50, y0=100),
            Span(text="x", size=10, font="CMMI10", x0=122, x1=128, y0=100, y1=112,
                 origin_y=110, block=0, line=0),
            Span(text=" ∈", size=10, font="CMSY10", x0=128, x1=138, y0=100, y1=112,
                 origin_y=110, block=0, line=0),
            Span(text="B", size=10, font="CMMI10", x0=139, x1=146, y0=100, y1=112,
                 origin_y=110, block=0, line=0),
            flow_span(" holds.", font="CMR10", x0=146, y0=100),
        ])
        self.assertEqual(len(calls), 1)
        self.assertEqual(html.count("<img"), 1)
        self.assertIn("Assume that", html)
        self.assertIn("holds.", html)
        self.assertNotIn("∈", html)

    def test_formulas_on_consecutive_lines_stay_separate(self) -> None:
        def formula(line: int, y0: float) -> list[Span]:
            return [
                Span(text="f", size=10, font="CMMI10", x0=60, x1=66, y0=y0, y1=y0 + 12,
                     origin_y=y0 + 10, block=0, line=line),
                Span(text="1", size=7, font="CMR7", x0=66, x1=70, y0=y0 - 2, y1=y0 + 6,
                     origin_y=y0 + 5, block=0, line=line),
            ]
        _html, calls = self.render(formula(0, 100) + formula(1, 112))
        self.assertEqual(len(calls), 2)

    def test_limits_under_a_big_operator_join_its_formula(self) -> None:
        _html, calls = self.render([
            Span(text="\x04", size=10, font="CMEX10", x0=100, x1=110, y0=92, y1=102,
                 origin_y=100, block=0, line=0, ink_y0=100, ink_y1=112),
            Span(text="A", size=10, font="CMMI10", x0=112, x1=118, y0=100, y1=112,
                 origin_y=110, block=0, line=0),
            Span(text="i∈I", size=7, font="CMMI7", x0=100, x1=110, y0=113, y1=120,
                 origin_y=119, block=0, line=1),
        ])
        self.assertEqual(len(calls), 1)
        x0, y0, x1, y1 = calls[0]
        self.assertGreaterEqual(y1, 120)

    def test_paragraph_of_only_a_formula_is_centred(self) -> None:
        html, _calls = self.render([
            Span(text="x = y", size=10, font="CMMI10", x0=150, x1=200, y0=100, y1=112,
                 origin_y=110, block=0, line=0),
        ])
        self.assertIn("text-align:center", html)


class FormulaDetectionTests(unittest.TestCase):
    """Finding formulas in books that do not use TeX maths fonts."""

    def render(self, spans, rules=()):
        calls = []

        def renderer(rect, px_per_pt, pad_top, pad_bottom):
            calls.append(rect)
            return ("formula", 10.0, 10.0)

        page = PageLayout(width=430, height=800, spans=tuple(spans), rules=tuple(rules))
        html = layout.flow_html(page, base_pt=12, body_pt=10, bionic_enabled=False,
                                math_renderer=renderer)
        return html, calls

    def test_unknown_font_runs_are_maths_but_text_fonts_are_not(self) -> None:
        body = frozenset({"TimesLTStd-Roman"})
        publisher_maths = flow_span("=", font="WWDOC01")
        italic_variable = flow_span("a particle varies with", font="TimesLTStd-Italic")
        self.assertTrue(layout._math_core(publisher_maths, body))
        self.assertFalse(layout._math_core(italic_variable, body))

    def test_a_fraction_bar_binds_numerator_and_denominator(self) -> None:
        # "m0" over "1 - v", as a publisher sets it: the bar is a drawing.
        spans = [
            flow_span("prose before it", font="Times-Roman", x0=50, y0=60),
            flow_span("m", font="Times-Italic", block=1, x0=150, y0=90),
            flow_span("0", font="Times-Roman", block=1, x0=157, y0=93),
            flow_span("1", font="Times-Roman", block=2, line=0, x0=148, y0=112),
            flow_span("v", font="Times-Italic", block=2, line=0, x0=160, y0=112),
        ]
        rules = [(146.0, 108.0, 172.0, 108.0)]
        _html, without = self.render(spans)
        _html, with_rule = self.render(spans, rules)
        # With no bar there is no formula at all: every span is ordinary text.
        self.assertEqual(without, [])
        self.assertEqual(len(with_rule), 1)   # the bar makes it one fraction
        x0, y0, x1, y1 = with_rule[0]
        self.assertLessEqual(y0, 108.0)
        self.assertGreaterEqual(y1, 108.0)

    def test_a_runaway_cluster_falls_back_to_text(self) -> None:
        """A formula taller than a few lines means the grouping went wrong."""
        spans = [
            Span(text="∫", size=10, font="CMEX10", x0=100, x1=110, y0=100, y1=110,
                 origin_y=108, block=0, line=0, ink_y0=100, ink_y1=400),
            Span(text="x", size=10, font="CMMI10", x0=112, x1=118, y0=380, y1=392,
                 origin_y=390, block=0, line=1),
        ]
        _html, calls = self.render(spans)
        self.assertEqual(calls, [])
