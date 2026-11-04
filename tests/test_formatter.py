"""Tests for src/formatter.py.

The expected strings follow the notation of the course: dots up to the
third derivative, y⁽⁴⁾ from the fourth on, and the highest derivative
isolated as on the lecture slides, for example
ẏ = (0.5u − 3y) / 2 from lecture 1.
"""

import io
import unittest

from matplotlib import mathtext

from src.formatter import derivative_latex, derivative_text, to_latex, to_text
from src.parser import parse_system

# Combining dots above, as produced by the formatter.
DOT1, DOT2, DOT3 = "̇", "̈", "⃛"


class TestDerivativeNotation(unittest.TestCase):
    """Notation of a single derivative."""

    def test_latex_dots_up_to_third_order(self):
        self.assertEqual(derivative_latex("y", 0), "y")
        self.assertEqual(derivative_latex("y", 1), r"\dot{y}")
        self.assertEqual(derivative_latex("y", 2), r"\ddot{y}")
        self.assertEqual(derivative_latex("y", 3), r"\dddot{y}")

    def test_latex_parentheses_from_fourth_order(self):
        self.assertEqual(derivative_latex("y", 4), "y^{(4)}")
        self.assertEqual(derivative_latex("y", 5), "y^{(5)}")

    def test_latex_subscript(self):
        self.assertEqual(derivative_latex("x1", 2), r"\ddot{x}_{1}")

    def test_text_notation(self):
        self.assertEqual(derivative_text("y", 1), "y" + DOT1)
        self.assertEqual(derivative_text("y", 3), "y" + DOT3)
        self.assertEqual(derivative_text("y", 4), "y⁽⁴⁾")
        self.assertEqual(derivative_text("x2", 1), "x" + DOT1 + "₂")


class TestSingleEquations(unittest.TestCase):
    """Interpreted and solved forms of one equation."""

    def test_exercise_1_text(self):
        interpreted, solved = to_text(parse_system("y'' + 3y' = u"))
        self.assertEqual(interpreted, [f"y{DOT2}(t) + 3y{DOT1}(t) = u(t)"])
        self.assertEqual(solved, [f"y{DOT2}(t) = u(t) - 3y{DOT1}(t)"])

    def test_lecture_example_fraction_and_decimal(self):
        """Lecture 1: 2ẏ + 3y = 0.5u gives ẏ = (0.5u − 3y) / 2."""
        interpreted, solved = to_latex(parse_system("2y' + 3y = 0.5u"))
        self.assertEqual(interpreted, [r"2 \dot{y}(t) + 3 y(t) = 0.5 u(t)"])
        self.assertEqual(solved, [r"\dot{y}(t) = \dfrac{0.5 u(t) - 3 y(t)}{2}"])

    def test_exercise_10_leading_coefficient(self):
        _, solved = to_text(parse_system("5y''' + 10y'' + 10y' + 2y = u"))
        expected = f"y{DOT3}(t) = (u(t) - 10y{DOT2}(t) - 10y{DOT1}(t) - 2y(t)) / 5"
        self.assertEqual(solved, [expected])

    def test_exercise_2_power_before_time(self):
        _, solved = to_latex(parse_system("y'' + 2y'^3 + y = u"))
        self.assertEqual(solved, [r"\ddot{y}(t) = u(t) - 2 \dot{y}^{3}(t) - y(t)"])

    def test_exercise_8_absolute_value(self):
        interpreted, _ = to_text(parse_system("y''' + 3y''*abs(y') + 0.5y' + y'^2*y = u"))
        self.assertIn(f"3y{DOT2}(t)·|y{DOT1}(t)|", interpreted[0])

    def test_fifth_order_lecture_task(self):
        interpreted, _ = to_latex(parse_system("y''''' + 5.5y'''' + 3.5y''' + 5y'' + y' + y = u"))
        self.assertTrue(interpreted[0].startswith(r"y^{(5)}(t) + 5.5 y^{(4)}(t) + 3.5 \dddot{y}(t)"))


class TestSystems(unittest.TestCase):
    """Systems are solved one equation at a time, as in lecture 2."""

    def test_exercise_3(self):
        _, solved = to_text(parse_system("y''' + 5y'' + 2y' + y + z = u ; z'' + z' + z + y = v"))
        self.assertEqual(solved, [
            f"y{DOT3}(t) = u(t) - 5y{DOT2}(t) - 2y{DOT1}(t) - y(t) - z(t)",
            f"z{DOT2}(t) = v(t) - z{DOT1}(t) - z(t) - y(t)",
        ])

    def test_exercise_6_keeps_other_derivatives_as_signals(self):
        """ż stays in the first equation instead of being substituted."""
        text = "y'' + 5y' + y + z' + x' = 0; z' + z + x' = u; x'' + 0.5x' + x - z' = 0"
        _, solved = to_text(parse_system(text))
        self.assertEqual(solved[0], f"y{DOT2}(t) = -5y{DOT1}(t) - y(t) - z{DOT1}(t) - x{DOT1}(t)")
        self.assertEqual(solved[1], f"z{DOT1}(t) = u(t) - z(t) - x{DOT1}(t)")

    def test_exercise_12_falls_back_to_full_solution(self):
        """Both third derivatives are in both equations, so they are solved together."""
        text = ("2y''' + 5y'' + y' + 2y + z''' + 1.5z'' + 2z' + 2z = u ; "
                "3z''' + 2z'' + 5z' + 2z - y''' - 5y'' - 3y' - 2y = 0")
        _, solved = to_text(parse_system(text))
        self.assertTrue(solved[0].startswith(f"y{DOT3}(t) = 3u(t)/7"))
        self.assertNotIn(f"z{DOT3}", solved[0])

    def test_two_springs_keep_parentheses(self):
        text = ("m1*x1'' + b1*x1' + k1*x1 - b2*(x2' - x1') - k2*(x2 - x1) = 0 ; "
                "m2*x2'' + b2*(x2' - x1') + k2*(x2 - x1) = F")
        _, solved = to_latex(parse_system(text))
        self.assertIn(r"\left(\dot{x}_{2}(t) - \dot{x}_{1}(t)\right)", solved[1])


class TestRendering(unittest.TestCase):
    """Every LaTeX line must be drawable by matplotlib (no window needed)."""

    def test_all_examples_render(self):
        examples = [
            "2y' + 3y = 0.5u",
            "y''' + 3y''*abs(y') + 0.5y' + y'^2*y = u",
            "y''''' + 5.5y'''' + 3.5y''' + 5y'' + y' + y = u",
            "y''' + 5y'' + y' + y - z' = u ; 3z'' + 0.3z' + z - y'' + y' = 0",
            "x' - 10(y - x) = u ; y' + y - x*(30 - z) = 0 ; z' - x*y + 8/3 z = 0",
        ]
        for text in examples:
            interpreted, solved = to_latex(parse_system(text))
            for line in interpreted + solved:
                with self.subTest(line=line):
                    mathtext.math_to_image(f"${line}$", io.BytesIO(), format="png")


if __name__ == "__main__":
    unittest.main()
