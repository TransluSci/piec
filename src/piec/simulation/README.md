# Simulation Module

This module provides tools for simulating various materials and their responses. It is primarily designed to support virtual instruments and testing scenarios where physical hardware is not available.

## Role contracts (checkpoint 27)

`contracts.py` defines electrical loads and material roles. Load inputs/outputs
use V, A, Ohm and s. The FE material's native polarization is C/m^2; measurement
output may convert to uC/cm^2 explicitly. `LoadResponse.state` is a detached,
immutable snapshot of scalar/container state; apparent resistance can be infinite
or undefined at zero current.

- `reset()` restores constructor start time and the stored RNG seed, including
  replay within an instance constructed without an explicit seed. Independent
  unseeded instances need not agree. Use an explicit seed for cross-instance replay.
- Absolute role timestamps cannot move backwards outside reset. FE waveform
  timestamps are local to an acquisition; valid uniformly sampled waveforms
  advance its clock by their duration.
- `CapacitiveLoad` requires positive elapsed time. It uses backward Euler with
  interval-average current and end-step leakage. Choose a timestep small enough
  to resolve the circuit; it does not resolve sub-step compliance transitions.
- `DiodeLoad` models Shockley conduction with optional series resistance, without
  reverse breakdown. Reverse current beyond saturation reaches the supplied voltage
  compliance limit. `noise_std` is A for voltage-source readback;
  `voltage_noise_std` is V for current-source readback.
- `MagneticSample.get_voltage_response(excitation_current=...)` requires current
  in A and returns a plain `(X, Y)` tuple in V. The resistive model has Y=0;
  there is no scalar/tuple compatibility wrapper or implicit excitation current.
  The existing VirtualLockin fallback passes its declared simulation-only
  `excitation_current` setting (default 1 uA). This is not a measured sample current
  or a model of the physical lock-in output circuit.

## Driver virtual hooks (checkpoint 28a)

- `VirtualLockin` (lock-in driver family) supports generic per-instance hook injection via
  `xy_reader` or `transport_hook` (in constructor, via property, or via `set_xy_reader`).
- Injected hooks take strict precedence over the deprecated global `mag_sample` fallback.
- The generic driver contains no sample-, magnetic-, or AMR-specific logic; material behavior
  remains external to the driver.
- Declared excitation current (in A) is forwarded to hooks that accept `excitation_current`
  or a single positional argument; 0-argument hooks are supported as well.
- Invocation is selected by signature binding before calling the hook exactly once.
  Hook exceptions propagate unchanged. Callables with unavailable signatures follow
  the zero-argument contract; wrap them in a Python function to receive current.
- Excitation current accepts finite signed values and zero, including after construction.
  Reference voltage and declared sample current are independent simulation settings;
  converting oscillator output voltage to current requires an explicit external circuit model.
- Reference configuration validates amplitude, frequency, source and phase before changing
  state. `read_data()` derives phase in degrees from `atan2(Y, X)`.
- Returns plain `(X, Y)` tuples in V without compatibility wrappers. Non-sequence, wrong-length,
  or non-finite hook returns raise `TypeError` or `ValueError`.
- `reset()` restores constructor excitation current and default settings while preserving the
  injected hook. Instance assignments to `lockin.mag_sample` do not pollute global shared sample state.
  Reset does not reset a closure's RNG, time or material: that state is owned by the
  setup and must be reset there. A future VirtualBench will coordinate those resets.

## Driver virtual hooks: DMM family (checkpoint 28b)

- `VirtualDMM` (DMM driver family) supports generic per-instance hook injection via
  `voltage_reader` or `reader_hook` (in constructor, via property, or via `set_voltage_reader`).
- Injected hooks take strict precedence over the deprecated global `mag_sample` fallback.
  When an explicit hook is injected, `mag_sample` is not accessed.
- The injected path adds no sample-, sensor-, or material-specific logic; physical modeling
  remains external in the hook. The historical `current_field / 10000` fallback remains
  solely for existing shared-sample simulations; it is not a general sensor calibration.
- The hook receives coupling parameters if declared: accepts zero arguments, keyword `ac` or `coupling`,
  or positional-only `ac` or `coupling`. Callables with unavailable signatures follow the zero-argument contract.
- Named `ac` and `coupling` parameters are supplied together when both are declared,
  including mixed positional-only/keyword signatures. Optional unrelated parameters
  keep their defaults. A `**kwargs` hook also receives undeclared coupling settings.
- Invocation is selected by signature binding before calling the hook exactly once. Hook exceptions
  propagate unchanged without retries or fallback invocation.
- Returns scalar `float` voltages in Volts. Preserves IEEE 754 non-finite numbers (`inf`, `-inf`, `nan`)
  for DMM hardware overload emulation (per Checkpoint 6 contract). Rejects non-scalar collections
  (`tuple`, `list`, multi-element or non-0d `ndarray`) with `TypeError`.
- `reset()` restores default driver-owned configuration (`sense_func="VOLT"`, `coupling="DC"`,
  `sense_mode="2W"`, `sense_range=None`, `autorange=True`, `integration_time=1.0`) while preserving
  the injected hook. Instance assignments to `dmm.mag_sample` do not pollute global shared sample state.
- Driver reset does not reset setup-owned closures, external material models, clocks, or RNG seeds:
  that state is owned by the setup / fixture and must be reset there. A future VirtualBench will coordinate resets.
- Manual sense range and integration time must be positive and finite. Rejected
  configuration values leave state unchanged; non-finite voltage readings remain
  permitted by the overload contract.

## Driver virtual hooks: DC Calibrator family (checkpoint 28c)

- `VirtualCalibrator` (DC calibrator driver family) supports generic per-instance hook injection via
  `output_hook` or `field_hook` (in constructor, via property, or via `set_output_hook`).
- Injected hooks take strict precedence over the deprecated global `mag_sample` fallback.
  When an explicit hook is injected, `mag_sample` is not accessed or mutated.
- The injected path adds no sample-, sensor-, or magnetic-specific logic; physical modeling
  remains external in the hook closure. The historical `value * 10000.0` fallback remains
  solely for existing shared-sample simulations.
- Hook receives commanded output parameters if declared: accepts single output value (positional
  or named), `mode` ("voltage" or "current"), `output_on` (boolean), or `**kwargs`.
  Zero-argument hooks are also supported.
- Invocation is selected by signature binding before calling the hook exactly once. Hook exceptions
  propagate unchanged without retries or fallback invocation.
- Declared units are `{"voltage": "V", "current": "A"}`. Output values must be finite numeric values;
  rejected values leave state unchanged.
- `reset()` restores default driver-owned configuration (`output_on=False`, `voltage=0.0`, `current=0.0`,
  `mode="voltage"`, engaging crowbar) while preserving the injected hook. If a hook is injected, it is
  notified of 0.0 V output. Instance assignments to `cal.mag_sample` do not pollute global shared sample state.
- Driver reset does not reset setup-owned closures, external material models, clocks, or RNG seeds:
  that state is owned by the setup / fixture and must be reset there. A future VirtualBench will coordinate resets.

Other driver families and VirtualBench wiring remain separate later checkpoints.

## Contents

The core logic is implemented in `fe_material.py` and includes:

*   **`Material`**: Base class for all material simulations.
*   **`Resistor`**: Simulates an ideal ohmic resistor ($V = IR$).
*   **`Dielectric`**: Simulates an ideal linear dielectric material.
*   **`Ferroelectric`**: Implements a Landau-Devonshire model for ferroelectric materials, including:
    *   Hysteresis loop calculation.
    *   Temperature dependence ($T_0$).
    *   Strain effects from substrate mismatch.
    *   Parasitic effects (linear dielectric background and leakage/loss).

## Usage

Classes can be imported directly from the module. The primary method for interaction is typically `voltage_response` or `apply_waveform`.

### Example: Simulating a Resistor

```python
import numpy as np
from piec.simulation.fe_material import Resistor

# Create a resistor
r = Resistor(resistance=2000)

# Define a waveform
t = np.linspace(0, 1e-3, 1000)
v = np.sin(2 * np.pi * 1000 * t)

# Calculate response
i_response, t_out = r.voltage_response(v, t)
```

### Example: Simulating a Ferroelectric Capacitor

The `Ferroelectric` class requires a material property dictionary for initialization.

```python
from piec.simulation.fe_material import Ferroelectric

# Define material properties (or use defaults from virtual_instrument.py)
material_props = {
    'ferroelectric': {
        'a0': 8.248e5, 'b': -8.388e8, 'c': 7.764e9, 'T0': 388,
        'Q12': -0.034, 's11': 1.27e-11, 's12': -4.2e-12,
        'lattice_a': 4.02e-10, 'film_thickness': 10e-9,
        'epsilon_r': 400, 'leakage_resistance': 1e4
    },
    'substrate': {'lattice_a': 3.905e-10},
    'electrode': {'screening_lambda': 5e-11, 'permittivity_e': 8.0, 'area': 4e-10}
}

fe_sample = Ferroelectric(material_dict=material_props)
fe_sample.apply_waveform(v, t)
output_voltage, time = fe_sample.get_voltage_response()
```
