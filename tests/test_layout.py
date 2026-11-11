"""Tests for src/layout.py.

The layout cannot be judged fully by a program (the final check is
looking at the canvas in MATLAB, see docs/tests.md), but its rules can:
the main chain of each equation is on one horizontal row, from left to
right; feedback blocks are under that row and face left; equations are
stacked in separate bands; and no two blocks overlap.
"""

import unittest

from src.block_model import build_block_model
from src.layout import compute_layout
from src.parser import parse_system

EXAMPLES = [
    "y'' + 3y' = u",
    "3y'' + y' + 2y = u",
    "y'' + 2y'^3 + y = u",
    "y''' + 3y''*abs(y') + 0.5y' + y'^2*y = u",
    "y''' + 5y'' + 2y' + y + z = u ; z'' + z' + z + y = v",
    "y'' + 5y' + y + z' + x' = 0 ; z' + z + x' = u ; x'' + 0.5x' + x - z' = 0",
    "x' - 10(y - x) = u ; y' + y - x*(30 - z) = 0 ; z' - x*y + 8/3 z = 0",
    ("2y''' + 5y'' + y' + 2y + z''' + 1.5z'' + 2z' + 2z = u ; "
     "3z''' + 2z'' + 5z' + 2z - y''' - 5y'' - 3y' - 2y = 0"),
    "y'' = u",
    "y'' = 2u",
]


def centre(box):
    """Centre of a (left, top, right, bottom) box."""
    left, top, right, bottom = box
    return (left + right) / 2, (top + bottom) / 2


def overlap(a, b):
    """True if two boxes overlap."""
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


class TestExercise11(unittest.TestCase):
    """Layout of 3ÿ + ẏ + 2y = u, checked against the course scheme."""

    def setUp(self):
        self.model = build_block_model(parse_system("3y'' + y' + 2y = u"))
        self.layout = compute_layout(self.model)
        self.centres = {name: centre(box) for name, box in self.layout.positions.items()}

    def test_main_chain_on_one_row_left_to_right(self):
        chain = ["Step u", "Sum1", "Gain2", "Integrator y'", "Integrator y"]
        # The Mux's last input (y) is level with the row too.
        heights = {self.centres[name][1] for name in chain}
        self.assertEqual(len(heights), 1)
        xs = [self.centres[name][0] for name in chain]
        self.assertEqual(xs, sorted(xs))

    def test_feedback_gain_below_and_facing_left(self):
        self.assertGreater(self.centres["Gain1"][1], self.centres["Sum1"][1])
        self.assertEqual(self.layout.facing_left, {"Gain1"})

    def test_sum_inputs_ordered_by_direction(self):
        """u on the left of the circle, then 2y (deepest loop), then y'."""
        self.assertEqual(self.layout.port_order["Sum1"], [1, 3, 2])
        self.assertEqual(self.layout.sum_slots["Sum1"], [None, None, 1, 3, 2])

    def test_every_wire_has_a_path(self):
        self.assertEqual(len(self.layout.routes), len(self.model.lines))

    def test_mux_after_the_chain(self):
        self.assertGreater(self.layout.positions["Mux1"][0], self.layout.positions["Integrator y"][2])
        self.assertEqual(self.layout.positions["Mux1"][3] - 10, self.centres["Integrator y"][1])

    def test_scope_on_the_right(self):
        rightmost = max(box[2] for name, box in self.layout.positions.items() if name != "Scope1")
        self.assertGreater(self.layout.positions["Scope1"][0], rightmost)


class TestExercise3(unittest.TestCase):
    """Nested loops and wires between equations, as in the course scheme."""

    def setUp(self):
        self.model = build_block_model(parse_system(EXAMPLES[4]))
        self.layout = compute_layout(self.model)

    def route_to(self, source, target):
        for index, line in enumerate(self.model.lines):
            if line.source == source and line.target == target:
                return self.layout.routes[index]
        raise KeyError((source, target))

    def test_loops_are_nested(self):
        """The deeper a loop goes, the further left it climbs back to the Sum."""
        gain_5 = self.route_to("Gain1", "Sum1").moves[-1][1]
        gain_2 = self.route_to("Gain2", "Sum1").moves[-1][1]
        loop_y = self.route_to("Integrator y", "Sum1").moves
        self.assertGreater(gain_5, gain_2)
        self.assertGreater(gain_2, loop_y[-1][1])

    def test_branches_further_right_go_deeper(self):
        own_loop = self.route_to("Integrator y", "Sum1")
        to_other_equation = self.route_to("Integrator y", "Sum2")
        self.assertGreater(to_other_equation.tap_x, own_loop.tap_x)
        self.assertGreater(to_other_equation.moves[0][1], own_loop.moves[0][1])

    def test_wires_between_equations_use_the_gap(self):
        """y goes down to the second Sum and z goes up to the first one,
        both between the two bands."""
        bottom_of_band_1 = max(self.layout.positions[n][3] for n in ("Gain1", "Gain2"))
        top_of_band_2 = self.layout.positions["Integrator z'"][1]
        for source, target in (("Integrator y", "Sum2"), ("Integrator z", "Sum1")):
            lane_y = self.route_to(source, target).moves[0][1]
            self.assertTrue(bottom_of_band_1 < lane_y < top_of_band_2)


class TestAllExamples(unittest.TestCase):
    """General rules, checked on every example."""

    def test_every_block_placed_without_overlap(self):
        for text in EXAMPLES:
            model = build_block_model(parse_system(text))
            positions = compute_layout(model).positions
            with self.subTest(text=text):
                self.assertEqual(set(positions), {block.name for block in model.blocks})
                boxes = list(positions.items())
                for i, (name_a, box_a) in enumerate(boxes):
                    for name_b, box_b in boxes[i + 1:]:
                        self.assertFalse(overlap(box_a, box_b), f"{name_a} overlaps {name_b}")

    def test_equations_in_separate_bands(self):
        """The integrators of y are above those of z in exercise 3."""
        model = build_block_model(parse_system(EXAMPLES[4]))
        positions = compute_layout(model).positions
        lowest_y = max(positions[name][3] for name in ("Integrator y''", "Integrator y'", "Integrator y"))
        highest_z = min(positions[name][1] for name in ("Integrator z'", "Integrator z"))
        self.assertLess(lowest_y, highest_z)

    def test_only_feedback_blocks_face_left(self):
        for text in EXAMPLES:
            model = build_block_model(parse_system(text))
            layout = compute_layout(model)
            kinds = {model.block(name).kind for name in layout.facing_left}
            with self.subTest(text=text):
                self.assertFalse(kinds & {"Integrator", "Step", "Scope"})


if __name__ == "__main__":
    unittest.main()
