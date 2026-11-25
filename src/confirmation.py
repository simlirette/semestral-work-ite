"""Show the interpreted equations and ask the user to confirm them.

The equations are always printed in the terminal. When possible, they
are also drawn in a small matplotlib window with a white background,
so they look like equations typeset in Word. The user then answers
y or n in the terminal.
"""

from src.formatter import initial_condition_lines, to_latex, to_text
from src.parser import ParsedSystem

# Sizes of the window text: equations, titles, and the empty border around them.
_FONT_SIZE = 20
_TITLE_SIZE = 11
_MARGIN = 0.3  # inches


def _sections(system: ParsedSystem, conditions, printer_type: str) -> list:
    """Return the parts to show, as (title, lines) pairs.

    The equations as understood, the equations solved for the highest
    derivative, and the initial conditions if the user gave some.
    """
    interpreted, solved = to_latex(system) if printer_type == "latex" else to_text(system)
    # "Interpreted equation" for one equation, "Interpreted equations" for several.
    plural = "s" if len(interpreted) > 1 else ""
    sections = [(f"Interpreted equation{plural}", interpreted),
                (f"Solved for the highest derivative{plural}", solved)]
    if conditions is not None:
        sections.append(("Initial conditions", initial_condition_lines(system, conditions, printer_type)))
    return sections


def print_equations(system: ParsedSystem, conditions: dict = None) -> None:
    """Print the equations (and the initial conditions, if given) in the terminal."""
    for title, lines in _sections(system, conditions, "text"):
        print(f"\n{title}:")
        for line in lines:
            print(f"    {line}")
    print()


def open_window(system: ParsedSystem, conditions: dict = None):
    """Draw the equations in a matplotlib window and return the figure.

    The window stays open (without blocking the program) until the
    returned figure is closed.
    """
    import matplotlib.pyplot as plt

    # matplotlib can draw LaTeX by itself, without installing LaTeX.
    # The "stix" font makes it look like an equation in Word.
    plt.rcParams["mathtext.fontset"] = "stix"

    # Each row: (text, x, height, style). Titles are small and grey;
    # equations are drawn by matplotlib's math renderer.
    title = dict(fontsize=_TITLE_SIZE, color="#555555")
    math = dict(fontsize=_FONT_SIZE, color="black")
    rows = []
    for heading, lines in _sections(system, conditions, "latex"):
        rows.append((heading, _MARGIN / 2, 0.45, title))
        # The $...$ tells matplotlib the text is math. A fraction needs a taller row.
        rows += [(f"${line}$", _MARGIN, 1.0 if r"\dfrac" in line else 0.6, math) for line in lines]

    # The window is as tall as all its rows, plus a border above and below.
    total = sum(row[2] for row in rows) + 2 * _MARGIN
    figure = plt.figure(figsize=(8, total), facecolor="white")
    if figure.canvas.manager is not None:
        figure.canvas.manager.set_window_title("Check the equation")

    # Write the rows from the top down. Positions are in inches from the
    # bottom-left corner of the window.
    top = total - _MARGIN
    texts = []
    for text, x, height, style in rows:
        texts.append(figure.text(x, top - height / 2, text, va="center",
                                 transform=figure.dpi_scale_trans, **style))
        top -= height

    # Widen the window to fit the longest equation.
    renderer = figure.canvas.get_renderer()
    widest = max(artist.get_window_extent(renderer).width for artist in texts) / figure.dpi
    figure.set_size_inches(max(4.0, widest + 2 * _MARGIN), total)

    # Open the window without stopping the program, so the terminal can ask
    # the question while the window is visible.
    plt.show(block=False)
    plt.pause(0.1)
    return figure


def ask_confirmation(system: ParsedSystem, use_window: bool = True, ask=input,
                     conditions: dict = None) -> bool:
    """Show the equations and ask whether they were understood correctly.

    Args:
        system: The parsed equations.
        use_window: Also draw the equations in a window (default True).
            If the window cannot be opened, the text version is enough.
        ask: Function used to read the answer; ``input`` by default
            (tests replace it to simulate the user).
        conditions: Initial conditions given by the user, from
            :func:`src.parser.parse_initial_conditions`; None if none
            were given (they are then not shown).

    Returns:
        True if the user answered yes, False if no.
    """
    # The terminal text is always shown. The window comes on top of it.
    print_equations(system, conditions)
    figure = None
    if use_window:
        try:
            figure = open_window(system, conditions)
        # If the window can't open (no screen, for example), the text is enough,
        # so the program goes on instead of crashing.
        except Exception:  # no display, missing GUI toolkit, ...
            print("(The equation window could not be opened; check the text above.)\n")

    try:
        # Ask again until the answer is y/yes or n/no.
        while True:
            answer = ask("Is this what you meant? [y/n]: ").strip().lower()
            if answer in ("y", "yes"):
                return True
            if answer in ("n", "no"):
                return False
            print("Please answer y or n.")
    # "finally" runs in every case, even after a return: the window is
    # always closed once the user has answered.
    finally:
        if figure is not None:
            import matplotlib.pyplot as plt
            plt.close(figure)
