"""Entry point of the Simulink reference generator.

Run with:
    python main.py "y'' + 3y' = u"
    python main.py "y'' + 3y' = u" --no-gui

For now the program reads the equation and asks the user to confirm
how it was understood. Building the Simulink model comes next.
"""

import argparse
import sys

from src.confirmation import ask_confirmation
from src.parser import EquationError, parse_system

EXAMPLES = """examples:
  python main.py "y'' + 3y' = u"
  python main.py "5y''' + 10y'' + 10y' + 2y = u"
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
    parser.add_argument("--no-gui", action="store_true", help="show the equations as text only")
    return parser


def main(arguments=None) -> int:
    """Run the program and return the exit code (0 = success)."""
    options = build_argument_parser().parse_args(arguments)
    try:
        system = parse_system(options.equation)
    except EquationError as error:
        print(f"Error: {error}")
        return 1

    if not ask_confirmation(system, use_window=not options.no_gui):
        print("Stopped. Check how the equation is written and try again.")
        return 1
    print("Equation confirmed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
