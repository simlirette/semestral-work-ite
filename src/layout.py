"""Place the blocks and draw the wires of a model, as in the course schemes.

The rules come from the solution schemes of the exercises:

* each equation gets a horizontal band, stacked from top to bottom;
* the main row of a band holds the input Step, the Sum, the optional
  1/a Gain and the chain of Integrators, from left to right;
* every feedback term gets its own row under the main row; its blocks
  (Gains, Products...) face left because the signal flows back to the Sum;
* feedback loops are nested: the further right a wire leaves the chain,
  the deeper its row and the further left it climbs back to the Sum,
  so the loops never cross each other;
* wires between two equations use the space between their bands;
* the wire from each Step to its Mux goes around the band, above it or
  below it, on the side that is free;
* the Sum and Mux inputs are ordered to match where each wire arrives.

Every wire gets an exact path, given as a list of moves (go to x, go to
y) from its start point. The MATLAB script turns these paths into lines
and falls back on Simulink's automatic routing if a path cannot be drawn.

Positions are in Simulink pixels: ``(left, top, right, bottom)``.
"""

from dataclasses import dataclass, field

from src.block_model import BlockModel

MARGIN = 40
COLUMN = 110      # horizontal distance between main-row blocks
ROW = 50          # vertical distance between feedback rows
PAD = 22          # space around groups of wires
LANE = 12         # distance between parallel horizontal wires
LANE_X = 10       # distance between parallel vertical wires
TAP = 10          # distance between branch points on one wire
TREE_STEP = 70    # horizontal distance between blocks of one feedback term
MUX_PORT = 20     # distance between two inputs of a Mux
SCOPE_PORT = 30   # distance between two inputs of the Scope
X, Y = 1, 2       # axes of a move

SIZES = {
    "Step": (30, 30), "Constant": (30, 30), "Sum": (26, 26), "Gain": (40, 34),
    "Product": (30, 34), "Abs": (30, 30), "Fcn": (70, 30), "Integrator": (34, 34),
}


@dataclass
class Route:
    """The path of one wire.

    Attributes:
        tap_x: None if the wire starts at its block's output port;
            otherwise the wire branches off the block's first wire at this x.
        moves: Successive moves ``(axis, value)``: ``(1, 120)`` goes to
            x = 120, ``(2, 300)`` goes to y = 300. The last corner and the
            end at the input port are added automatically.
    """

    tap_x: float = None
    moves: list = field(default_factory=list)


@dataclass
class Layout:
    """Result of the layout.

    Attributes:
        positions: Block name mapped to ``(left, top, right, bottom)``.
        facing_left: Names of the blocks drawn facing left (feedback blocks).
        port_order: For Sum and Mux blocks, the original input ports in
            their new order from top to bottom, for example ``[3, 1, 2]``.
        sum_slots: For main Sum blocks, the input positions around the
            circle from top to bottom: an original port number, or None for
            an empty slot. Empty slots keep the Step input on the left side.
        routes: Index of a line in ``model.lines`` mapped to its Route.
            Lines without a route are drawn by Simulink's automatic routing.
    """

    positions: dict
    facing_left: set
    port_order: dict
    routes: dict
    sum_slots: dict = field(default_factory=dict)


@dataclass
class _Band:
    """One equation: its main-row blocks and the terms of its Sum."""

    chain: list
    terms: list
    step: str = None                        # Step on the main row
    rows: dict = field(default_factory=dict)  # own term -> first row
    row_count: int = 0
    from_above: list = field(default_factory=list)
    from_below: list = field(default_factory=list)
    main_y: float = 0
    top_lane: float = None
    bottom_lane: float = None
    lane_x: dict = field(default_factory=dict)  # Sum input port -> x of its vertical wire


def _size(model: BlockModel, name: str) -> tuple:
    """Width and height of a block on the canvas."""
    block = model.block(name)
    if block.kind == "Scope":
        return 34, max(40, SCOPE_PORT * block.input_count())
    if block.kind == "Mux":
        return 6, MUX_PORT * block.input_count()
    return SIZES[block.kind]


def _sources(model: BlockModel, name: str) -> list:
    """Blocks connected to the inputs of a block, by input port."""
    return [line.source for line in model.inputs_of(name)]


def _bands(model: BlockModel) -> list:
    """Find the main row (Sum, 1/a Gain, Integrators) of each equation."""
    integrators = [b.name for b in model.of_kind("Integrator")]
    next_integrator = {}
    for line in model.lines:
        if line.source in integrators and line.target in integrators:
            next_integrator[line.source] = line.target
    heads = [name for name in integrators
             if model.block(_sources(model, name)[0]).kind != "Integrator"]

    bands = []
    for head in heads:
        chain = [head]
        while chain[-1] in next_integrator:
            chain.append(next_integrator[chain[-1]])
        feeder = _sources(model, head)[0]
        block = model.block(feeder)
        if block.kind == "Gain" and block.parameters["Gain"].startswith("1/"):
            chain.insert(0, feeder)
            feeder = _sources(model, feeder)[0]
            block = model.block(feeder)
        if block.kind in ("Step", "Integrator"):
            bands.append(_Band(chain, [feeder]))
        else:
            chain.insert(0, feeder)
            bands.append(_Band(chain, _sources(model, feeder)))
    return bands


def _rows(model, name, leaves) -> int:
    """Rows used by a feedback term: one, plus one per extra branch."""
    branches = [s for s in _sources(model, name) if s not in leaves]
    if not branches:
        return 1
    return _rows(model, branches[0], leaves) + sum(_rows(model, s, leaves) for s in branches[1:])


def _depth(model, name, leaves) -> int:
    """Number of blocks on the longest path from a term back to a leaf."""
    branches = [s for s in _sources(model, name) if s not in leaves]
    return 1 + max((_depth(model, s, leaves) for s in branches), default=0)


def _tree_leaves(model, name, leaves) -> list:
    """All leaf blocks (Integrators, Steps...) that feed a feedback term."""
    found = []
    for source in _sources(model, name):
        found += [source] if source in leaves else _tree_leaves(model, source, leaves)
    return found


def compute_layout(model: BlockModel) -> Layout:
    """Compute block positions, input orders and wire paths for a model.

    Args:
        model: Blocks and lines from :func:`src.block_model.build_block_model`.

    Returns:
        The complete layout.
    """
    return _Layouter(model).run()


class _Layouter:
    """Carries out the layout step by step."""

    def __init__(self, model: BlockModel):
        self.model = model
        self.bands = _bands(model)
        self.band_of = {name: i for i, band in enumerate(self.bands) for name in band.chain}
        self.steps = [b.name for b in model.of_kind("Step")]
        self.leaves = set(self.band_of) | set(self.steps)
        self.positions = {}
        self.centres = {}
        self.facing_left = set()
        self.port_order = {}
        self.sum_slots = {}
        self.routes = {}

    def run(self) -> Layout:
        """Run every step and return the layout."""
        self.classify_terms()
        self.place_vertically()
        self.place_horizontally()
        self.order_inputs()
        self.route_wires()
        return Layout(self.positions, self.facing_left, self.port_order, self.routes, self.sum_slots)

    # ------------------------------------------------------------ helpers

    def place(self, name, x, y):
        """Centre a block at (x, y)."""
        width, height = _size(self.model, name)
        self.centres[name] = (x, y)
        self.positions[name] = (round(x - width / 2), round(y - height / 2),
                                round(x + width / 2), round(y + height / 2))

    def chain_index(self, name):
        """Position of a block in its band's main row (-1 if not on a main row)."""
        if name not in self.band_of:
            return -1
        return self.bands[self.band_of[name]].chain.index(name)

    def is_sum(self, band):
        return self.model.block(band.chain[0]).kind == "Sum"

    # ------------------------------------------------------------ steps

    def classify_terms(self):
        """Sort the terms of each Sum: Step, own feedback, other equations."""
        for b, band in enumerate(self.bands):
            own = []
            for source in band.terms:
                if source in self.steps:
                    if band.step is None and self.is_sum(band):
                        band.step = source
                elif source in self.band_of and self.band_of[source] != b:
                    other = self.band_of[source]
                    if other == b - 1:
                        band.from_above.append(source)
                    elif other == b + 1:
                        band.from_below.append(source)
                elif source in self.band_of or source not in self.leaves:
                    own.append(source)

            def leaf_rank(term):
                leaves = [term] if term in self.leaves else _tree_leaves(self.model, term, self.leaves)
                return max((self.chain_index(l) for l in leaves if self.band_of.get(l) == b), default=-1)

            row = 1
            for term in sorted(own, key=leaf_rank):
                band.rows[term] = row
                row += 1 if term in self.leaves else _rows(self.model, term, self.leaves)
            band.row_count = row - 1
            band.from_above.sort(key=self.chain_index, reverse=True)
            band.from_below.sort(key=self.chain_index)

    def step_side(self, b):
        """Route the Step-to-Mux wire above the band if that side is free."""
        band = self.bands[b]
        wires_up = b > 0 and self.bands[b - 1].from_below
        wires_down = b + 1 < len(self.bands) and self.bands[b + 1].from_above
        if not band.from_above and not wires_up:
            return "above"
        if not band.from_below and not wires_down:
            return "below"
        return "above"

    def place_vertically(self):
        """Choose the y of each main row, feedback row and wire lane."""
        self.gap_lane = {}  # (source, target Sum) -> y of the lane between bands
        y = MARGIN
        for b, band in enumerate(self.bands):
            side = self.step_side(b) if band.step and self.mux_of(b) else None
            if side == "above":
                band.top_lane = y + 10
                band.main_y = band.top_lane + PAD + 20
            else:
                band.main_y = y + 30
            bottom = band.main_y + ROW * band.row_count + 25
            if side == "below":
                band.bottom_lane = bottom
                bottom += 10
            y = bottom
            if b + 1 < len(self.bands):
                below = self.bands[b + 1]
                lanes = [(s, below.chain[0]) for s in sorted(below.from_above, key=self.chain_index)]
                lanes += [(s, band.chain[0]) for s in sorted(band.from_below, key=self.chain_index,
                                                            reverse=True)]
                for i, key in enumerate(lanes):
                    self.gap_lane[key] = y + PAD + LANE * i
                y += 2 * PAD + LANE * max(len(lanes) - 1, 0)
            y += 10

    def mux_of(self, b):
        """The Mux (or Scope) that shows the variable of band b."""
        last = self.bands[b].chain[-1]
        for line in self.model.lines:
            if line.source == last and self.model.block(line.target).kind in ("Mux", "Scope"):
                return line.target
        return None

    def place_horizontally(self):
        """Choose the x of every block and place them."""
        groups = [max(len(band.from_above), len(band.from_below) + len(band.rows))
                  for band in self.bands] or [0]
        step_right = MARGIN + 15
        self.step_tap = step_right + TAP
        sum_left = self.step_tap + 24 + LANE_X * max(groups)
        sum_x = sum_left + 13

        for band in self.bands:
            for column, name in enumerate(band.chain):
                self.place(name, sum_x + column * COLUMN, band.main_y)
            if band.step and band.step not in self.centres:
                self.place(band.step, MARGIN, band.main_y)
        for step in self.steps:
            if step not in self.centres:
                self.place(step, MARGIN, self.bands[0].main_y - 60 if self.bands else MARGIN)

        # Feedback terms on their rows, facing left.
        for b, band in enumerate(self.bands):
            for term, row in band.rows.items():
                if term in self.leaves:
                    continue
                leaves = [l for l in _tree_leaves(self.model, term, self.leaves)
                          if self.band_of.get(l) == b]
                depth = _depth(self.model, term, self.leaves)
                if leaves:
                    right = max(self.positions[l][2] for l in leaves)
                    x = right - 18 - TREE_STEP * (depth - 1)
                else:
                    x = sum_x + 2 * COLUMN
                self.place_tree(term, max(x, sum_x + 40), band.main_y, row)

        # Muxes after the longest main row, then the Scope.
        rightmost = max(right for _, _, right, _ in self.positions.values())
        self.mux_lane = rightmost + 60
        for mux in self.model.of_kind("Mux"):
            self.place(mux.name, self.mux_lane + 18, 0)  # y set in order_inputs
        mux_right = self.mux_lane + 21
        self.scope_lane = {}
        for scope in self.model.of_kind("Scope"):
            sources = _sources(self.model, scope.name)
            for i, source in enumerate(sources):
                self.scope_lane[source] = mux_right + 20 + LANE_X * i
            x = mux_right + 20 + LANE_X * len(sources) + 25
            first, last = self.bands[0].main_y, self.bands[-1].main_y
            self.place(scope.name, x, (first + last) / 2)

    def place_tree(self, name, x, main_y, row) -> int:
        """Place a feedback term and its inputs; return the last row used."""
        self.place(name, x, main_y + ROW * row)
        self.facing_left.add(name)
        last = row
        first = True
        for source in _sources(self.model, name):
            if source in self.leaves:
                continue
            start = row if first else last + 1
            last = self.place_tree(source, x + TREE_STEP, main_y, start)
            first = False
        return last

    def order_inputs(self):
        """Order Sum inputs by where their wire arrives; align the Muxes."""
        for b, band in enumerate(self.bands):
            main = band.chain[0]
            if self.is_sum(band):
                ports = {source: port for port, source in enumerate(band.terms, start=1)}
                top = [ports[s] for s in band.from_above]
                below = [ports[s] for s in band.from_below]
                below += [ports[t] for t, _ in sorted(band.rows.items(), key=lambda item: -item[1])]
                middle = [ports[band.step]] if band.step else []
                rest = [p for p in ports.values() if p not in top + below + middle]
                below = rest + below
                # Empty slots make the groups above and below the Step the same
                # size, so the Step input sits on the left of the circle.
                size = max(len(top), len(below))
                slots = [None] * (size - len(top)) + top + (middle or [None])
                slots += below + [None] * (size - len(below))
                self.sum_slots[main] = slots
                self.port_order[main] = [p for p in slots if p is not None]
                sum_left = self.positions[main][0]
                for i, port in enumerate(top):
                    band.lane_x[port] = sum_left - 14 - LANE_X * i
                for j, port in enumerate(reversed(below)):
                    band.lane_x[port] = sum_left - 14 - LANE_X * j

            mux = self.mux_of(b)
            if mux and self.model.block(mux).kind == "Mux":
                count = self.model.block(mux).input_count()
                order = list(range(1, count + 1))
                if self.step_side(b) == "below" and band.step:
                    order = [count] + order[:-1]   # the variable first, the Step under it
                self.port_order[mux] = order
                variable_port = order.index(count) + 1
                top = band.main_y - MUX_PORT * (variable_port - 0.5)
                self.place(mux, self.mux_lane + 18, top + MUX_PORT * count / 2)

    def route_wires(self):
        """Give every wire a path when the rules of the course schemes apply."""
        tapped = {}  # source -> list of (key, line index, moves)
        for index, line in enumerate(self.model.lines):
            route = self.route_of(line)
            if route is None:
                continue
            kind, payload = route
            if kind == "port":
                self.routes[index] = Route(None, payload)
            else:
                key, moves = payload
                tapped.setdefault(line.source, []).append((key, index, moves))

        for source, wires in tapped.items():
            start = self.positions[source][2] if source not in self.facing_left else None
            limit = self.tap_limit(source)
            if start is None or limit is None:
                continue
            wires.sort()
            spacing = min(TAP, (limit - start) / (len(wires) + 1))
            for i, (_, index, moves) in enumerate(wires, start=1):
                self.routes[index] = Route(round(start + spacing * i), moves)

    def tap_limit(self, source):
        """Right end of the part of a block's first wire where branches may start."""
        if source in self.steps:
            band = next((b for b in self.bands if b.step == source), None)
            if band is None:
                return None
            return min(list(band.lane_x.values()) + [self.positions[band.chain[0]][0] - 6]) - 4
        if source in self.band_of:
            chain = self.bands[self.band_of[source]].chain
            i = chain.index(source)
            if i + 1 < len(chain):
                return self.positions[chain[i + 1]][0] - 6
            target = self.mux_of(self.band_of[source])
            if target and self.model.block(target).kind == "Mux":
                return self.mux_lane - 6
            return self.scope_lane.get(source, self.mux_lane) - 6
        return None

    def route_of(self, line):
        """Path of one wire: ("port", moves), ("tap", (key, moves)) or None."""
        source, target = line.source, line.target
        target_kind = self.model.block(target).kind

        # Main rows: straight wires along the chain.
        if source in self.band_of and target in self.band_of:
            chain = self.bands[self.band_of[source]].chain
            if self.band_of[source] == self.band_of[target] and \
                    chain.index(target) == chain.index(source) + 1:
                return "port", []

        # Wires into a main Sum.
        for b, band in enumerate(self.bands):
            if target != band.chain[0] or not self.is_sum(band) or line.target_port not in \
                    [p for p in range(1, len(band.terms) + 1)]:
                continue
            port = line.target_port
            if source == band.step:
                return "port", [(X, self.positions[target][0] - 6)]
            lane_x = band.lane_x.get(port)
            if lane_x is None:
                return None
            if source in band.rows and source not in self.leaves:
                return "port", [(X, lane_x)]
            if source in band.rows:
                row_y = band.main_y + ROW * band.rows[source]
                return "tap", ((0, row_y), [(Y, row_y), (X, lane_x)])
            if source in band.from_above or source in band.from_below:
                lane_y = self.gap_lane[(source, target)]
                key = (0, lane_y) if source in band.from_above else (1, -lane_y)
                return "tap", (key, [(Y, lane_y), (X, lane_x)])
            return None

        # A main-row signal feeding a block of a feedback term (under it, on the left).
        if target in self.facing_left and source in self.band_of:
            target_y = self.centres[target][1]
            if self.positions[target][2] < self.positions[source][2] + TAP:
                return "tap", ((0, target_y), [])
            return None

        # Feedback blocks of one term: automatic routing (short wires).
        if source in self.facing_left:
            return None

        # Variables, Muxes and the Scope.
        if target_kind == "Mux":
            b = next((i for i, band in enumerate(self.bands) if self.mux_of(i) == target), None)
            if b is None:
                return None
            band = self.bands[b]
            if source == band.chain[-1]:
                return "port", []
            if source == band.step:
                lane_y = band.top_lane if band.top_lane is not None else band.bottom_lane
                if lane_y is None:
                    return None
                return "tap", ((2, 0), [(Y, lane_y), (X, self.mux_lane)])
            return None
        if target_kind == "Scope" and source in self.scope_lane:
            return "port", [(X, self.scope_lane[source])]
        return None
