"""Tests for src/block_model.py.

Specific tests compare the generated blocks with the solution schemes
of the course exercises (for example exercise 1: two Integrators, a
Gain 3 and a Sum with signs + −). A structural test then checks, for
every exercise, that the model is complete: each input port receives
exactly one line, and every block except the Scope is used.
"""

import unittest

from src.block_model import build_block_model, number_text
from src.parser import parse_system

EXERCISES = {
    "1": "y'' + 3y' = u",
    "2": "y'' + 2y'^3 + y = u",
    "3": "y''' + 5y'' + 2y' + y + z = u ; z'' + z' + z + y = v",
    "5": "y''' + 0.5y'' + y' = u",
    "6": "y'' + 5y' + y + z' + x' = 0 ; z' + z + x' = u ; x'' + 0.5x' + x - z' = 0",
    "7": "y''' + 5y'' + y' + y - z' = u ; 3z'' + 0.3z' + z - y'' + y' = 0",
    "8": "y''' + 3y''*abs(y') + 0.5y' + y'^2*y = u",
    "9": "x' - 10(y - x) = u ; y' + y - x*(30 - z) = 0 ; z' - x*y + 8/3 z = 0",
    "10": "5y''' + 10y'' + 10y' + 2y = u",
    "11": "3y'' + y' + 2y = u",
    "12": ("2y''' + 5y'' + y' + 2y + z''' + 1.5z'' + 2z' + 2z = u ; "
           "3z''' + 2z'' + 5z' + 2z - y''' - 5y'' - 3y' - 2y = 0"),
}


def model_of(number, initial_conditions=None):
    """Build the block model of one course exercise."""
    return build_block_model(parse_system(EXERCISES[number]), initial_conditions)


def kinds(model):
    """Count the blocks of each kind."""
    counts = {}
    for block in model.blocks:
        counts[block.kind] = counts.get(block.kind, 0) + 1
    return counts


class TestNumberText(unittest.TestCase):
    """Numbers written in block parameters."""

    def test_formats(self):
        self.assertEqual(number_text(3), "3")
        self.assertEqual(number_text(0.5), "0.5")
        self.assertEqual(number_text(1.5), "1.5")
        self.assertEqual(number_text(-2), "-2")


class TestCourseSchemes(unittest.TestCase):
    """Blocks match the solution schemes of the exercises."""

    def test_exercise_1(self):
        model = model_of("1")
        self.assertEqual(kinds(model),
                         {"Integrator": 2, "Step": 1, "Gain": 1, "Sum": 1, "Mux": 1, "Scope": 1})
        self.assertEqual(model.of_kind("Gain")[0].parameters["Gain"], "3")
        total = model.of_kind("Sum")[0]
        self.assertEqual(total.parameters["Inputs"], "+-")
        sources = [line.source for line in model.inputs_of(total.name)]
        self.assertEqual(sources, ["Step u", "Gain1"])

    def test_integrators_are_chained(self):
        """y'' enters the first Integrator, whose output y' enters the second."""
        model = model_of("1")
        self.assertEqual([line.source for line in model.inputs_of("Integrator y'")], ["Sum1"])
        self.assertEqual([line.source for line in model.inputs_of("Integrator y")], ["Integrator y'"])

    def test_exercise_11_gain_for_leading_coefficient(self):
        """3ÿ = u − ẏ − 2y needs a Gain 1/3 between the Sum and the Integrator."""
        model = model_of("11")
        last = model.inputs_of("Integrator y'")[0].source
        self.assertEqual(model.block(last).parameters["Gain"], "1/3")
        self.assertEqual(model.of_kind("Sum")[0].parameters["Inputs"], "+--")

    def test_exercise_2_power_block(self):
        model = model_of("2")
        power = model.of_kind("Fcn")[0]
        self.assertEqual(power.parameters["Expr"], "u^3")
        self.assertEqual(model.inputs_of(power.name)[0].source, "Integrator y'")

    def test_exercise_8_product_and_abs(self):
        model = model_of("8")
        counts = kinds(model)
        self.assertEqual(counts["Abs"], 1)
        self.assertEqual(counts["Product"], 2)  # ÿ·|ẏ| and y·ẏ²
        self.assertEqual(counts["Integrator"], 3)

    def test_exercise_3_two_chains(self):
        model = model_of("3")
        self.assertEqual(kinds(model)["Integrator"], 5)  # 3 for y, 2 for z
        self.assertEqual(kinds(model)["Step"], 2)        # u and v
        signs = [block.parameters["Inputs"] for block in model.of_kind("Sum")]
        self.assertEqual(sorted(signs), ["+---", "+----"])

    def test_exercise_6_derivative_used_as_signal(self):
        """ż, computed by the Sum of the second equation, enters the first Sum."""
        model = model_of("6")
        z_dot = model.inputs_of("Integrator z")[0].source
        y_sum = model.inputs_of("Integrator y'")[0].source
        self.assertIn(z_dot, [line.source for line in model.inputs_of(y_sum)])

    def test_initial_conditions(self):
        model = model_of("1", {("y", 0): 1, ("y", 1): 0.5})
        self.assertEqual(model.block("Integrator y").parameters["InitialCondition"], "1")
        self.assertEqual(model.block("Integrator y'").parameters["InitialCondition"], "0.5")

    def test_default_initial_conditions_are_zero(self):
        model = model_of("10")
        for block in model.of_kind("Integrator"):
            self.assertEqual(block.parameters["InitialCondition"], "0")

    def test_one_mux_per_equation(self):
        """Exercise 3: Mux [u, y] and Mux [v, z] feed the two Scope inputs."""
        model = model_of("3")
        muxes = model.of_kind("Mux")
        labels = [[line.label for line in model.inputs_of(mux.name)] for mux in muxes]
        self.assertEqual(labels, [["u", "y"], ["v", "z"]])
        scope = model.of_kind("Scope")[0]
        self.assertEqual([line.source for line in model.inputs_of(scope.name)], ["Mux1", "Mux2"])

    def test_equation_without_input_skips_the_mux(self):
        """Exercise 6: only the second equation contains u."""
        model = model_of("6")
        scope = model.of_kind("Scope")[0]
        sources = [line.source for line in model.inputs_of(scope.name)]
        self.assertEqual(sources, ["Integrator y", "Mux1", "Integrator x"])


class TestModelIsComplete(unittest.TestCase):
    """Structural checks on every exercise."""

    def test_every_input_port_connected_once(self):
        for number in EXERCISES:
            model = model_of(number)
            for block in model.blocks:
                with self.subTest(exercise=number, block=block.name):
                    ports = [line.target_port for line in model.inputs_of(block.name)]
                    self.assertEqual(ports, list(range(1, block.input_count() + 1)))

    def test_every_block_output_is_used(self):
        for number in EXERCISES:
            model = model_of(number)
            used = {line.source for line in model.lines}
            for block in model.blocks:
                if block.kind != "Scope":
                    with self.subTest(exercise=number, block=block.name):
                        self.assertIn(block.name, used)

    def test_block_names_are_unique(self):
        for number in EXERCISES:
            names = [block.name for block in model_of(number).blocks]
            self.assertEqual(len(names), len(set(names)), number)


if __name__ == "__main__":
    unittest.main()
