"""Write parsed equations in mathematical notation for the user to check.

Two outputs are produced from the same equations:

* LaTeX text, drawn by matplotlib in a window that looks like an
  equation in Word (the user never sees or types the LaTeX itself);
* plain text, printed in the terminal.

Notation follows the course: dots above the variable up to the third
derivative, then the order as a superscript in parentheses, y⁽⁴⁾.
The solved form isolates the highest derivative of each equation the
way it is done on paper, for example ẏ(t) = (u(t)/2 − 3y(t)) / 2.
Fractions always stay fractions: 0.5 is shown as 1/2.
"""

import re

import sympy
from sympy.printing.latex import LatexPrinter
from sympy.printing.str import StrPrinter

from src.parser import ParsedSystem, isolate_equations, ordered_terms, split_symbol, variable_order

_LATEX_DOTS = {1: r"\dot", 2: r"\ddot", 3: r"\dddot"}
_TEXT_DOTS = {1: "̇", 2: "̈", 3: "⃛"}  # combining dots above
_SUPERSCRIPT = str.maketrans("0123456789()", "⁰¹²³⁴⁵⁶⁷⁸⁹⁽⁾")
_SUBSCRIPT = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")
_NAME_PARTS = re.compile(r"([A-Za-z]+?)_?(\d*)$")


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
    of a power goes before ``(t)`` (ẏ³(t) rather than ẏ(t)³); and inside
    parentheses positive terms come first, as in (ẋ₂ − ẋ₁).
    """

    def _print_Symbol(self, expr):
        return f"{self._name(expr)}(t)"

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
        return _join_terms(ordered_terms(expr, variables), printer)

    interpreted = []
    for equation, source in zip(system.equations, system.sources):
        variables = variable_order(source, system)
        interpreted.append(f"{side(equation.lhs, variables)} = {side(equation.rhs, variables)}")

    solved = []
    for symbol, numerator, denominator, variables in isolate_equations(system):
        left = printer._print(symbol)
        top = side(numerator, variables)
        bottom = printer._print(denominator)
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


def initial_condition_lines(system: ParsedSystem, conditions: dict, printer_type: str) -> list:
    """Return the starting values of each variable, one line per variable.

    Every Integrator is listed, so the user sees the values not given too
    (they are 0). For y'' + 3y' = u with y(0)=1, the text line is
    ``y(0) = 1, ẏ(0) = 0``.

    Args:
        system: A parsed system from :func:`src.parser.parse_system`.
        conditions: Values by ``(variable, order)``, from
            :func:`src.parser.parse_initial_conditions`.
        printer_type: ``"latex"`` or ``"text"``.
    """
    printer = _Latex() if printer_type == "latex" else _Text()
    name_of = derivative_latex if printer_type == "latex" else derivative_text
    separator = r",\quad " if printer_type == "latex" else ", "

    def value(name, k):
        number = sympy.sympify(conditions.get((name, k), 0))
        return f"{name_of(name, k)}(0) = {printer._print(number)}"

    return [separator.join(value(name, k) for k in range(order)) for name, order in system.orders.items()]
