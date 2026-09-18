"""Unit tests for PDF page-text re-flowing (no PDF file needed)."""

from __future__ import annotations

import unittest

from saccade.document import reflow


class DehyphenationTests(unittest.TestCase):
    def test_soft_hyphen_line_break_is_joined(self) -> None:
        self.assertEqual(reflow("The exam-\nple works."), "The example works.")

    def test_unicode_hyphen_is_joined(self) -> None:
        self.assertEqual(reflow("A co\u2010\noperate deal."), "A cooperate deal.")

    def test_hyphen_before_capital_is_kept(self) -> None:
        # "Anglo-\nSaxon" is a real hyphen, not a broken word.
        self.assertEqual(reflow("Anglo-\nSaxon"), "Anglo- Saxon")

    def test_dehyphenation_can_be_disabled(self) -> None:
        self.assertEqual(reflow("exam-\nple", dehyphenate=False), "exam- ple")


class ParagraphTests(unittest.TestCase):
    def test_blank_line_separates_paragraphs(self) -> None:
        self.assertEqual(reflow("one\ntwo\n\nthree"), "one two\n\nthree")

    def test_indented_line_starts_a_paragraph(self) -> None:
        text = "end of the first para\n    And the second one."
        self.assertEqual(reflow(text), "end of the first para\n\nAnd the second one.")

    def test_indentation_heuristic_can_be_disabled(self) -> None:
        text = "end of the first para\n    And the second one."
        self.assertEqual(reflow(text, smart_paragraphs=False),
                         "end of the first para And the second one.")

    def test_line_whitespace_is_collapsed(self) -> None:
        self.assertEqual(reflow("too   many    spaces"), "too many spaces")

    def test_windows_and_mac_line_endings(self) -> None:
        self.assertEqual(reflow("one\r\ntwo\rthree"), "one two three")


class NormalisationTests(unittest.TestCase):
    def test_ligatures_are_expanded(self) -> None:
        self.assertIn("office", reflow("of\ufb01ce"))

    def test_soft_hyphens_are_dropped(self) -> None:
        self.assertEqual(reflow("won\u00adder"), "wonder")

    def test_empty_input(self) -> None:
        self.assertEqual(reflow(""), "")
        self.assertEqual(reflow("   \n\n  "), "")


if __name__ == "__main__":
    unittest.main()