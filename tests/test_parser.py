"""Tests for src/parser.py.

The valid cases are equations from the course exercise sheet
("Review of differential equations"), numbered as in the sheet.
Each test checks that the equation is solved for the right highest
derivative. The error cases check that badly written equations are
rejected with an EquationError instead of producing a wrong model.
"""

import unittest

import sympy

from src.parser import EquationError, derivative_symbol, parse_initial_conditions, parse_system, split_symbol

# Symbols used to write the expected results.
u, v = sympy.symbols("u v")
y, y1, y2 = (derivative_symbol("y", k) for k in range(3))
z, z1 = (derivative_symbol("z", k) for k in range(2))


class TestSymbols(unittest.TestCase):
    """The naming of derivative symbols."""

    def test_round_trip(self):
        """A derivative symbol splits back into its name and order."""
        self.assertEqual(split_symbol(derivative_symbol("x1", 3)), ("x1", 3))
        self.assertEqual(split_symbol(derivative_symbol("y", 0)), ("y", 0))


class TestSingleEquations(unittest.TestCase):
    """One equation, linear or nonlinear (version 1.0 scope)."""

    def assert_solved(self, text, order, expected):
        """Parse `text` and compare the solved highest derivative of y."""
        system = parse_system(text)
        self.assertEqual(system.orders, {"y": order})
        self.assertEqual(system.inputs, ("u",))
        self.assertEqual(sympy.simplify(system.solved["y"] - expected), 0)

    def test_exercise_1(self):
        self.assert_solved("y'' + 3y' = u", 2, u - 3 * y1)

    def test_exercise_2_nonlinear_power(self):
        self.assert_solved("y'' + 2y'^3 + y = u", 2, u - 2 * y1**3 - y)

    def test_exercise_5_decimal_coefficient(self):
        self.assert_solved("y''' + 0.5y'' + y' = u", 3, u - y2 / 2 - y1)

    def test_exercise_8_abs_and_products(self):
        expected = u - 3 * y2 * sympy.Abs(y1) - y1 / 2 - y1**2 * y
        self.assert_solved("y''' + 3y''*abs(y') + 0.5y' + y'^2*y = u", 3, expected)

    def test_exercise_10_leading_coefficient(self):
        expected = (u - 10 * y2 - 10 * y1 - 2 * y) / 5
        self.assert_solved("5y''' + 10y'' + 10y' + 2y = u", 3, expected)

    def test_exercise_11(self):
        self.assert_solved("3y'' + y' + 2y = u", 2, (u - y1 - 2 * y) / 3)

    def test_optional_time_argument(self):
        """Writing (t) after each variable gives the same result."""
        self.assert_solved("y''(t) + 3y'(t) = u(t)", 2, u - 3 * y1)

    def test_zero_right_hand_side(self):
        system = parse_system("y'' + 4y = 0")
        self.assertEqual(system.inputs, ())
        self.assertEqual(system.solved["y"], -4 * y)


class TestSystems(unittest.TestCase):
    """Several coupled equations (version 1.1 scope)."""

    def test_exercise_3(self):
        system = parse_system("y''' + 5y'' + 2y' + y + z = u ; z'' + z' + z + y = v")
        self.assertEqual(system.orders, {"y": 3, "z": 2})
        self.assertEqual(system.inputs, ("u", "v"))
        self.assertEqual(sympy.simplify(system.solved["y"] - (u - 5 * y2 - 2 * y1 - y - z)), 0)
        self.assertEqual(sympy.simplify(system.solved["z"] - (v - z1 - z - y)), 0)

    def test_exercise_12_highest_derivatives_coupled(self):
        """Both third derivatives appear in both equations."""
        text = ("2y''' + 5y'' + y' + 2y + z''' + 1.5z'' + 2z' + 2z = u ; "
                "3z''' + 2z'' + 5z' + 2z - y''' - 5y'' - 3y' - 2y = 0")
        system = parse_system(text)
        self.assertEqual(system.orders, {"y": 3, "z": 3})
        # Substituting the solution back must satisfy both equations.
        values = {derivative_symbol("y", 3): system.solved["y"],
                  derivative_symbol("z", 3): system.solved["z"]}
        for equation in system.equations:
            self.assertEqual(sympy.simplify((equation.lhs - equation.rhs).subs(values)), 0)


class TestInvalidInput(unittest.TestCase):
    """Badly written equations must be rejected."""

    def assert_rejected(self, text):
        with self.assertRaises(EquationError):
            parse_system(text)

    def test_empty_text(self):
        self.assert_rejected("   ")

    def test_missing_equal_sign(self):
        self.assert_rejected("y'' + 3y'")

    def test_two_equal_signs(self):
        self.assert_rejected("y'' = u = v")

    def test_empty_side(self):
        self.assert_rejected("y'' + 3y' =")

    def test_no_derivative(self):
        self.assert_rejected("y + 3 = u")

    def test_more_unknowns_than_equations(self):
        self.assert_rejected("y'' + z'' = u")

    def test_highest_derivative_squared(self):
        self.assert_rejected("y''^2 + y = u")

    def test_unsupported_character(self):
        self.assert_rejected("y'' + 3y' = u$")

    def test_unknown_function(self):
        self.assert_rejected("y'' + foo(y) = u")

    def test_apostrophe_without_variable(self):
        self.assert_rejected("(y + 1)' = u")

    def test_unsolvable_system(self):
        self.assert_rejected("y' + z' = u ; y' + z' = v")


class TestInitialConditions(unittest.TestCase):
    """Starting values written like y(0)=1, y'(0)=0.5 (lecture "Initial conditions")."""

    def setUp(self):
        self.orders = parse_system("y'' + 3y' = u").orders

    def test_values_by_variable_and_order(self):
        values = parse_initial_conditions("y(0)=1, y'(0)=0.5", self.orders)
        self.assertEqual(values, {("y", 0): 1, ("y", 1): sympy.Rational(1, 2)})

    def test_spaces_negative_values_and_fractions(self):
        values = parse_initial_conditions(" y(0) = -2 , y'(0) = 1/3 ", self.orders)
        self.assertEqual(values, {("y", 0): -2, ("y", 1): sympy.Rational(1, 3)})

    def test_values_not_given_are_left_out(self):
        """Missing values are 0 later, when the Integrators are built."""
        self.assertEqual(parse_initial_conditions("y'(0)=4", self.orders), {("y", 1): 4})

    def test_system(self):
        orders = parse_system("y''' + 5y'' + 2y' + y + z = u ; z'' + z' + z + y = v").orders
        values = parse_initial_conditions("y''(0)=1, z'(0)=2", orders)
        self.assertEqual(values, {("y", 2): 1, ("z", 1): 2})

    def test_rejected(self):
        """Each of these must stop the program with a clear message."""
        for text in ("y''(0)=1",       # y'' has no Integrator of its own
                     "z(0)=1",         # z is not in the equation
                     "y(0)=a",         # not a number
                     "y=1",            # (0) missing
                     "y(1)=1",         # only t = 0 is allowed
                     "y(0)=",          # value missing
                     "y(0)=1, y(0)=2"):  # given twice
            with self.subTest(text=text), self.assertRaises(EquationError):
                parse_initial_conditions(text, self.orders)


if __name__ == "__main__":
    unittest.main()
