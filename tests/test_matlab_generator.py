"""Tests for src/matlab_generator.py.

MATLAB is not needed: the tests check the text of the generated
script. Whether the script builds the right model in Simulink is
checked by hand in MATLAB (see docs/tests.md).
"""

import re
import tempfile
import unittest
from pathlib import Path

from src.block_model import build_block_model
from src.matlab_generator import LIBRARY, check_model_name, generate_script, matlab_string, write_script
from src.parser import parse_system


def script_for(text, **options):
    """Generate the script of one equation."""
    return generate_script(build_block_model(parse_system(text)), **options)


class TestMatlabString(unittest.TestCase):
    """Quoting text for MATLAB."""

    def test_plain_text(self):
        self.assertEqual(matlab_string("Gain1"), "'Gain1'")

    def test_apostrophes_are_doubled(self):
        self.assertEqual(matlab_string("y''"), "'y'''''")


class TestModelName(unittest.TestCase):
    """Model names must be valid MATLAB names."""

    def test_valid_names(self):
        for name in ("reference_model", "exercise11", "E2b"):
            check_model_name(name)

    def test_invalid_names(self):
        for name in ("", "1model", "my model", "a-b", "x" * 61):
            with self.subTest(name=name), self.assertRaises(ValueError):
                check_model_name(name)


class TestScript(unittest.TestCase):
    """Content of the generated script for exercise 11 (3ÿ + ẏ + 2y = u)."""

    def setUp(self):
        self.script = script_for("3y'' + y' + 2y = u", model_name="exercise11",
                                 equations=("3y'' + y' + 2y = u",))

    def test_creates_the_model(self):
        self.assertIn("model = 'exercise11';", self.script)
        self.assertIn("new_system(model);", self.script)

    def test_equation_written_as_comment(self):
        self.assertIn("%   3y'' + y' + 2y = u", self.script)

    def test_blocks_with_parameters(self):
        self.assertIn("add_block('simulink/Math Operations/Gain', [model '/' 'Gain2'], 'Gain', '1/3', "
                      "'Position', [", self.script)
        # Sum slots from the layout: two empty slots on top, u on the left,
        # then 2y and y' coming from below.
        self.assertIn("'IconShape', 'round', 'Inputs', '||+--'", self.script)
        self.assertIn("route(model, 'Step u', 'Sum1', 1, NaN, [1 ", self.script)
        self.assertIn("[model '/' 'Integrator y'''], 'InitialCondition', '0'", self.script)

    def test_labelled_line(self):
        expected = ("h = route(model, 'Gain2', 'Integrator y''', 1, NaN, zeros(0, 2));\n"
                    "set_param(h, 'Name', 'y''''');")
        self.assertIn(expected, self.script)

    def test_branch_lines_after_port_lines(self):
        """A branch starts on an existing line, so it must be drawn later."""
        trunk = self.script.index("route(model, 'Integrator y''', 'Integrator y', 1, NaN")
        branch = self.script.index("route(model, 'Integrator y''', 'Sum1', 3, ")
        self.assertLess(trunk, branch)

    def test_route_function_included(self):
        self.assertIn("function h = route(model, source, target, port, tapX, moves)", self.script)
        self.assertTrue(self.script.rstrip().endswith("end"))

    def test_positions_and_orientation(self):
        """Every block gets a position; the feedback Gain 2 faces left."""
        self.assertEqual(self.script.count("'Position', ["), self.script.count("add_block("))
        gain = next(line for line in self.script.splitlines() if "'Gain1'" in line and "add_block" in line)
        self.assertIn("'Orientation', 'left'", gain)

    def test_each_signal_named_once(self):
        """Step u branches to the Sum and the Mux, but is named only once."""
        self.assertEqual(self.script.count("'Name', 'u'"), 1)

    def test_simulation_time_and_save(self):
        self.assertIn("set_param(model, 'StopTime', '100');", self.script)
        self.assertIn("save_system(model", self.script)

    def test_apostrophes_are_balanced(self):
        """Every code line has an even number of apostrophes (all strings closed)."""
        for line in self.script.splitlines():
            if line and not line.startswith("%"):
                with self.subTest(line=line):
                    self.assertEqual(line.count("'") % 2, 0)


class TestEveryBlockAndLine(unittest.TestCase):
    """The script contains one add_block per block and one add_line per line."""

    def test_counts_match_the_model(self):
        texts = [
            "y''' + 3y''*abs(y') + 0.5y' + y'^2*y = u",
            "y''' + 5y'' + 2y' + y + z = u ; z'' + z' + z + y = v",
            "x' - 10(y - x) = u ; y' + y - x*(30 - z) = 0 ; z' - x*y + 8/3 z = 0",
        ]
        for text in texts:
            model = build_block_model(parse_system(text))
            script = generate_script(model)
            with self.subTest(text=text):
                self.assertEqual(script.count("add_block("), len(model.blocks))
                drawn = re.findall(r"^(?:h = )?(?:route|add_line)\(model, '", script, re.MULTILINE)
                self.assertEqual(len(drawn), len(model.lines))
                used = set(re.findall(r"add_block\('([^']+)'", script))
                self.assertTrue(used <= set(LIBRARY.values()))


class TestWriteScript(unittest.TestCase):
    """The script is saved as build_<name>.m."""

    def test_file_is_written(self):
        model = build_block_model(parse_system("y'' + 3y' = u"))
        with tempfile.TemporaryDirectory() as folder:
            path = write_script(model, Path(folder) / "out", "exercise1")
            self.assertEqual(path.name, "build_exercise1.m")
            self.assertIn("model = 'exercise1';", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
