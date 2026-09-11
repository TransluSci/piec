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

Per-instance driver hooks and VirtualBench wiring remain later checkpoints.

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
