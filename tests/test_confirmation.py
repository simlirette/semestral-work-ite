"""Tests for src/confirmation.py.

The window itself is checked by hand (see docs/tests.md). These tests
check the question-and-answer logic by replacing the keyboard input
with a list of prepared answers.
"""

import contextlib
import io
import unittest

from src.confirmation import ask_confirmation
from src.parser import parse_system


def answers(*replies):
    """Return a fake `input` function that gives the replies in order."""
    remaining = iter(replies)
    return lambda prompt: next(remaining)


class TestAskConfirmation(unittest.TestCase):
    """The user confirms or rejects the interpreted equation."""

    def setUp(self):
        self.system = parse_system("y'' + 3y' = u")

    def confirm(self, *replies):
        """Run the confirmation without a window and without printing."""
        with contextlib.redirect_stdout(io.StringIO()):
            return ask_confirmation(self.system, use_window=False, ask=answers(*replies))

    def test_yes(self):
        self.assertTrue(self.confirm("y"))
        self.assertTrue(self.confirm(" YES "))

    def test_no(self):
        self.assertFalse(self.confirm("n"))

    def test_asks_again_after_invalid_answer(self):
        self.assertTrue(self.confirm("maybe", "", "y"))

    def test_prints_the_equations(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            ask_confirmation(self.system, use_window=False, ask=answers("y"))
        self.assertIn("u(t) - 3", output.getvalue())


if __name__ == "__main__":
    unittest.main()
