# Simulink Reference Generator

You write a differential equation as plain text. The program builds the matching Simulink model, so you can check the model you made by hand.

> Version 1.0 is almost ready. The test documentation and the diagrams are still to come.

## Purpose

In a Simulink course, you turn differential equations into block diagrams by hand. This program does the same thing automatically, with the method taught in the course:

1. Isolate the highest derivative of each equation (for example ÿ = u − 3ẏ).
2. Chain one Integrator per derivative (ÿ → ẏ → y). An Integrator is the block that turns ÿ into ẏ, and ẏ into y.
3. Send every term back into a Sum block with its sign, through Gain, Product, Abs or power blocks.
4. Show the input and the result on a Scope.

You solve the exercise first. Then you generate the reference model and compare the two models and their results.

**Who it is for:** students of a "Simulations in MATLAB/Simulink" course, and teachers who prepare the solutions.

## Installation

You need Python 3.10 or newer. To open the model, you also need MATLAB R2018a or newer with Simulink. The program itself runs without MATLAB.

```bash
git clone https://github.com/simlirette/semestral-work-ite.git
cd semestral-work-ite
pip install -r requirements.txt
```

The program uses two libraries: [SymPy](https://www.sympy.org) to read and solve the equations, and [matplotlib](https://matplotlib.org) to show them in a window.

## Usage

```bash
python main.py "EQUATION" [--ic VALUES] [--name NAME] [--output FOLDER] [--no-gui]
```

| Option | What it does | Default |
|---|---|---|
| `EQUATION` | The equation(s), in quotes | (required) |
| `--ic` | Initial conditions, like `"y(0)=1, y'(0)=0.5"` | all 0 |
| `--name` | Name of the Simulink model and of the `.slx` file | `reference_model` |
| `--output` | Folder where the MATLAB script is saved | `output` |
| `--no-gui` | Show the equations in the terminal only, without a window | off |

### Writing the equation

| Write | Meaning |
|---|---|
| `y'`, `y''`, `y'''`, `y''''` | 1st, 2nd, 3rd, 4th derivative of y |
| `3y'` or `3*y'` | 3 times y' |
| `y'^3` | y' to the power 3 |
| `abs(y')`, `sqrt(y)`, `sin(y)`, `cos(y)`, `exp(y)` | functions |
| `;` | separates the equations of a system |
| `u`, `v`, `F`... | a letter without an apostrophe is an input (a Step block) |

You can write `(t)` after a variable or leave it out: `y''(t) + 3y'(t) = u(t)` is the same as `y'' + 3y' = u`.

### Writing the initial conditions

An initial condition is the value of a variable at the start of the simulation (t = 0). Write them like the equation, separated by commas:

```bash
python main.py "y'' + 3y' = u" --ic "y(0)=1, y'(0)=0.5"
```

- Each value goes into one Integrator. For a 2nd-order equation, you can give y(0) and y'(0), but not y''(0).
- Values you don't give are 0.
- Decimals, negative numbers and fractions work: `y(0)=-2, y'(0)=1/3`.

### Examples

```bash
python main.py "y'' + 3y' = u"                                         # exercise 1
python main.py "5y''' + 10y'' + 10y' + 2y = u" --name exercise10       # coefficient in front of y'''
python main.py "y'' + 2y'^3 + y = u" --name exercise2                  # nonlinear
python main.py "y'' + 3y' = u" --ic "y(0)=1, y'(0)=0.5"                # with initial conditions
python main.py "y''' + 5y'' + 2y' + y + z = u ; z'' + z' + z + y = v"  # system (exercise 3)
```

### What happens

1. The program shows how it understood your equation, written like in class (dots for derivatives, y⁽⁴⁾ from the 4th one), and the equation solved for the highest derivative. If you gave initial conditions, it shows them too:

   ```
   Interpreted equation:
       3ÿ(t) + ẏ(t) + 2y(t) = u(t)

   Solved for the highest derivative:
       ÿ(t) = (u(t) - ẏ(t) - 2y(t)) / 3

   Initial conditions:
       y(0) = 1, ẏ(0) = 0.5

   Is this what you meant? [y/n]:
   ```

   The same thing also opens in a small window, written like an equation in Word.

2. If you answer `y`, it saves the MATLAB script `output/build_<name>.m`.
3. Run that script in MATLAB. It builds the model, arranges the blocks, opens the model and saves `<name>.slx` next to the script. Press Run and open the Scope to see the results.

If the program can't read the equation (no `=`, unknown function, more unknowns than equations...), it tells you why and stops.

## Running the tests

```bash
python test_main.py
```

All the tests are in the `tests/` folder. None of them needs MATLAB.

## Project structure

```
src/
  parser.py            reads the text: equations and initial conditions
  formatter.py         writes the equations in class notation (window and terminal)
  confirmation.py      shows the equations and asks you to confirm
  block_model.py       turns the equations into Simulink blocks and wires
  matlab_generator.py  writes the MATLAB script that builds the model
tests/                 one test file per module
main.py                runs the program
test_main.py           runs all the tests
```

## Limitations

- Each equation must be solvable for its highest derivative. That derivative can't be squared or inside a function.
- Coefficients must be numbers. In `m*x'' + k*x = F`, m and k are read as input signals, not as values.
- An integral on the right side of the equation (exercise 4 of the course) is not supported.
- Physical models like the water tanks (saturation, Goto/From blocks, subsystems) are not generated.
- Only the Integrator version of the model is generated, not the Transfer Function version.
- The blocks are the same as in the course solutions, but Simulink places them itself, so the drawing can look different from the professor's.
- In a system, each equation that has an input gets a Mux (a block that groups signals) before the Scope, as in exercises 3, 7 and 12. In exercises 6 and 9, the professor uses no Mux, so the model has one more block than his solution.
- Inputs are Step blocks with Simulink's default settings, and the simulation lasts 100 s.

## License

MIT, see [LICENSE](LICENSE).
