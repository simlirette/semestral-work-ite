"""Read differential equations written in plain text.

Derivatives are written with apostrophes, as in ``y'' + 3y' = u``.
Several equations are separated by semicolons. The optional ``(t)``
after a variable is accepted and ignored, so ``y''(t) + 3y'(t) = u(t)``
means the same thing.

The parser turns the text into SymPy expressions and solves the
equations for the highest derivative of each unknown variable. That
solved form is exactly what the Simulink model with integrators
implements, following the method taught in the course.

Example:
    >>> system = parse_system("2y'' + 3y' + 2y = u")
    >>> system.orders
    {'y': 2}
"""

import itertools
import re
from dataclasses import dataclass

import sympy
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication,
    parse_expr,
    rationalize,
    standard_transformations,
)


class EquationError(ValueError):
    """Raised when the text cannot be read as a supported equation."""


# Functions the user may write in an equation, mapped to SymPy.
FUNCTIONS = {
    "abs": sympy.Abs,
    "sqrt": sympy.sqrt,
    "exp": sympy.exp,
    "sin": sympy.sin,
    "cos": sympy.cos,
}

_ALLOWED_TEXT = re.compile(r"[A-Za-z0-9_'+\-*/^().=;\s]+")
_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
_DERIVATIVE = re.compile(r"([A-Za-z][A-Za-z0-9_]*)('+)")
_FUNCTION_CALL = re.compile(r"([A-Za-z][A-Za-z0-9_]*)\s*\(")
_DERIVATIVE_MARK = "__d"
_MAX_EQUATIONS_TO_MATCH = 6

# "3y'" means 3*y', "y^3" means y**3, and decimals such as 0.5 are kept
# as exact fractions (1/2) so that no rounding error appears when solving.
_TRANSFORMATIONS = standard_transformations + (implicit_multiplication, convert_xor, rationalize)


@dataclass(frozen=True)
class ParsedSystem:
    """A system of differential equations, read and solved.

    Attributes:
        equations: The equations as the user wrote them (SymPy ``Eq``).
        orders: Each unknown variable mapped to its highest derivative order,
            in order of first appearance.
        inputs: Names of the input signals (variables never differentiated).
        solved: Each unknown variable mapped to the expression of its highest
            derivative, for example ``{'y': u - 3*y__d1}`` for ``y'' + 3y' = u``.
        sources: The text of each equation, used to display terms in the
            order the user wrote the variables.
    """

    equations: tuple
    orders: dict
    inputs: tuple
    solved: dict
    sources: tuple = ()


def derivative_symbol(name: str, order: int) -> sympy.Symbol:
    """Return the SymPy symbol standing for a derivative of a variable.

    Args:
        name: Variable name, for example ``"y"``.
        order: Derivative order; 0 means the variable itself.

    Returns:
        ``y`` for order 0, ``y__d2`` for the second derivative, and so on.
    """
    if order == 0:
        return sympy.Symbol(name)
    return sympy.Symbol(f"{name}{_DERIVATIVE_MARK}{order}")


def split_symbol(symbol: sympy.Symbol) -> tuple:
    """Split a symbol into its variable name and derivative order.

    Args:
        symbol: A symbol produced by the parser, such as ``y__d2``.

    Returns:
        A ``(name, order)`` pair, for example ``("y", 2)``.
    """
    name, mark, order = symbol.name.partition(_DERIVATIVE_MARK)
    return (name, int(order)) if mark else (name, 0)


def parse_system(text: str) -> ParsedSystem:
    """Read one or more equations and solve them for the highest derivatives.

    Args:
        text: Equations separated by semicolons, for example
            ``"y'' + y + z = u ; z' + z = v"``.

    Returns:
        The parsed and solved system.

    Raises:
        EquationError: If the text is not a supported system of equations.
    """
    pieces = [piece.strip() for piece in text.split(";")]
    pieces = [piece for piece in pieces if piece]
    if not pieces:
        raise EquationError("No equation was given.")

    equations = [_parse_equation(piece) for piece in pieces]
    orders, inputs = _classify_variables(equations, text)
    if not orders:
        raise EquationError("No derivative found. Write derivatives with apostrophes, like y'.")
    if len(equations) != len(orders):
        raise EquationError(
            f"{len(equations)} equation(s) for {len(orders)} unknown variable(s) "
            f"({', '.join(orders)}). The counts must be equal."
        )

    solved = _solve_for_highest(equations, orders)
    return ParsedSystem(tuple(equations), orders, tuple(inputs), solved, tuple(pieces))


def _parse_equation(text: str) -> sympy.Eq:
    """Turn the text of one equation into a SymPy equation."""
    if not _ALLOWED_TEXT.fullmatch(text):
        bad = sorted(set(re.sub(r"[A-Za-z0-9_'+\-*/^().=;\s]", "", text)))
        raise EquationError(f"Unsupported character(s): {' '.join(bad)}")
    if text.count("=") != 1:
        raise EquationError(f"Each equation needs exactly one '=': {text}")

    text = text.replace("(t)", "")
    for name in _IDENTIFIER.findall(text):
        if _DERIVATIVE_MARK in name:
            raise EquationError(f"Variable names cannot contain '{_DERIVATIVE_MARK}': {name}")
    for name in _FUNCTION_CALL.findall(text):
        if name not in FUNCTIONS:
            raise EquationError(
                f"Unknown function '{name}'. Supported: {', '.join(FUNCTIONS)}. "
                "For a product, write the '*' explicitly, like 3*y*(y+1)."
            )

    text = _DERIVATIVE.sub(lambda m: f"{m.group(1)}{_DERIVATIVE_MARK}{len(m.group(2))}", text)
    if "'" in text:
        raise EquationError("An apostrophe must follow a variable name, like y'.")

    names = {name: sympy.Symbol(name) for name in _IDENTIFIER.findall(text) if name not in FUNCTIONS}
    local_dict = {**names, **FUNCTIONS}
    left, right = text.split("=")
    try:
        return sympy.Eq(_parse_side(left, local_dict), _parse_side(right, local_dict))
    except (SyntaxError, TypeError, ValueError) as error:
        raise EquationError(f"Could not read the equation: {text}") from error


def _parse_side(text: str, local_dict: dict) -> sympy.Expr:
    """Parse one side of an equation; an empty side is an error."""
    if not text.strip():
        raise EquationError("Both sides of '=' must contain something.")
    return parse_expr(text, local_dict=local_dict, transformations=_TRANSFORMATIONS)


def _classify_variables(equations: list, text: str) -> tuple:
    """Find the unknown variables with their highest order, and the inputs.

    A variable that appears with at least one apostrophe is unknown;
    any other variable is an input signal. Both keep the order in which
    they first appear in the text.
    """
    symbols = set().union(*(eq.free_symbols for eq in equations))
    highest = {}
    for symbol in symbols:
        name, order = split_symbol(symbol)
        highest[name] = max(highest.get(name, 0), order)

    first_seen = list(dict.fromkeys(_IDENTIFIER.findall(text)))
    orders = {name: highest[name] for name in first_seen if highest.get(name, 0) > 0}
    inputs = [name for name in first_seen if name in highest and highest[name] == 0]
    return orders, inputs


def _solve_for_highest(equations: list, orders: dict) -> dict:
    """Solve the equations for the highest derivative of each unknown.

    The equations must be linear in those highest derivatives (as in all
    course examples); they may be nonlinear in everything else.
    """
    expressions = [eq.lhs - eq.rhs for eq in equations]
    highest = [derivative_symbol(name, order) for name, order in orders.items()]

    for expression in expressions:
        for symbol in highest:
            if sympy.diff(expression, symbol).free_symbols & set(highest):
                raise EquationError(
                    "The highest derivatives must appear linearly "
                    "(not squared, multiplied together or inside a function)."
                )

    matrix, constants = sympy.linear_eq_to_matrix(expressions, highest)
    if matrix.det() == 0:
        raise EquationError("The equations cannot be solved for the highest derivatives.")

    if len(highest) == 1:
        solution = [constants[0] / matrix[0, 0]]
    else:
        solution = list(matrix.LUsolve(constants))
    return {name: sympy.simplify(value) if len(highest) > 1 else value
            for name, value in zip(orders, solution)}


def variable_order(source: str, system: ParsedSystem) -> list:
    """Unknown variables in the order they first appear in one equation."""
    names = [name for name in _IDENTIFIER.findall(source) if name in system.orders]
    return list(dict.fromkeys(names + list(system.orders)))


def ordered_terms(expr: sympy.Expr, variables: list) -> list:
    """Split a sum into terms in the order used in the course.

    Inputs come first, then the terms of each variable (in the order the
    user wrote them) from the highest derivative down, as in
    u − 3ÿ − 2ẏ − y − ż.
    """
    def key(term):
        found = [split_symbol(symbol) for symbol in term.free_symbols]
        found = [(variables.index(n), o) for n, o in found if n in variables]
        if not found:
            return (0, 0, 0)
        position = min(index for index, _ in found)
        order = max(o for index, o in found if index == position)
        return (1, position, -order)

    return sorted(sympy.Add.make_args(expr), key=key)


def _isolate(expression: sympy.Expr, target: sympy.Symbol, highest: set):
    """Isolate `target` in ``expression = 0``, as done on paper.

    Returns:
        ``(numerator, denominator)`` such that target = numerator / denominator,
        or None if the target does not appear as ``coefficient * target``.
    """
    terms = sympy.Add.make_args(expression)
    with_target = sympy.expand(sympy.Add(*[t for t in terms if t.has(target)]))
    coefficient = with_target.coeff(target)
    if coefficient == 0 or coefficient.has(*highest) or sympy.expand(coefficient * target) != with_target:
        return None
    numerator = -sympy.Add(*[t for t in terms if not t.has(target)])
    return numerator, coefficient


def _has_loop(dependencies: dict) -> bool:
    """True if the highest derivatives depend on each other in a circle."""
    visiting, done = set(), set()

    def visit(name):
        if name in done:
            return False
        if name in visiting:
            return True
        visiting.add(name)
        if any(visit(other) for other in dependencies[name]):
            return True
        visiting.discard(name)
        done.add(name)
        return False

    return any(visit(name) for name in dependencies)


def isolate_equations(system: ParsedSystem) -> list:
    """Return how each equation is solved for a highest derivative.

    Each equation is matched with the unknown whose highest derivative it
    is solved for, preferring the variable written first in it. Highest
    derivatives of other variables may stay in the result (ż in
    ÿ = −5ẏ − y − ż − ẋ), as in the course, as long as they do not depend
    on each other in a circle. When no such matching exists (exercise 12),
    the fully solved expressions from the parser are used.

    Returns:
        A list of ``(highest_symbol, numerator, denominator, variables)``
        tuples, one per equation; ``variables`` gives the term order.
    """
    names = list(system.orders)
    highest = {name: derivative_symbol(name, system.orders[name]) for name in names}
    expressions = [eq.lhs - eq.rhs for eq in system.equations]
    orders = [variable_order(source, system) for source in system.sources]

    best = None
    if len(names) <= _MAX_EQUATIONS_TO_MATCH:
        for assignment in itertools.permutations(names):
            rows = [_isolate(e, highest[n], set(highest.values())) for e, n in zip(expressions, assignment)]
            if None in rows:
                continue
            dependencies = {
                name: {other for other in names if other != name and row[0].has(highest[other])}
                for name, row in zip(assignment, rows)
            }
            if _has_loop(dependencies):
                continue
            score = sum(order[0] == name for order, name in zip(orders, assignment))
            if best is None or score > best[0]:
                best = (score, assignment, rows)

    if best is not None:
        _, assignment, rows = best
        return [(highest[n], num, den, order) for n, (num, den), order in zip(assignment, rows, orders)]
    return [(highest[n], sympy.expand(system.solved[n]), sympy.Integer(1), names) for n in names]
