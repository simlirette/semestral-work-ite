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
from sympy.solvers.solveset import NonlinearError


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

# Patterns used to read the text. A pattern (regular expression) describes
# what a piece of text must look like.
# Every character the user is allowed to type.
_ALLOWED_TEXT = re.compile(r"[A-Za-z0-9_'+\-*/^().=;\s]+")
# A name: a letter, then letters, digits or _ (y, x1, u).
_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
# A name followed by apostrophes (y''), to find the derivatives.
_DERIVATIVE = re.compile(r"([A-Za-z][A-Za-z0-9_]*)('+)")
# A name followed by "(" (sin(, abs(), to find the functions.
_FUNCTION_CALL = re.compile(r"([A-Za-z][A-Za-z0-9_]*)\s*\(")
# One initial condition: a name, apostrophes, (0), =, then a value (y'(0)=0.5).
_INITIAL_CONDITION = re.compile(r"\s*([A-Za-z][A-Za-z0-9_]*)('*)\s*\(\s*0\s*\)\s*=\s*(.+?)\s*")
# y'' becomes the symbol y__d2: the name, this mark, then the order.
_DERIVATIVE_MARK = "__d"
# Above this number of equations, isolate_equations would take too long
# to try every matching, so it uses the fully solved form instead.
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
    # One piece of text per equation. Empty pieces (a ";" at the end) are dropped.
    pieces = [piece.strip() for piece in text.split(";")]
    pieces = [piece for piece in pieces if piece]
    if not pieces:
        raise EquationError("No equation was given.")

    # Turn each piece into a SymPy equation, then find the unknowns and the inputs.
    equations = [_parse_equation(piece) for piece in pieces]
    orders, inputs = _classify_variables(equations, text)
    # Stop with a clear message if these equations can't give a model.
    if not orders:
        raise EquationError("No derivative found. Write derivatives with apostrophes, like y'.")
    if len(equations) != len(orders):
        raise EquationError(
            f"{len(equations)} equation(s) for {len(orders)} unknown variable(s) "
            f"({', '.join(orders)}). The counts must be equal."
        )

    # Solve for the highest derivatives. This also refuses equations that
    # can't be solved.
    solved = _solve_for_highest(equations, orders)
    return ParsedSystem(tuple(equations), orders, tuple(inputs), solved, tuple(pieces))


def parse_initial_conditions(text: str, orders: dict) -> dict:
    """Read the starting values of the variables, written like y(0)=1, y'(0)=0.5.

    Each value goes in one Integrator, so a variable of order n can only
    get the values of y, y', ... up to n-1 apostrophes. Values not given
    are 0, like in Simulink.

    Args:
        text: Values separated by commas, for example ``"y(0)=1, y'(0)=-0.5"``.
        orders: The unknown variables with their highest order, as in
            :attr:`ParsedSystem.orders`.

    Returns:
        The values by ``(variable, order)``, for example
        ``{("y", 0): 1, ("y", 1): -1/2}``.

    Raises:
        EquationError: If a value is badly written or has no Integrator.
    """
    values = {}
    # The values are separated by commas: read them one by one.
    for piece in filter(str.strip, text.split(",")):
        # Check the shape y'(0)=value, then take the name, the number of
        # apostrophes (the order) and the value.
        match = _INITIAL_CONDITION.fullmatch(piece)
        if not match:
            raise EquationError(f"Write each initial condition like y(0)=1 or y'(0)=0.5, not: {piece.strip()}")
        name, order, number = match.group(1), len(match.group(2)), match.group(3)
        label = name + "'" * order
        # The value must belong to an unknown, have its own Integrator (an order
        # below the highest one), and be given only once.
        if name not in orders:
            raise EquationError(f"'{name}' is not a variable of the equation(s).")
        if order >= orders[name]:
            last = name + "'" * (orders[name] - 1)
            raise EquationError(f"{label}(0) cannot be set: the last value you can give for {name} is {last}(0).")
        if (name, order) in values:
            raise EquationError(f"{label}(0) is given twice.")
        try:
            # Read the value with SymPy, so 1/3 and -0.5 work too. Anything that isn't
            # a plain number is refused.
            value = parse_expr(number, transformations=_TRANSFORMATIONS)
        except (SyntaxError, TypeError, ValueError):
            value = None
        if value is None or not value.is_number:
            raise EquationError(f"The value of {label}(0) must be a number, not: {number}")
        values[(name, order)] = value
    return values


def _parse_equation(text: str) -> sympy.Eq:
    """Turn the text of one equation into a SymPy equation."""
    # Refuse the characters the program doesn't know, and name them.
    if not _ALLOWED_TEXT.fullmatch(text):
        bad = sorted(set(re.sub(r"[A-Za-z0-9_'+\-*/^().=;\s]", "", text)))
        raise EquationError(f"Unsupported character(s): {' '.join(bad)}")
    # One equation = exactly one "=".
    if text.count("=") != 1:
        raise EquationError(f"Each equation needs exactly one '=': {text}")

    # "(t)" after a variable adds nothing, so it is removed.
    text = text.replace("(t)", "")
    # A name can't contain "__d", because that mark is kept for the derivatives.
    for name in _IDENTIFIER.findall(text):
        if _DERIVATIVE_MARK in name:
            raise EquationError(f"Variable names cannot contain '{_DERIVATIVE_MARK}': {name}")
    # Every function must be one we know (abs, sqrt, exp, sin, cos).
    for name in _FUNCTION_CALL.findall(text):
        if name not in FUNCTIONS:
            raise EquationError(
                f"Unknown function '{name}'. Supported: {', '.join(FUNCTIONS)}. "
                "For a product, write the '*' explicitly, like 3*y*(y+1)."
            )

    # Replace each derivative by its symbol: y'' -> y__d2 (2 = number of apostrophes).
    text = _DERIVATIVE.sub(lambda m: f"{m.group(1)}{_DERIVATIVE_MARK}{len(m.group(2))}", text)
    # An apostrophe left over is not right after a name, like in (y+1)'.
    if "'" in text:
        raise EquationError("An apostrophe must follow a variable name, like y'.")

    # Tell SymPy which names are variables and which are functions,
    # then read each side of "=".
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
    # For each name, keep its highest order (0 if it never has an apostrophe).
    symbols = set().union(*(eq.free_symbols for eq in equations))
    highest = {}
    for symbol in symbols:
        name, order = split_symbol(symbol)
        highest[name] = max(highest.get(name, 0), order)

    # Keep the order in which the user wrote the names. Unknowns have an
    # order above 0, inputs have 0.
    first_seen = list(dict.fromkeys(_IDENTIFIER.findall(text)))
    orders = {name: highest[name] for name in first_seen if highest.get(name, 0) > 0}
    inputs = [name for name in first_seen if name in highest and highest[name] == 0]
    return orders, inputs


def _solve_for_highest(equations: list, orders: dict) -> dict:
    """Solve the equations for the highest derivative of each unknown.

    The equations must be linear in those highest derivatives (as in all
    course examples); they may be nonlinear in everything else.
    """
    # Move everything to one side (left - right = 0), and list the highest
    # derivatives to solve for.
    expressions = [eq.lhs - eq.rhs for eq in equations]
    highest = [derivative_symbol(name, order) for name, order in orders.items()]

    try:
        # Write the equations as a matrix system A·x = b, where x holds the highest
        # derivatives. SymPy refuses it if they aren't linear (y''^2, sin(y'')).
        matrix, constants = sympy.linear_eq_to_matrix(expressions, highest)
    except NonlinearError:
        raise EquationError(
            "The highest derivatives must appear linearly "
            "(not squared, multiplied together or inside a function)."
        ) from None
    # If the determinant of A is 0, there is no single solution.
    if matrix.det() == 0:
        raise EquationError("The equations cannot be solved for the highest derivatives.")

    # One equation: just divide by the coefficient. Several: SymPy solves the system.
    if len(highest) == 1:
        return {name: constants[0] / matrix[0, 0] for name in orders}
    return {name: sympy.simplify(value) for name, value in zip(orders, matrix.LUsolve(constants))}


def variable_order(source: str, system: ParsedSystem) -> list:
    """Unknown variables in the order they first appear in one equation."""
    # The unknowns of this equation first, in the order written, then the others.
    names = [name for name in _IDENTIFIER.findall(source) if name in system.orders]
    return list(dict.fromkeys(names + list(system.orders)))


def ordered_terms(expr: sympy.Expr, variables: list) -> list:
    """Split a sum into terms in the order used in the course.

    Inputs come first, then the terms of each variable (in the order the
    user wrote them) from the highest derivative down, as in
    u − 3ÿ − 2ẏ − y − ż.
    """
    def key(term):
        """Sort key: inputs first, then by variable, highest derivative first."""
        # Find which variables (and which orders) the term contains.
        found = [split_symbol(symbol) for symbol in term.free_symbols]
        found = [(variables.index(n), o) for n, o in found if n in variables]
        # No variable: it's an input or a number, so it comes first.
        if not found:
            return (0, 0, 0)
        # Otherwise: sort by the first variable written, then from the highest
        # derivative down.
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
    # Split the equation into its terms and keep the ones with the target (like ÿ).
    terms = sympy.Add.make_args(expression)
    with_target = sympy.expand(sympy.Add(*[t for t in terms if t.has(target)]))
    # The number in front of the target, like the 3 in 3ÿ.
    coefficient = with_target.coeff(target)
    # Give up if the target is missing, if its coefficient contains another
    # highest derivative, or if the target isn't simply "coefficient × target".
    if coefficient == 0 or coefficient.has(*highest) or sympy.expand(coefficient * target) != with_target:
        return None
    # Every other term goes to the other side of "=", so its sign changes.
    numerator = -sympy.Add(*[t for t in terms if not t.has(target)])
    return numerator, coefficient


def isolate_equations(system: ParsedSystem) -> list:
    """Return how each equation is solved for a highest derivative.

    Each equation is matched with the unknown whose highest derivative it
    is solved for, preferring the variable written first in it. Highest
    derivatives of other variables stay in the result, as in the course:
    ż in ÿ = −5ẏ − y − ż − ẋ (exercise 6). They may even need each other,
    like y⃛ and z⃛ in exercise 12: Simulink solves this "algebraic loop",
    as in the professor's solution. With more than 6 equations, trying
    every matching would be too slow, so the fully solved expressions
    from the parser are used instead.

    Returns:
        A list of ``(highest_symbol, numerator, denominator, variables)``
        tuples, one per equation; ``variables`` gives the term order.
    """
    # For each unknown: its highest derivative. For each equation: everything on
    # one side, and its variables in the order written.
    names = list(system.orders)
    highest = {name: derivative_symbol(name, system.orders[name]) for name in names}
    expressions = [eq.lhs - eq.rhs for eq in system.equations]
    orders = [variable_order(source, system) for source in system.sources]

    # Try every way to match the equations with the unknowns (y with the first
    # equation and z with the second, or the reverse...).
    best = None
    if len(names) <= _MAX_EQUATIONS_TO_MATCH:
        for assignment in itertools.permutations(names):
            rows = [_isolate(e, highest[n], set(highest.values())) for e, n in zip(expressions, assignment)]
            # This matching fails if one equation can't be isolated for its unknown.
            if None in rows:
                continue
            # Score = how many equations are matched with the unknown written first in
            # them. The best score wins: that's how the student would do it on paper.
            score = sum(order[0] == name for order, name in zip(orders, assignment))
            if best is None or score > best[0]:
                best = (score, assignment, rows)

    # Each equation as (highest derivative, top of the fraction, bottom, term order).
    if best is not None:
        _, assignment, rows = best
        return [(highest[n], num, den, order) for n, (num, den), order in zip(assignment, rows, orders)]
    # Backup for more than 6 equations: the fully solved form, divided by 1.
    return [(highest[n], sympy.expand(system.solved[n]), sympy.Integer(1), names) for n in names]
