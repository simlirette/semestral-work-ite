"""Run the whole test suite with a single command.

Usage:
    python test_main.py

Discovers every file named test_*.py in the tests/ folder and runs it
with the standard unittest module. Exits with code 1 if any test fails.
"""

import sys
import unittest


def run_all_tests() -> bool:
    """Discover and run all tests in the tests/ folder.

    Returns:
        True if every test passed, False otherwise.
    """
    suite = unittest.defaultTestLoader.discover(start_dir="tests", pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return result.wasSuccessful()


if __name__ == "__main__":
    sys.exit(0 if run_all_tests() else 1)
