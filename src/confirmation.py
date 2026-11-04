"""Show the interpreted equations and ask the user to confirm them.

The equations are always printed in the terminal. When possible, they
are also drawn in a small matplotlib window with a white background,
so they look like equations typeset in Word. The user then answers
y or n in the terminal.
"""

from src.formatter import to_latex, to_text
from src.parser import ParsedSystem

_FONT_SIZE = 20
_TITLE_SIZE = 11
_MARGIN = 0.3  # inches


def _titles(count: int) -> tuple:
    """Section titles, singular or plural depending on the number of equations."""
    if count == 1:
        return "Interpreted equation", "Solved for the highest derivative"
    return "Interpreted equations", "Solved for the highest derivatives"


def print_equations(system: ParsedSystem) -> None:
    """Print the interpreted and solved equations in the terminal."""
    interpreted, solved = to_text(system)
    first, second = _titles(len(interpreted))
    print(f"\n{first}:")
    for line in interpreted:
        print(f"    {line}")
    print(f"\n{second}:")
    for line in solved:
        print(f"    {line}")
    print()


def open_window(system: ParsedSystem):
    """Draw the equations in a matplotlib window and return the figure.

    The window stays open (without blocking the program) until the
    returned figure is closed.
    """
    import matplotlib.pyplot as plt

    plt.rcParams["mathtext.fontset"] = "stix"
    interpreted, solved = to_latex(system)
    first, second = _titles(len(interpreted))

    rows = [("title", first)] + [("math", line) for line in interpreted]
    rows += [("title", second)] + [("math", line) for line in solved]

    def height(kind, text):
        if kind == "title":
            return 0.45
        return 1.0 if r"\dfrac" in text else 0.6

    total = sum(height(kind, text) for kind, text in rows) + 2 * _MARGIN
    figure = plt.figure(figsize=(8, total), facecolor="white")
    if figure.canvas.manager is not None:
        figure.canvas.manager.set_window_title("Check the equation")

    top = total - _MARGIN
    texts = []
    for kind, text in rows:
        step = height(kind, text)
        if kind == "title":
            artist = figure.text(_MARGIN / 2, top - step / 2, text, fontsize=_TITLE_SIZE,
                                 color="#555555", va="center", transform=figure.dpi_scale_trans)
        else:
            artist = figure.text(_MARGIN, top - step / 2, f"${text}$", fontsize=_FONT_SIZE,
                                 color="black", va="center", transform=figure.dpi_scale_trans)
        texts.append(artist)
        top -= step

    # Widen the window to fit the longest equation.
    renderer = figure.canvas.get_renderer()
    widest = max(artist.get_window_extent(renderer).width for artist in texts) / figure.dpi
    figure.set_size_inches(max(4.0, widest + 2 * _MARGIN), total)

    plt.show(block=False)
    plt.pause(0.1)
    return figure


def ask_confirmation(system: ParsedSystem, use_window: bool = True, ask=input) -> bool:
    """Show the equations and ask whether they were understood correctly.

    Args:
        system: The parsed equations.
        use_window: Also draw the equations in a window (default True).
            If the window cannot be opened, the text version is enough.
        ask: Function used to read the answer; ``input`` by default
            (tests replace it to simulate the user).

    Returns:
        True if the user answered yes, False if no.
    """
    print_equations(system)
    figure = None
    if use_window:
        try:
            figure = open_window(system)
        except Exception:  # no display, missing GUI toolkit, ...
            print("(The equation window could not be opened; check the text above.)\n")

    try:
        while True:
            answer = ask("Is this what you meant? [y/n]: ").strip().lower()
            if answer in ("y", "yes"):
                return True
            if answer in ("n", "no"):
                return False
            print("Please answer y or n.")
    finally:
        if figure is not None:
            import matplotlib.pyplot as plt
            plt.close(figure)
