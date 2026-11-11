"""Write the MATLAB script that builds a block model in Simulink.

The generated script uses the commands from the lecture "Controlling
Simulink from Matlab command line": ``new_system``, ``add_block``,
``add_line`` and ``set_param``. Every block is given a position computed
by :mod:`src.layout`, so the canvas looks like the course schemes, and
the model is saved as an ``.slx`` file next to the script.

Running the script requires MATLAB with Simulink; generating it does not.
"""

import re
from pathlib import Path

from src.block_model import BlockModel
from src.layout import compute_layout

# Simulink library path of each block kind.
LIBRARY = {
    "Step": "simulink/Sources/Step",
    "Constant": "simulink/Sources/Constant",
    "Sum": "simulink/Math Operations/Sum",
    "Gain": "simulink/Math Operations/Gain",
    "Product": "simulink/Math Operations/Product",
    "Abs": "simulink/Math Operations/Abs",
    "Fcn": "simulink/User-Defined Functions/Fcn",
    "Integrator": "simulink/Continuous/Integrator",
    "Mux": "simulink/Signal Routing/Mux",
    "Scope": "simulink/Sinks/Scope",
}

_MODEL_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,59}")


def matlab_string(text: str) -> str:
    """Quote text as a MATLAB character vector ('' stands for one apostrophe)."""
    return "'" + text.replace("'", "''") + "'"


def check_model_name(name: str) -> None:
    """Raise ValueError if `name` cannot be used as a Simulink model name.

    A model name must start with a letter and contain only letters,
    digits and underscores (like a MATLAB variable name).
    """
    if not _MODEL_NAME.fullmatch(name):
        raise ValueError(
            f"Invalid model name '{name}': use letters, digits and '_', starting with a letter."
        )


def _block_parameters(kind: str, parameters: dict, slots=None) -> dict:
    """Adapt block parameters to Simulink.

    Sum blocks are round, as in the course. For a main Sum, the signs are
    written in the slot order chosen by the layout, with ``|`` for an
    empty slot. Mux blocks are drawn as a thin bar.
    """
    if kind == "Sum":
        signs = parameters["Inputs"]
        if slots:
            return {"IconShape": "round",
                    "Inputs": "".join("|" if port is None else signs[port - 1] for port in slots)}
        return {"IconShape": "round", "Inputs": "|" + signs}
    if kind == "Mux":
        return {"Inputs": parameters["Inputs"], "DisplayOption": "bar"}
    return dict(parameters)


def _number(value) -> str:
    """Write a coordinate for MATLAB."""
    return "NaN" if value is None else f"{value:g}"


def _route_call(line, port: int, route) -> str:
    """MATLAB call drawing one line along its computed path."""
    moves = "; ".join(f"{axis} {_number(value)}" for axis, value in route.moves)
    moves = f"[{moves}]" if moves else "zeros(0, 2)"
    return (f"route(model, {matlab_string(line.source)}, {matlab_string(line.target)}, {port}, "
            f"{_number(route.tap_x)}, {moves})")


# Local function appended to every script: draws a line through the given
# points and falls back on automatic routing if Simulink cannot connect it.
_ROUTE_FUNCTION = """
function h = route(model, source, target, port, tapX, moves)
% Draw a line from the output of SOURCE to input PORT of TARGET.
% The line starts at the output port, or branches off the source's
% first line at x = tapX. MOVES lists [axis value] rows: axis 1 sets x,
% axis 2 sets y. If the line cannot be connected, Simulink routes it.
    sourceHandle = get_param([model '/' source], 'Handle');
    sourcePorts = get_param(sourceHandle, 'PortHandles');
    targetPorts = get_param([model '/' target], 'PortHandles');
    a = get_param(sourcePorts.Outport(1), 'Position');
    b = get_param(targetPorts.Inport(port), 'Position');
    if ~isnan(tapX)
        a(1) = tapX;
    end
    points = a;
    for k = 1:size(moves, 1)
        p = points(end, :);
        p(moves(k, 1)) = moves(k, 2);
        points(end + 1, :) = p; %#ok<AGROW>
    end
    p = points(end, :);
    if p(1) ~= b(1) && p(2) ~= b(2)
        points(end + 1, :) = [p(1) b(2)];
    end
    points(end + 1, :) = b;
    h = -1;
    try
        h = add_line(model, points);
        connected = get_param(targetPorts.Inport(port), 'Line');
        ok = connected ~= -1 && get_param(connected, 'SrcBlockHandle') == sourceHandle;
    catch
        ok = false;
    end
    if ~ok
        if h ~= -1 && ishandle(h)
            delete_line(h);
        end
        h = add_line(model, [source '/1'], [target '/' num2str(port)], 'autorouting', 'smart');
    end
end
"""


def generate_script(model: BlockModel, model_name: str = "reference_model",
                    equations: tuple = (), stop_time: float = 100) -> str:
    """Return the text of a MATLAB script that builds `model` in Simulink.

    Args:
        model: Blocks and lines from :func:`src.block_model.build_block_model`.
        model_name: Name of the Simulink model (and of the saved .slx file).
        equations: Equation texts written as comments at the top of the script.
        stop_time: Simulation stop time in seconds.

    Returns:
        The script as a string.
    """
    check_model_name(model_name)
    name = matlab_string(model_name)
    layout = compute_layout(model)
    out = [f"% Builds the Simulink model '{model_name}'.",
           "% Generated by the Simulink reference generator (semestral-work-ite)."]
    out += [f"%   {text}" for text in equations]
    out += [
        "",
        f"model = {name};",
        "if bdIsLoaded(model)",
        "    close_system(model, 0);",
        "end",
        "new_system(model);",
        "",
        "% Blocks",
    ]
    for block in model.blocks:
        arguments = [matlab_string(LIBRARY[block.kind]), f"[model '/' {matlab_string(block.name)}]"]
        slots = layout.sum_slots.get(block.name)
        for key, value in _block_parameters(block.kind, block.parameters, slots).items():
            arguments += [matlab_string(key), matlab_string(value)]
        position = " ".join(str(value) for value in layout.positions[block.name])
        arguments += ["'Position'", f"[{position}]"]
        if block.name in layout.facing_left:
            arguments += ["'Orientation'", "'left'"]
        out.append(f"add_block({', '.join(arguments)});")

    # Lines starting at a port first, then branches (which start on those
    # lines), then the short lines left to Simulink's automatic routing.
    phases = {1: [], 2: [], 3: []}
    for index, line in enumerate(model.lines):
        route = layout.routes.get(index)
        phase = 3 if route is None else (1 if route.tap_x is None else 2)
        phases[phase].append((line, route))
    titles = {1: "% Lines from output ports", 2: "% Branch lines",
              3: "% Lines routed by Simulink"}

    labelled = set()
    for phase in (1, 2, 3):
        if not phases[phase]:
            continue
        out += ["", titles[phase]]
        for line, route in phases[phase]:
            port = line.target_port
            if line.target in layout.port_order:
                port = layout.port_order[line.target].index(port) + 1
            if route is None:
                command = (f"add_line(model, {matlab_string(f'{line.source}/1')}, "
                           f"{matlab_string(f'{line.target}/{port}')}, 'autorouting', 'smart')")
            else:
                command = _route_call(line, port, route)
            # A signal is named once, even when it branches to several blocks.
            if line.label and line.source not in labelled:
                labelled.add(line.source)
                out.append(f"h = {command};")
                out.append(f"set_param(h, 'Name', {matlab_string(line.label)});")
            else:
                out.append(f"{command};")

    out += [
        "",
        "% Simulation time, save and open",
        f"set_param(model, 'StopTime', {matlab_string(f'{stop_time:g}')});",
        "save_system(model, fullfile(fileparts(mfilename('fullpath')), model));",
        "open_system(model);",
        _ROUTE_FUNCTION,
    ]
    return "\n".join(out)


def write_script(model: BlockModel, folder: Path, model_name: str = "reference_model",
                 equations: tuple = (), stop_time: float = 100) -> Path:
    """Write the script ``build_<model_name>.m`` into `folder` and return its path."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"build_{model_name}.m"
    path.write_text(generate_script(model, model_name, equations, stop_time), encoding="utf-8")
    return path
