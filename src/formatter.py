"""Write parsed equations in mathematical notation for the user to check.

Two outputs are produced from the same equations:

* LaTeX text, drawn by matplotlib in a window that looks like an
  equation in Word (the user never sees or types the LaTeX itself);
* plain text, printed in the terminal.

Notation follows the course: dots above the variable up to the third
derivative, then the order as a superscript in parentheses, y⁽⁴⁾.
The solved form isolates the highest derivative of each equation the
way it is done on paper, for example ẏ(t) = (0.5u(t) − 3y(t)) / 2.
"""

import itertools
import re

import sympy
from sympy.printing.latex import LatexPrinter
from sympy.printing.str import StrPrinter

from src.parser import ParsedSystem, derivative_symbol, split_symbol

_LATEX_DOTS = {1: r"\dot", 2: r"\ddot", 3: r"\dddot"}
_TEXT_DOTS = {1: "̇", 2: "̈", 3: "⃛"}  # combining dots above
_SUPERSCRIPT = str.maketrans("0123456789()", "⁰¹²³⁴⁵⁶⁷⁸⁹⁽⁾")
_SUBSCRIPT = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")
_NAME_PARTS = re.compile(r"([A-Za-z]+?)_?(\d*)$")
_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
_MAX_EQUATIONS_TO_MATCH = 6


# ---------------------------------------------------------------- notation

def _base_and_index(name: str) -> tuple:
    """Split ``x1`` or ``x_1`` into the letter part and the subscript."""
    match = _NAME_PARTS.match(name)
    return (match.group(1), match.group(2)) if match else (name, "")


def derivative_latex(name: str, order: int) -> str:
    """Return the LaTeX notation of a derivative, without ``(t)``.

    Args:
        name: Variable name, for example ``"y"`` or ``"x1"``.
        order: Derivative order, 0 for the variable itself.

    Returns:
        For example ``\\ddot{y}`` for y'' or ``y^{(4)}`` for y''''.
    """
    base, index = _base_and_index(name)
    subscript = f"_{{{index}}}" if index else ""
    if order == 0:
        return f"{base}{subscript}"
    if order in _LATEX_DOTS:
        return f"{_LATEX_DOTS[order]}{{{base}}}{subscript}"
    return f"{base}{subscript}^{{({order})}}"


def derivative_text(name: str, order: int) -> str:
    """Return the plain-text (Unicode) notation of a derivative, without ``(t)``.

    Args:
        name: Variable name, for example ``"y"`` or ``"x1"``.
        order: Derivative order, 0 for the variable itself.

    Returns:
        For example ``ÿ`` for y'', ``x₁`` for x1, or ``y⁽⁴⁾`` for y''''.
    """
    base, index = _base_and_index(name)
    subscript = index.translate(_SUBSCRIPT)
    if order == 0:
        return f"{base}{subscript}"
    if order in _TEXT_DOTS:
        return f"{base}{_TEXT_DOTS[order]}{subscript}"
    return f"{base}{subscript}{f'({order})'.translate(_SUPERSCRIPT)}"


# ---------------------------------------------------------------- printers

def _decimals(expr: sympy.Expr) -> sympy.Expr:
    """Show fractions such as 1/2 as 0.5 when they have a short decimal form."""
    replacements = {}
    for number in expr.atoms(sympy.Rational):
        if number.q != 1 and _is_short_decimal(number.q):
            replacements[number] = sympy.Float(number, 15)
    return expr.xreplace(replacements)


def _is_short_decimal(denominator: int) -> bool:
    """True if 1/denominator has a finite decimal form (only factors 2 and 5)."""
    for factor in (2, 5):
        while denominator % factor == 0:
            denominator //= factor
    return denominator == 1


def _join_terms(terms: list, printer) -> str:
    """Join terms with + and − signs, writing 0 for an empty sum."""
    if not terms:
        return "0"
    pieces = []
    for position, term in enumerate(terms):
        negative = term.could_extract_minus_sign()
        body = printer._print(-term if negative else term)
        if position == 0:
            pieces.append(f"-{body}" if negative else body)
        else:
            pieces.append(f" - {body}" if negative else f" + {body}")
    return "".join(pieces)


class _TimeSignalMixin:
    """Printer behaviour shared by the LaTeX and plain-text printers.

    Every variable is printed as a signal of time, ``y(t)``; the exponent
    of a power goes before ``(t)`` (ẏ³(t) rather than ẏ(t)³); floats have
    no trailing zeros; and inside parentheses positive terms come first,
    as in (ẋ₂ − ẋ₁).
    """

    def _print_Symbol(self, expr):
        return f"{self._name(expr)}(t)"

    def _print_Float(self, expr):
        return f"{float(expr):g}"

    def _print_Pow(self, expr):
        base, exponent = expr.as_base_exp()
        if isinstance(base, sympy.Symbol) and exponent.is_Integer and exponent > 0:
            return self._power(self._name(base), exponent)
        return super()._print_Pow(expr)

    def _print_Add(self, expr, order=None):
        terms = sorted(expr.args, key=lambda term: term.could_extract_minus_sign())
        return _join_terms(terms, self)


class _Latex(_TimeSignalMixin, LatexPrinter):
    """LaTeX printer for time signals."""

    def _name(self, symbol):
        return derivative_latex(*split_symbol(symbol))

    def _power(self, name, exponent):
        return f"{name}^{{{exponent}}}(t)"


class _Text(_TimeSignalMixin, StrPrinter):
    """Plain-text printer for time signals."""

    def _name(self, symbol):
        return derivative_text(*split_symbol(symbol))

    def _power(self, name, exponent):
        return f"{name}{str(exponent).translate(_SUPERSCRIPT)}(t)"

    def _print_Abs(self, expr):
        return f"|{self._print(expr.args[0])}|"


def _tidy_text(text: str) -> str:
    """Drop the '*' after a number (3ẏ) and show other products with '·'."""
    return re.sub(r"(?<=[0-9.])\*", "", text).replace("*", "·")


# ---------------------------------------------------------------- ordering

def _variable_order(source: str, system: ParsedSystem) -> list:
    """Unknown variables in the order they first appear in one equation."""
    names = [name for name in _IDENTIFIER.findall(source) if name in system.orders]
    return list(dict.fromkeys(names + list(system.orders)))


def _ordered_terms(expr: sympy.Expr, variables: list) -> list:
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


# ---------------------------------------------------------------- isolation

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


def isolations(system: ParsedSystem) -> list:
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
    orders = [_variable_order(source, system) for source in system.sources]

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


# ---------------------------------------------------------------- output

def equation_lines(system: ParsedSystem, printer_type: str) -> tuple:
    """Return the interpreted and solved equations as printable lines.

    Args:
        system: A parsed system from :func:`src.parser.parse_system`.
        printer_type: ``"latex"`` or ``"text"``.

    Returns:
        A pair ``(interpreted, solved)`` of lists of strings, one string
        per equation.
    """
    printer = _Latex() if printer_type == "latex" else _Text()

    def side(expr, variables):
        return _join_terms(_ordered_terms(_decimals(expr), variables), printer)

    interpreted = []
    for equation, source in zip(system.equations, system.sources):
        variables = _variable_order(source, system)
        interpreted.append(f"{side(equation.lhs, variables)} = {side(equation.rhs, variables)}")

    solved = []
    for symbol, numerator, denominator, variables in isolations(system):
        left = printer._print(symbol)
        top = side(numerator, variables)
        bottom = printer._print(_decimals(denominator))
        if denominator == 1:
            solved.append(f"{left} = {top}")
        elif printer_type == "latex":
            solved.append(rf"{left} = \dfrac{{{top}}}{{{bottom}}}")
        else:
            bottom = bottom if denominator.is_Atom else f"({bottom})"
            solved.append(f"{left} = ({top}) / {bottom}")

    if printer_type == "text":
        interpreted = [_tidy_text(line) for line in interpreted]
        solved = [_tidy_text(line) for line in solved]
    return interpreted, solved


def to_latex(system: ParsedSystem) -> tuple:
    """Return the interpreted and solved equations as LaTeX strings."""
    return equation_lines(system, "latex")


def to_text(system: ParsedSystem) -> tuple:
    """Return the interpreted and solved equations as plain Unicode text."""
    return equation_lines(system, "text")
