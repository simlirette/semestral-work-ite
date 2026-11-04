"""Describe the Simulink model of a system of equations as blocks and lines.

The model follows the method taught in the course (lectures 1 and 2):

1. one Integrator per derivative order, chained from the highest
   derivative down to the variable itself (ÿ → ẏ → y);
2. one Sum block per equation, whose inputs are the terms of the solved
   equation with a + or − sign (coefficients are positive Gain values,
   the sign is on the Sum);
3. a Gain 1/a after the Sum when the highest derivative has a
   coefficient a, as in ẏ = (0.5u − 3y) / 2;
4. Product, Abs and Fcn blocks for nonlinear terms (ÿ·|ẏ|, ẏ³);
5. a Step block for each input signal and one Scope showing the inputs
   and the unknown variables.

Block parameters use Simulink's own parameter names (``Gain``,
``Inputs``, ``InitialCondition``...), so the MATLAB generator can set
them directly. Nothing here depends on MATLAB.
"""

from dataclasses import dataclass, field

import sympy

from src.parser import (
    ParsedSystem,
    derivative_symbol,
    isolate_equations,
    ordered_terms,
    split_symbol,
)

# Functions drawn with an Fcn block, written in Simulink's Fcn syntax.
_FCN_EXPRESSIONS = {sympy.sin: "sin(u)", sympy.cos: "cos(u)", sympy.exp: "exp(u)"}


@dataclass
class Block:
    """One Simulink block.

    Attributes:
        name: Unique name in the model, for example ``"Gain2"``.
        kind: Block type: Step, Constant, Sum, Gain, Product, Abs, Fcn,
            Integrator or Scope.
        parameters: Simulink parameter names mapped to their values as text.
    """

    name: str
    kind: str
    parameters: dict = field(default_factory=dict)

    def input_count(self) -> int:
        """Number of input ports this block has."""
        if self.kind in ("Step", "Constant"):
            return 0
        if self.kind == "Sum":
            return len(self.parameters["Inputs"])
        if self.kind == "Product":
            return int(self.parameters["Inputs"])
        if self.kind == "Scope":
            return int(self.parameters["NumInputPorts"])
        return 1


@dataclass(frozen=True)
class Line:
    """A connection from an output port to an input port (ports start at 1).

    Attributes:
        source: Name of the block the signal comes from.
        target: Name of the block the signal goes to.
        target_port: Input port number on the target block.
        label: Signal name shown on the line, for example ``"y'"``.
    """

    source: str
    target: str
    target_port: int = 1
    label: str = ""


@dataclass
class BlockModel:
    """A complete Simulink model: its blocks and the lines between them."""

    blocks: list = field(default_factory=list)
    lines: list = field(default_factory=list)

    def block(self, name: str) -> Block:
        """Return the block with the given name."""
        for block in self.blocks:
            if block.name == name:
                return block
        raise KeyError(name)

    def of_kind(self, kind: str) -> list:
        """Return all blocks of one kind, in creation order."""
        return [block for block in self.blocks if block.kind == kind]

    def inputs_of(self, name: str) -> list:
        """Return the lines entering a block, sorted by input port."""
        return sorted((line for line in self.lines if line.target == name),
                      key=lambda line: line.target_port)


def signal_label(name: str, order: int) -> str:
    """Signal name with apostrophes, as written on the course schemes (y'')."""
    return name + "'" * order


def number_text(value) -> str:
    """Write a number for a block parameter: 3, 0.5 or 5/14."""
    value = sympy.nsimplify(value)
    if value.is_Integer:
        return str(value)
    if value.is_Rational:
        denominator = value.q
        for factor in (2, 5):
            while denominator % factor == 0:
                denominator //= factor
        if denominator == 1:
            return f"{float(value):g}"
        return f"{value.p}/{value.q}"
    return str(value)


class _Builder:
    """Creates blocks and lines step by step while walking the equations."""

    def __init__(self, initial_conditions: dict):
        self.model = BlockModel()
        self.variables = []  # variable order of the equation being built
        self.signals = {}   # SymPy symbol -> name of the block producing it
        self.counters = {}
        self.initial_conditions = initial_conditions

    def add(self, kind: str, prefix: str = "", **parameters) -> str:
        """Add a block and return its name (Gain1, Gain2, ... or a given prefix)."""
        base = prefix or kind
        self.counters[base] = self.counters.get(base, 0) + 1
        count = self.counters[base]
        name = base if prefix and count == 1 else f"{base}{count}"
        self.model.blocks.append(Block(name, kind, {k: str(v) for k, v in parameters.items()}))
        return name

    def connect(self, source: str, target: str, port: int = 1, label: str = "") -> None:
        """Add a line from `source` to input `port` of `target`."""
        self.model.lines.append(Line(source, target, port, label))

    def integrator_chain(self, name: str, order: int) -> str:
        """Create the Integrators of one variable and return the first one.

        The first Integrator receives the highest derivative; the last one
        outputs the variable itself.
        """
        previous = None
        first = None
        for k in range(order - 1, -1, -1):
            initial = self.initial_conditions.get((name, k), 0)
            block = self.add("Integrator", f"Integrator {signal_label(name, k)}",
                             InitialCondition=number_text(initial))
            self.signals[derivative_symbol(name, k)] = block
            if previous is not None:
                self.connect(previous, block, label=signal_label(name, k + 1))
            first = first or block
            previous = block
        return first

    def signal(self, expr: sympy.Expr) -> str:
        """Return the block whose output is `expr`, creating blocks as needed."""
        if expr in self.signals:
            return self.signals[expr]
        if isinstance(expr, sympy.Symbol):
            # A variable that is never differentiated is an input signal.
            block = self.add("Step", f"Step {expr.name}")
            self.signals[expr] = block
            return block
        if expr.is_Number:
            return self.add("Constant", Value=number_text(expr))
        if isinstance(expr, sympy.Add):
            # Inside parentheses, positive terms first, as in (ẋ₂ − ẋ₁).
            terms = ordered_terms(expr, self.variables)
            return self.sum(sorted(terms, key=lambda term: term.could_extract_minus_sign()))
        if isinstance(expr, sympy.Mul):
            return self.product(expr)
        if isinstance(expr, sympy.Pow):
            base, exponent = expr.as_base_exp()
            block = self.add("Fcn", Expr=f"u^{number_text(exponent)}" if exponent.is_Integer
                             else f"u^({number_text(exponent)})")
            self.connect(self.signal(base), block)
            return block
        if isinstance(expr, sympy.Abs):
            block = self.add("Abs")
            self.connect(self.signal(expr.args[0]), block)
            return block
        if expr.func in _FCN_EXPRESSIONS:
            block = self.add("Fcn", Expr=_FCN_EXPRESSIONS[expr.func])
            self.connect(self.signal(expr.args[0]), block)
            return block
        raise ValueError(f"No Simulink block for: {expr}")

    def product(self, expr: sympy.Expr) -> str:
        """Blocks for a product: a Gain for the number, a Product for the rest."""
        coefficient, rest = expr.as_coeff_Mul()
        if coefficient != 1:
            if rest == 1:
                return self.add("Constant", Value=number_text(coefficient))
            block = self.add("Gain", Gain=number_text(coefficient))
            self.connect(self.signal(rest), block)
            return block
        factors = sympy.Mul.make_args(rest)
        block = self.add("Product", Inputs=len(factors))
        for port, factor in enumerate(factors, start=1):
            self.connect(self.signal(factor), block, port)
        return block

    def sum(self, terms: tuple) -> str:
        """A Sum block with one input per term; the sign goes on the Sum.

        A single positive term needs no Sum and is returned directly.
        """
        signs, sources = [], []
        for term in terms:
            negative = term.could_extract_minus_sign()
            signs.append("-" if negative else "+")
            sources.append(self.signal(-term if negative else term))
        if signs == ["+"]:
            return sources[0]
        block = self.add("Sum", Inputs="".join(signs))
        for port, source in enumerate(sources, start=1):
            self.connect(source, block, port)
        return block


def build_block_model(system: ParsedSystem, initial_conditions: dict = None) -> BlockModel:
    """Build the integrator-based Simulink model of a system of equations.

    Args:
        system: Parsed equations from :func:`src.parser.parse_system`.
        initial_conditions: Optional values at t = 0, keyed by
            ``(variable, order)``; for example ``{("y", 0): 1, ("y", 1): 0}``
            means y(0) = 1 and ẏ(0) = 0. Missing values are 0.

    Returns:
        The blocks and lines of the model.
    """
    builder = _Builder(initial_conditions or {})
    first_integrator = {name: builder.integrator_chain(name, order)
                        for name, order in system.orders.items()}

    rows = isolate_equations(system)
    highest = {row[0] for row in rows}
    pending = list(rows)
    while pending:
        # Build an equation once the highest derivatives it uses exist.
        for row in pending:
            symbol, numerator, denominator, _ = row
            needed = (numerator.free_symbols & highest) - {symbol}
            if needed <= set(builder.signals):
                break
        pending.remove(row)
        builder.variables = row[3]
        _build_equation(builder, symbol, numerator, denominator, first_integrator)

    scope_signals = [sympy.Symbol(name) for name in system.inputs]
    scope_signals += [derivative_symbol(name, 0) for name in system.orders]
    scope = builder.add("Scope", NumInputPorts=len(scope_signals))
    for port, symbol in enumerate(scope_signals, start=1):
        builder.connect(builder.signal(symbol), scope, port, label=symbol.name)
    return builder.model


def _build_equation(builder, symbol, numerator, denominator, first_integrator) -> None:
    """Blocks for one solved equation, connected to its integrator chain."""
    if denominator.could_extract_minus_sign():
        numerator, denominator = -numerator, -denominator
    name, order = split_symbol(symbol)
    output = builder.sum(ordered_terms(numerator, builder.variables))
    if denominator != 1:
        gain = builder.add("Gain", Gain=f"1/{number_text(denominator)}")
        builder.connect(output, gain)
        output = gain
    builder.signals[symbol] = output
    builder.connect(output, first_integrator[name], label=signal_label(name, order))
