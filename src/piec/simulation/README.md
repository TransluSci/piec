# Simulation Module

This module provides tools for simulating various materials and their responses. It is primarily designed to support virtual instruments and testing scenarios where physical hardware is not available.

## Contents

`sample.py` defines `Sample`, the common base for all simulated samples. `Material` and `MagneticSample` inherit from it; `Resistor`, `Dielectric`, and `Ferroelectric` inherit through `Material`.

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

Classes can be imported directly from the module. The primary methods for interaction are typically `voltage_response`, `current_response`, or `apply_waveform`. Instrument drivers provide the applied signal; these material objects provide the simulated device response.

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

# Or calculate the voltage produced by a sourced current.
v_response, t_out = r.current_response(i_response, t)
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
