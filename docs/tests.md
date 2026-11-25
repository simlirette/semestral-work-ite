# Tests

## How to run them

```bash
python test_main.py
```

This runs all 82 tests in the `tests/` folder. None of them needs MATLAB.

## How I test the program

The program works in steps, and each step has its own file in `src/` and its own test file in `tests/`. If a test fails, I know right away which step is broken.

```
text → parser → formatter / confirmation → block_model → matlab_generator → .m script
```

**The expected answers are known in advance.** The tests use solved Simulink exercises: for each equation, the solved form and the Simulink model are already known. If the program gives the same result, it is right. They cover the cases a user meets: linear and nonlinear equations, a number in front of the highest derivative, and systems of 2 or 3 equations.

**Wrong inputs are tested too.** When an equation is badly written, the program must stop and say why. It must never build a wrong model without telling you.

**MATLAB is not needed.** The tests check the text of the MATLAB script, not the model itself. The model is checked by hand in MATLAB (see [Tests done by hand](#tests-done-by-hand)).

## What each test file checks

| File | Tests | What it checks |
|---|---|---|
| `test_parser.py` | 27 | The equation is read and solved correctly. Wrong equations and wrong initial conditions are refused. |
| `test_formatter.py` | 17 | The equations are written in math notation: dots for derivatives, y⁽⁴⁾ from the 4th one, fractions. |
| `test_confirmation.py` | 6 | The question "Is this what you meant?" works with yes, no and wrong answers. |
| `test_block_model.py` | 17 | The model has the expected blocks, and every block is connected. |
| `test_matlab_generator.py` | 15 | The MATLAB script has one `add_block` per block, one `add_line` per wire, and valid MATLAB text. |

## Examples of inputs and outputs

### Equation → solved equation (shown to the user)

| Input | Output |
|---|---|
| `y'' + 3y' = u` | ÿ(t) = u(t) − 3ẏ(t) |
| `3y'' + y' + 2y = u` (number in front of y'') | ÿ(t) = (u(t) − ẏ(t) − 2y(t)) / 3 |
| `y'' + 2y'^3 + y = u` (power) | ÿ(t) = u(t) − 2ẏ³(t) − y(t) |
| `y''' + 3y''*abs(y') + 0.5y' + y'^2*y = u` (abs and products) | y⃛(t) = u(t) − 3ÿ(t)·\|ẏ(t)\| − ẏ(t)/2 − y(t)·ẏ²(t) |
| `y''' + 5y'' + 2y' + y + z = u ; z'' + z' + z + y = v` (2 equations) | y⃛(t) = u(t) − 5ÿ(t) − 2ẏ(t) − y(t) − z(t)<br>z̈(t) = v(t) − ż(t) − z(t) − y(t) |

### Equation → Simulink blocks

| Input | Blocks in the model |
|---|---|
| `y'' + 3y' = u` | 2 Integrators, 1 Gain (3), 1 Sum (+ −), 1 Step, 1 Scope |
| `3y'' + y' + 2y = u` | 2 Integrators, 2 Gains (2 and 1/3), 1 Sum (+ − −), 1 Step, 1 Scope |
| `y'' + 2y'^3 + y = u` | 2 Integrators, 1 Fcn (u^3), 1 Gain (2), 1 Sum (+ − −), 1 Step, 1 Scope |
| `y''' + 3y''*abs(y') + 0.5y' + y'^2*y = u` | 3 Integrators, 1 Abs, 2 Products, 1 Fcn (u^2), 2 Gains, 1 Sum (+ − − −), 1 Step, 1 Scope |
| `y''' + 5y'' + 2y' + y + z = u ; z'' + z' + z + y = v` | 5 Integrators, 2 Gains, 2 Sums, 2 Steps, 2 Muxes, 1 Scope |
| `2y''' + 5y'' + y' + 2y + z''' + 1.5z'' + 2z' + 2z = u ; 3z''' + 2z'' + 5z' + 2z - y''' - 5y'' - 3y' - 2y = 0` | 6 Integrators, 13 Gains (1/2, 1/3, 3/2, 3, three 5, six 2), 2 Sums, 1 Step, 1 Mux, 1 Scope. y⃛ goes into the Sum of z⃛ and z⃛ into the Sum of y⃛: the two equations need each other, and Simulink solves this loop by itself. |

A single equation has no Mux: u and y each go to their own Scope input. Decimals are always shown as fractions: `0.5y'` gives a Gain `1/2`.

### Initial conditions

| Input | Output |
|---|---|
| `y'' + 3y' = u` with `--ic "y(0)=1"` | Shown as y(0) = 1, ẏ(0) = 0. In the script, the Integrator of y starts at 1 and the one of ẏ at 0. |
| `--ic "y(0)=-2, y'(0)=1/3"` | y(0) = −2, ẏ(0) = 1/3 |

### Wrong inputs → message

| Input | Message |
|---|---|
| `y'' + 3y'` | Each equation needs exactly one '=': y'' + 3y' |
| `y + 3 = u` | No derivative found. Write derivatives with apostrophes, like y'. |
| `y'' + z'' = u` | 1 equation(s) for 2 unknown variable(s) (y, z). The counts must be equal. |
| `y''^2 + y = u` | The highest derivatives must appear linearly (not squared, multiplied together or inside a function). |
| `y'' + foo(y) = u` | Unknown function 'foo'. Supported: abs, sqrt, exp, sin, cos. ... |
| `y'' + 3y' = u$` | Unsupported character(s): $ |
| `y' + z' = u ; y' + z' = v` | The equations cannot be solved for the highest derivatives. |
| `--ic "y''(0)=1"` for `y'' + 3y' = u` | y''(0) cannot be set: the last value you can give for y is y'(0). |
| `--ic "z(0)=1"` for `y'' + 3y' = u` | 'z' is not a variable of the equation(s). |
| `--ic "y(0)=a"` | The value of y(0) must be a number, not: a |

## Tests done by hand

Two things can't be checked by an automatic test, so I check them myself.

**The equation window.** A test checks that every equation can be drawn without an error, but only a person can see if it looks right. I open the window with the README examples and check the notation.

**The model in MATLAB.** I run the generated script in MATLAB, check that the model has the expected blocks, that it runs, and that the Scope shows the expected curve.

| Equation | What I checked | Result |
|---|---|---|
| `3y'' + y' + 2y = u` | Expected blocks, no Mux, the model runs | ✅ |
| same, with `--ic "y(0)=1"` | The Scope starts at y = 1 | ✅ |
| `y''' + 5y'' + 2y' + y + z = u ; z'' + z' + z + y = v` | Expected blocks, one Mux per equation, the model runs | ✅ |
| `y''' + 3y''*abs(y') + 0.5y' + y'^2*y = u` | Expected blocks (an Fcn block u^2 for ẏ²), no Mux, the model runs | ✅ |
| `2y''' + 5y'' + y' + 2y + z''' + 1.5z'' + 2z' + 2z = u ; 3z''' + 2z'' + 5z' + 2z - y''' - 5y'' - 3y' - 2y = 0` | Expected blocks (Gains 1/2 and 1/3, y⃛ and z⃛ feeding each other's Sum), the model runs with no warning | ✅ |
