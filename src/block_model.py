"""Describe the Simulink model of a system of equations as blocks and lines.

The model follows the method taught in the course (lectures 1 and 2):

1. one Integrator per derivative order, chained from the highest
   derivative down to the variable itself (ÿ → ẏ → y);
2. one Sum block per equation, whose inputs are the terms of the solved
   equation with a + or − sign (coefficients are positive Gain values,
   the sign is on the Sum);
3. a Gain 1/a after the Sum when the highest derivative has a
   coefficient a, as in ẏ = (u/2 − 3y) / 2;
4. Product, Abs and Fcn blocks for nonlinear terms (ÿ·|ẏ|, ẏ³);
5. a Step block for each input signal, and a Scope showing the inputs
   and the variables. As on the solution schemes, a single equation
   sends each signal to its own Scope input (no Mux); in a system, one
   Mux per equation groups its inputs and its variable, for example
   [u, y].

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
            Integrator, Mux or Scope.
        parameters: Simulink parameter names mapped to their values as text.
    """

    name: str
    kind: str
    parameters: dict = field(default_factory=dict)

    def input_count(self) -> int:
        """Number of input ports this block has."""
        # Sources have no input. A Sum has one input per sign ("+--" = 3),
        # Product, Mux and Scope have the number given, everything else has 1.
        if self.kind in ("Step", "Constant"):
            return 0
        if self.kind == "Sum":
            return len(self.parameters["Inputs"])
        if self.kind in ("Product", "Mux"):
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
    # y and 2 give y''. Used for block names and wire labels.
    return name + "'" * order


def number_text(value) -> str:
    """Write a number for a block parameter: 3, -2 or 1/2.

    Fractions always stay fractions, so 0.5 is written 1/2.
    """
    # nsimplify turns 0.5 into the exact fraction 1/2, then str writes it as text.
    return str(sympy.nsimplify(value))


class _Builder:
    """Creates blocks and lines step by step while walking the equations."""

    def __init__(self, initial_conditions: dict):
        """Start an empty model; `initial_conditions` are the values by (variable, order)."""
        self.model = BlockModel()
        self.variables = []  # variable order of the equation being built
        self.signals = {}   # SymPy symbol -> name of the block producing it
        # How many blocks of each kind exist, to number the next one (Gain1, Gain2...).
        self.counters = {}
        self.initial_conditions = initial_conditions

    def add(self, kind: str, prefix: str = "", **parameters) -> str:
        """Add a block and return its name (Gain1, Gain2, ... or a given prefix)."""
        # A block gets the given prefix ("Integrator y'") or its kind ("Gain"),
        # followed by a number. The first block with a prefix keeps the prefix alone.
        base = prefix or kind
        self.counters[base] = self.counters.get(base, 0) + 1
        count = self.counters[base]
        name = base if prefix and count == 1 else f"{base}{count}"
        # Simulink expects every parameter as text, so they are all turned into text.
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
        # From the top down: for y''', the Integrators output y'', then y', then y.
        for k in range(order - 1, -1, -1):
            # Its starting value: the one the user gave with --ic, or 0.
            initial = self.initial_conditions.get((name, k), 0)
            block = self.add("Integrator", f"Integrator {signal_label(name, k)}",
                             InitialCondition=number_text(initial))
            # Remember which block outputs this signal, so it can be reused later.
            self.signals[derivative_symbol(name, k)] = block
            # Chain it to the Integrator above it: y'' -> [Integrator] -> y' -> [Integrator] -> y.
            if previous is not None:
                self.connect(previous, block, label=signal_label(name, k + 1))
            first = first or block
            previous = block
        return first

    def signal(self, expr: sympy.Expr) -> str:
        """Return the block whose output is `expr`, creating blocks as needed."""
        # This function calls itself on the smaller pieces of a term, until each
        # piece is a signal that already exists (y, y', u...).
        # Already built (like y, from its Integrator): reuse that block.
        if expr in self.signals:
            return self.signals[expr]
        if isinstance(expr, sympy.Symbol):
            # A variable that is never differentiated is an input signal.
            block = self.add("Step", f"Step {expr.name}")
            self.signals[expr] = block
            return block
        # A number alone, like the 30 in exercise 9.
        if expr.is_Number:
            return self.add("Constant", Value=number_text(expr))
        if isinstance(expr, sympy.Add):
            # Inside parentheses, positive terms first, as in (ẋ₂ − ẋ₁).
            terms = ordered_terms(expr, self.variables)
            return self.sum(sorted(terms, key=lambda term: term.could_extract_minus_sign()))
        # A product, like 3*y' or y''*abs(y').
        if isinstance(expr, sympy.Mul):
            return self.product(expr)
        # A power, like y'^3: an Fcn block that computes u^3 on its input.
        if isinstance(expr, sympy.Pow):
            base, exponent = expr.as_base_exp()
            block = self.add("Fcn", Expr=f"u^{number_text(exponent)}" if exponent.is_Integer
                             else f"u^({number_text(exponent)})")
            self.connect(self.signal(base), block)
            return block
        # abs(...): an Abs block.
        if isinstance(expr, sympy.Abs):
            block = self.add("Abs")
            self.connect(self.signal(expr.args[0]), block)
            return block
        # sin, cos or exp: an Fcn block.
        if expr.func in _FCN_EXPRESSIONS:
            block = self.add("Fcn", Expr=_FCN_EXPRESSIONS[expr.func])
            self.connect(self.signal(expr.args[0]), block)
            return block
        # Should never happen: the parser only accepts what is handled above.
        raise ValueError(f"No Simulink block for: {expr}")

    def product(self, expr: sympy.Expr) -> str:
        """Blocks for a product: a Gain for the number, a Product for the rest."""
        # Split the number from the rest: 3*y' gives 3 and y'.
        coefficient, rest = expr.as_coeff_Mul()
        if coefficient != 1:
            # Only a number is left (rare): a Constant block.
            if rest == 1:
                return self.add("Constant", Value=number_text(coefficient))
            # A number times something: a Gain block on that something.
            block = self.add("Gain", Gain=number_text(coefficient))
            self.connect(self.signal(rest), block)
            return block
        # No number: a Product block, with one input per factor.
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
        # The course puts the sign on the Sum, not in the Gain: -3y' becomes
        # a "-" input fed by a Gain 3.
        for term in terms:
            negative = term.could_extract_minus_sign()
            signs.append("-" if negative else "+")
            sources.append(self.signal(-term if negative else term))
        # One positive term alone needs no Sum.
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
    # 1. The Integrator chains first, because almost every term needs them.
    builder = _Builder(initial_conditions or {})
    first_integrator = {name: builder.integrator_chain(name, order)
                        for name, order in system.orders.items()}

    # 2. Each equation, isolated like on paper (see parser.isolate_equations).
    rows = isolate_equations(system)
    # An equation may use the highest derivative of another one before that
    # one is built (z⃛ in the equation of y, exercise 12). Its wire starts
    # from a placeholder, replaced at the end by the block that outputs it.
    highest = [row[0] for row in rows]
    builder.signals.update({symbol: f"<{symbol}>" for symbol in highest})
    # 3. One Sum per equation.
    for symbol, numerator, denominator, variables in rows:
        builder.variables = variables
        _build_equation(builder, symbol, numerator, denominator, first_integrator)
    # Now every equation is built: replace each placeholder by the real block.
    output = {f"<{symbol}>": builder.signals[symbol] for symbol in highest}
    builder.model.lines = [Line(output.get(line.source, line.source), line.target, line.target_port, line.label)
                           for line in builder.model.lines]

    # 4. The Scope at the end.
    _add_scope(builder, system, rows)
    return builder.model


def _add_scope(builder, system, rows) -> None:
    """Connect the inputs and variables to a Scope, as on the course schemes.

    A single equation needs no Mux: each signal (u, then y) gets its own
    Scope input. In a system, one Mux per equation groups [inputs,
    variable]; each input is shown with the first equation that uses it,
    and an equation without an input of its own skips the Mux.
    """
    # Which inputs each equation shows: the inputs it uses, each input only once.
    inputs_of = {}
    shown = set()
    for symbol, numerator, _, _ in rows:
        name = split_symbol(symbol)[0]
        used = [i for i in system.inputs if sympy.Symbol(i) in numerator.free_symbols and i not in shown]
        shown.update(used)
        inputs_of[name] = used
    # An input used by no equation still goes with the first variable.
    first = next(iter(system.orders))
    inputs_of[first] = [i for i in system.inputs if i not in shown] + inputs_of[first]

    # One group per equation: [its inputs..., its variable], like [u, y].
    groups = [[sympy.Symbol(i) for i in inputs_of[name]] + [derivative_symbol(name, 0)]
              for name in system.orders]
    # One equation: no Mux, each signal on its own Scope input, like the professor.
    if len(groups) == 1:
        groups = [[symbol] for symbol in groups[0]]
    scope = builder.add("Scope", NumInputPorts=len(groups))
    for port, group in enumerate(groups, start=1):
        # A group of one signal goes straight to the Scope. Bigger groups go through a Mux.
        if len(group) == 1:
            builder.connect(builder.signal(group[0]), scope, port, label=group[0].name)
            continue
        mux = builder.add("Mux", Inputs=len(group))
        for mux_port, symbol in enumerate(group, start=1):
            builder.connect(builder.signal(symbol), mux, mux_port, label=symbol.name)
        builder.connect(mux, scope, port)


def _build_equation(builder, symbol, numerator, denominator, first_integrator) -> None:
    """Blocks for one solved equation, connected to its integrator chain."""
    # Keep the bottom of the fraction positive: -a/-3 becomes a/3.
    if denominator.could_extract_minus_sign():
        numerator, denominator = -numerator, -denominator
    name, order = split_symbol(symbol)
    # The Sum of the top of the fraction, terms in class order.
    output = builder.sum(ordered_terms(numerator, builder.variables))
    # 3y'' = ... needs a Gain 1/3 after the Sum.
    if denominator != 1:
        gain = builder.add("Gain", Gain=f"1/{number_text(denominator)}")
        builder.connect(output, gain)
        output = gain
    # The output is the highest derivative: remember it, and feed it into the
    # first Integrator of the chain.
    builder.signals[symbol] = output
    builder.connect(output, first_integrator[name], label=signal_label(name, order))
