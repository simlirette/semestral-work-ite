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
        return _join_terms(ordered_terms(_decimals(expr), variables), printer)

    interpreted = []
    for equation, source in zip(system.equations, system.sources):
        variables = variable_order(source, system)
        interpreted.append(f"{side(equation.lhs, variables)} = {side(equation.rhs, variables)}")

    solved = []
    for symbol, numerator, denominator, variables in isolate_equations(system):
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
