# Simulink Reference Generator

Turns a differential equation written as plain text into a reference Simulink model, so a student can check the model they built by hand.

> Work in progress: version 1.0 is not released yet. The solution plot, initial conditions on the command line and the test documentation are still to come.

## Purpose

In a Simulink course, students convert differential equations into block diagrams (integrators, gains, sums). This program does the same conversion automatically, following the method taught in the course:

1. isolate the highest derivative of each equation;
2. chain one Integrator per derivative order (ÿ → ẏ → y);
3. feed every term back into a Sum block with its sign, through Gain, Product, Abs or power blocks;
4. show each equation's input and variable on a Scope, through a Mux.

The student solves the exercise first, then generates the reference model and compares the two canvases and their simulation results.

**Target audience:** students of a "Simulations in MATLAB/Simulink" course, and teachers preparing solutions.

## Installation

Requires Python 3.10 or newer. Running the generated script requires MATLAB with Simulink (generating it does not).

```bash
git clone https://github.com/simlirette/semestral-work-ite.git
cd semestral-work-ite
pip install -r requirements.txt
```

Dependencies: [SymPy](https://www.sympy.org) (reads and solves the equations) and [matplotlib](https://matplotlib.org) (shows the equations for confirmation).

## Usage

```bash
python main.py "EQUATION" [--name NAME] [--output FOLDER] [--no-gui]
```

| Option | Meaning | Default |
|---|---|---|
| `EQUATION` | The equation(s), in quotes | (required) |
| `--name` | Name of the Simulink model and of the `.slx` file | `reference_model` |
| `--output` | Folder where the MATLAB script is written | `output` |
| `--no-gui` | Show the equations as text only, without a window | off |

### Writing the equation

| Write | Meaning |
|---|---|
| `y'`, `y''`, `y'''`, `y''''` | first, second, third, fourth derivative of y |
| `3y'` or `3*y'` | product with a number |
| `y'^3` | power |
| `abs(y')`, `sqrt(y)`, `sin(y)`, `cos(y)`, `exp(y)` | functions |
| `;` | separates the equations of a system |
| `u`, `v`, `F`... | any variable without an apostrophe is an input (a Step block) |

Writing `(t)` after a variable is allowed and ignored: `y''(t) + 3y'(t) = u(t)` is the same as `y'' + 3y' = u`.

### Examples

```bash
python main.py "y'' + 3y' = u"                                         # exercise 1
python main.py "5y''' + 10y'' + 10y' + 2y = u" --name exercise10       # leading coefficient
python main.py "y'' + 2y'^3 + y = u" --name exercise2                  # nonlinear
python main.py "y''' + 5y'' + 2y' + y + z = u ; z'' + z' + z + y = v"  # system (exercise 3)
```

### What happens

1. The program shows how it understood the equation, in mathematical notation (dots for derivatives, y⁽⁴⁾ from the fourth order), and the equation solved for the highest derivative:

   ```
   Interpreted equation:
       3ÿ(t) + ẏ(t) + 2y(t) = u(t)

   Solved for the highest derivative:
       ÿ(t) = (u(t) - ẏ(t) - 2y(t)) / 3

   Is this what you meant? [y/n]:
   ```

   The same equations are also drawn in a small window, typeset like in Word.

2. After `y`, it writes the MATLAB script `output/build_<name>.m`.
3. Run that script in MATLAB: it builds the model, opens it and saves `<name>.slx` next to the script. Press Run and open the Scope to see the results.

If the equation cannot be read (missing `=`, unknown function, more unknowns than equations...), the program prints the reason and stops.

## Running the tests

```bash
python test_main.py
```

All tests are in the `tests/` folder and run without MATLAB.

## Project structure

```
src/
  parser.py            text → equations, solved for the highest derivatives
  formatter.py         equations → mathematical notation (window and terminal)
  confirmation.py      shows the equations and asks the user to confirm
  block_model.py       equations → Simulink blocks and connections
  layout.py            positions of the blocks and paths of the wires
  matlab_generator.py  blocks → MATLAB script
tests/                 one test file per module
main.py                command-line program
test_main.py           runs all tests
```

## Limitations

- Each equation must be solvable for its highest derivative, and that derivative must appear linearly (not squared or inside a function).
- Coefficients must be numbers: `m*x'' + k*x = F` treats m and k as signals, not parameters.
- An integral on the right-hand side (exercise 4 of the course) is not supported.
- Physical models with saturation, Goto/From blocks or subsystems (water tanks) are not generated.
- Only the integrator scheme is generated; the transfer function scheme is planned.
- The layout follows the course schemes, but coupled systems (for example exercises 6, 7 and 12) can still have crossing wires.
- All initial conditions are 0, and inputs are Step blocks with Simulink's default settings.

## License

MIT, see [LICENSE](LICENSE).
