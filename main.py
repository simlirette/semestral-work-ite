"""Entry point of the Simulink model generator.

Run with:
    python main.py "y'' + 3y' = u"
    python main.py "2x'' + 0.5x' + 8x = F" --no-gui --name spring
    python main.py "y'' + 3y' = u" --ic "y(0)=1, y'(0)=0.5"

The program reads the equation, asks the user to confirm how it was
understood, then writes a MATLAB script that builds the Simulink
model.
"""

import argparse
import sys
from pathlib import Path

from src.block_model import build_block_model
from src.confirmation import ask_confirmation
from src.matlab_generator import check_model_name, write_script
from src.parser import EquationError, parse_initial_conditions, parse_system

# Shown at the end of "python main.py -h", ready to copy.
EXAMPLES = """examples:
  python main.py "2x'' + 0.5x' + 8x = F" --name spring
  python main.py "y'' + 2y'^3 + y = u"
  python main.py "x'' + 0.5x' + 9.81sin(x) = 0" --ic "x(0)=1" --name pendulum
  python main.py "y''' + 5y'' + 2y' + y + z = u ; z'' + z' + z + y = v"
"""


def build_argument_parser() -> argparse.ArgumentParser:
    """Define the command-line options."""
    # argparse reads what the user typed after "python main.py" and writes the
    # help text by itself. The equation is required, the options start with "--".
    parser = argparse.ArgumentParser(
        description="Generate a reference Simulink model from a differential equation.",
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("equation", help="equation(s) with derivatives written as y', y'', ...; "
                                         "separate several equations with ';'")
    parser.add_argument("--ic", metavar="VALUES",
                        help="initial conditions, like \"y(0)=1, y'(0)=0.5\" (the others are 0)")
    parser.add_argument("--name", default="my_model",
                        help="name of the Simulink model (default: my_model)")
    parser.add_argument("--output", default="output",
                        help="folder where the MATLAB script is written (default: output)")
    parser.add_argument("--no-gui", action="store_true", help="show the equations as text only")
    return parser


def main(arguments=None) -> int:
    """Run the program and return the exit code (0 = success)."""
    # "arguments" is None when run from the terminal: argparse then reads what
    # was typed. It can also be a list, to call main() from Python.
    options = build_argument_parser().parse_args(arguments)
    # Step 1: read everything. Any mistake stops the program with a clear message
    # and exit code 1 (1 = something went wrong, 0 = success).
    try:
        check_model_name(options.name)
        system = parse_system(options.equation)
        conditions = None if options.ic is None else parse_initial_conditions(options.ic, system.orders)
    except (EquationError, ValueError) as error:
        print(f"Error: {error}")
        return 1

    # Step 2: show the equations and ask the user. "n" stops before building anything.
    if not ask_confirmation(system, use_window=not options.no_gui, conditions=conditions):
        print("Stopped. Check how the equation is written and try again.")
        return 1

    # Step 3: build the blocks, then write the MATLAB script with the equation
    # (and the initial conditions) as comments at the top.
    model = build_block_model(system, conditions)
    comments = system.sources + ((f"initial conditions: {options.ic}",) if options.ic else ())
    script = write_script(model, Path(options.output), options.name, comments)
    print(f"\nMATLAB script written: {script}")
    print(f"Run it in MATLAB to create {options.name}.slx in the same folder.")
    return 0


# Only runs when the file is started directly (python main.py), not when
# it is imported by a test.
if __name__ == "__main__":
    sys.exit(main())
