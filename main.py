"""Entry point of the Simulink reference generator.

Run with:
    python main.py "y'' + 3y' = u"
    python main.py "y'' + 3y' = u" --no-gui --name exercise1

The program reads the equation, asks the user to confirm how it was
understood, then writes a MATLAB script that builds the reference
Simulink model.
"""

import argparse
import sys
from pathlib import Path

from src.block_model import build_block_model
from src.confirmation import ask_confirmation
from src.matlab_generator import check_model_name, write_script
from src.parser import EquationError, parse_system

EXAMPLES = """examples:
  python main.py "y'' + 3y' = u"
  python main.py "5y''' + 10y'' + 10y' + 2y = u" --name exercise10
  python main.py "y'' + 2y'^3 + y = u"
  python main.py "y''' + 5y'' + 2y' + y + z = u ; z'' + z' + z + y = v"
"""


def build_argument_parser() -> argparse.ArgumentParser:
    """Define the command-line options."""
    parser = argparse.ArgumentParser(
        description="Generate a reference Simulink model from a differential equation.",
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("equation", help="equation(s) with derivatives written as y', y'', ...; "
                                         "separate several equations with ';'")
    parser.add_argument("--name", default="reference_model",
                        help="name of the Simulink model (default: reference_model)")
    parser.add_argument("--output", default="output",
                        help="folder where the MATLAB script is written (default: output)")
    parser.add_argument("--no-gui", action="store_true", help="show the equations as text only")
    return parser


def main(arguments=None) -> int:
    """Run the program and return the exit code (0 = success)."""
    options = build_argument_parser().parse_args(arguments)
    try:
        check_model_name(options.name)
        system = parse_system(options.equation)
    except (EquationError, ValueError) as error:
        print(f"Error: {error}")
        return 1

    if not ask_confirmation(system, use_window=not options.no_gui):
        print("Stopped. Check how the equation is written and try again.")
        return 1

    model = build_block_model(system)
    script = write_script(model, Path(options.output), options.name, system.sources)
    print(f"\nMATLAB script written: {script}")
    print(f"Run it in MATLAB to create {options.name}.slx in the same folder.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
