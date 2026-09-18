"""Unit tests for the bionic text transformation (no GUI, no PDF needed)."""

from __future__ import annotations

import unittest

from saccade import bionic


class FixationLengthTests(unittest.TestCase):
    """The classic fixation table must be reproduced at the default intensity."""

    def test_classic_table(self) -> None:
        table = {1: 1, 2: 1, 3: 2, 4: 2, 5: 3, 6: 3, 7: 4,
                 8: 4, 9: 5, 10: 5, 11: 6, 12: 6, 13: 7}
        for length, expected in table.items():
            self.assertEqual(
                bionic.fixation_length(length), expected, f"length={length}"
            )

    def test_long_words_are_capped(self) -> None:
        self.assertEqual(bionic.fixation_length(14), 8)
        self.assertEqual(bionic.fixation_length(40), 8)

    def test_single_letter_words_are_fully_bolded(self) -> None:
        self.assertEqual(bionic.fixation_length(1), 1)

    def test_empty_word(self) -> None:
        self.assertEqual(bionic.fixation_length(0), 0)
        self.assertEqual(bionic.fixation_length(-3), 0)

    def test_never_bolds_a_whole_word(self) -> None:
        for length in range(2, 60):
            self.assertLess(bionic.fixation_length(length), length)

    def test_intensity_scales_fixation(self) -> None:
        self.assertLess(
            bionic.fixation_length(9, bionic.MIN_INTENSITY),
            bionic.fixation_length(9),
        )
        self.assertGreater(
            bionic.fixation_length(9, bionic.MAX_INTENSITY),
            bionic.fixation_length(9),
        )

    def test_intensity_is_clamped(self) -> None:
        self.assertEqual(
            bionic.fixation_length(9, 99.0),
            bionic.fixation_length(9, bionic.MAX_INTENSITY),
        )
        self.assertEqual(
            bionic.fixation_length(9, 0.0),
            bionic.fixation_length(9, bionic.MIN_INTENSITY),
        )
        self.assertGreaterEqual(bionic.fixation_length(2, -5.0), 1)


class SplitWordTests(unittest.TestCase):
    def test_plain_word(self) -> None:
        self.assertEqual(bionic.split_word("reading"), ["reading"])

    def test_apostrophe_and_hyphen(self) -> None:
        self.assertEqual(bionic.split_word("don't"), ["don", "'", "t"])
        self.assertEqual(bionic.split_word("well-known"), ["well", "-", "known"])
        self.assertEqual(bionic.split_word("it\u2019s"), ["it", "\u2019", "s"])

    def test_round_trip(self) -> None:
        for word in ("reading", "don't", "well-known", "a", "O'Brien-Smith"):
            self.assertEqual("".join(bionic.split_word(word)), word)

    def test_empty(self) -> None:
        self.assertEqual(bionic.split_word(""), [])


class BoldSpansTests(unittest.TestCase):
    def test_spans_cover_the_word(self) -> None:
        for word in ("reading", "don't", "well-known", "a", "42", "x",
                     "Donaudampfschifffahrt"):
            spans = bionic.bold_spans(word)
            self.assertEqual("".join(text for text, _ in spans), word)

    def test_joined_words_each_get_a_fixation(self) -> None:
        # "well" (4) -> 2 bolded chars, "known" (5) -> 3 bolded chars.
        bolded = [text for text, is_bold in bionic.bold_spans("well-known") if is_bold]
        self.assertEqual(bolded, ["we", "kno"])

    def test_punctuation_is_never_bolded(self) -> None:
        for text, is_bold in bionic.bold_spans("don't"):
            if text == "'":
                self.assertFalse(is_bold)


class MarkedTextTests(unittest.TestCase):
    def test_simple_sentence(self) -> None:
        # 5-letter "Bionic" -> 3 bolded, 7-letter "reading" -> 4 bolded.
        self.assertEqual(bionic.to_marked("Bionic reading"), "[Bio]nic [read]ing")

    def test_disabled_is_identity(self) -> None:
        text = "Bionic reading, unchanged!"
        self.assertEqual(bionic.to_marked(text, enabled=False), text)

    def test_text_outside_words_is_untouched(self) -> None:
        marked = bionic.to_marked("(hello) 42 \u2014 bye")
        self.assertTrue(marked.startswith("([hel]lo) 42 \u2014 "))
        self.assertTrue(marked.endswith("[by]e"))

    def test_ansi_wraps_with_escape_codes(self) -> None:
        self.assertEqual(bionic.to_ansi("Bionic"), "\033[1mBio\033[0mnic")

    def test_ansi_disabled_is_identity(self) -> None:
        self.assertEqual(bionic.to_ansi("Bionic", enabled=False), "Bionic")


class HtmlTests(unittest.TestCase):
    def test_bold_tags_are_emitted(self) -> None:
        self.assertEqual(
            bionic.to_html("Bionic reading"), "<p><b>Bio</b>nic <b>read</b>ing</p>"
        )

    def test_html_is_escaped(self) -> None:
        html = bionic.to_html("a <b>x & y</b> 3 > 2")
        self.assertIn("&lt;", html)
        self.assertIn("&amp;", html)
        self.assertIn("&gt;", html)
        self.assertNotIn("<b>x & y</b>", html)

    def test_blank_lines_become_paragraphs(self) -> None:
        html = bionic.to_html("one\n\n\ntwo")
        self.assertEqual(html.count("<p>"), 2)

    def test_single_newlines_become_breaks(self) -> None:
        html = bionic.to_html("line one\nline two")
        self.assertIn("<br />", html)
        self.assertEqual(html.count("<p>"), 1)

    def test_disabled_mode_has_no_bold(self) -> None:
        html = bionic.to_html("Bionic reading", enabled=False)
        self.assertNotIn("<b>", html)
        self.assertEqual(html, "<p>Bionic reading</p>")

    def test_intensity_reaches_the_output(self) -> None:
        low = bionic.to_html("wonderful", bionic.MIN_INTENSITY)
        high = bionic.to_html("wonderful", bionic.MAX_INTENSITY)
        self.assertNotEqual(low, high)
        # "wonderful" (9) -> 5 bolded at the default intensity, 8 at the maximum.
        self.assertEqual(bionic.to_html("wonderful"), "<p><b>wonde</b>rful</p>")
        self.assertEqual(high, "<p><b>wonderfu</b>l</p>")

    def test_empty_input(self) -> None:
        self.assertEqual(bionic.to_html(""), "")
        self.assertEqual(bionic.to_html("   \n\n "), "")

    def test_ligatures_and_soft_hyphens_are_normalised(self) -> None:
        # The ligature must be expanded *before* fixations are computed, so the
        # visible word reads "office" even though the tags split it.
        html = bionic.to_html("of\ufb01ce ex\u00adample")
        self.assertEqual(html, "<p><b>off</b>ice <b>exam</b>ple</p>")
        self.assertIn("ice", html)
        self.assertIn("ple", html)

    def test_paragraph_tag_is_configurable(self) -> None:
        self.assertTrue(bionic.to_html("hi", paragraph_tag="div").startswith("<div>"))


class WordCountTests(unittest.TestCase):
    def test_counts(self) -> None:
        self.assertEqual(bionic.word_count("one two three"), 3)
        self.assertEqual(bionic.word_count("don't stop"), 2)
        self.assertEqual(bionic.word_count("... 42!!!"), 0)
        self.assertEqual(bionic.word_count(""), 0)


class UnicodeTests(unittest.TestCase):
    def test_non_latin_words_are_fixated(self) -> None:
        self.assertTrue(bionic.to_marked("\u03b1\u03b2\u03b3\u03b4\u03b5").startswith("["))
        self.assertTrue(bionic.to_marked("\u4e2d\u6587\u5b57").startswith("["))

    def test_accented_words(self) -> None:
        self.assertEqual(bionic.to_marked("caf\u00e9"), "[ca]f\u00e9")


if __name__ == "__main__":
    unittest.main()
