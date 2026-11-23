# Simulation Module

Simulated sample models for virtual instruments and hardware-free testing. The module follows a 3-level hierarchy mirroring `piec.drivers`:

1. **Level 1 (`sample.py`)**: `Sample` — minimal base class holding `name`, `parameter_dict`, a generic `state` dict for pass-through stimulus tracking, and an `Instrument`-style `__getattr__` fallback that prints `[UNSUPPORTED]` once per method and returns `None`. A bare `Sample()` instance acts as a pass-through wire.
2. **Level 2 (`<category>/<category>.py`)**: Pure contract interfaces (`ResistiveMaterial`, `FerroelectricMaterial`, `MOKEMaterial`, `AMRMaterial`). Each category declares only the bare-minimum stimulus-to-response methods (`apply_voltage`, `apply_current`, `apply_field`) as docstring-only stubs mirroring `piec.drivers.awg.awg.Awg`.
3. **Level 3 (`<category>/<model>.py`)**: Concrete physics models implementing those Level 2 methods directly from their scalar or dictionary parameters (`parameter_dict`).

## Minimal Stimulus-to-Response Contracts

Virtual instruments share applied stimulus state via `sample.state` and call a sample's stimulus-to-response method directly:

| Category | Level-2 Contract Method(s) | Physical Meaning | Virtual Instrument Caller |
|---|---|---|---|
| **Resistor / I-V** | `apply_voltage(v, t=0.0)`, `apply_current(i, t=0.0)` | Apply voltage/current (scalar DC or waveform) and return current/voltage | `VirtualSourcemeter`, `VirtualScope` |
| **Ferroelectric** | `apply_voltage(v, t=0.0)` | Apply DC voltage or waveform `v(t)` and return current (A) | `VirtualScope`, `VirtualSourcemeter` |
| **MOKE** | `apply_field(field)` | Apply magnetic field (Oe) and return photodetector voltage (V) | `VirtualFieldController` |
| **AMR** | `apply_current(i=1e-6, angle=0.0, field=0.0)` | Apply sense current at `(angle, field)` and return terminal voltage (V) | `VirtualLockin` |

If an experiment or virtual instrument invokes a method that the active sample does not implement, `Sample.__getattr__` prints a one-time `[UNSUPPORTED]` notice to the console and returns `None` rather than crashing.

## Categories

*   **`resistor/`** *(reference template)*: Two-terminal resistive/I-V samples.
    *   Level 2: `ResistiveMaterial` (`resistor.py`)
    *   Level 3: `OhmicResistor` / `Resistor` (`ohmic_resistor.py`), `SimpleDiode` (`simple_diode.py`)
*   **`ferroelectric/`**: Ferroelectric capacitor samples.
    *   Level 2: `FerroelectricMaterial` (`ferroelectric.py`)
    *   Level 3: `LandauFerroelectric` / `Ferroelectric` (`landau_ferroelectric.py`)
*   **`magnetic/moke/`**: Magneto-Optic Kerr Effect (MOKE) samples ($H \rightarrow V_{\text{photodiode}}$).
    *   Level 2: `MOKEMaterial` (`moke.py`)
    *   Level 3: `ArctanMOKE` (`arctan_moke.py`)
*   **`magnetic/amr/`**: Anisotropic magnetoresistance / magneto-transport samples ($(I, \theta, H) \rightarrow V_{\text{terminal}}$).
    *   Level 2: `AMRMaterial` (`amr.py`)
    *   Level 3: `CosSquaredAMR` (`cos_squared_amr.py`)

## Simulation Hub GUI

`src/piec/simulation/simulation_hub.py` provides `SimulationHubWindow`, which dynamically discovers every Level-2 category and Level-3 model along with its editable parameters, instantiates the configured sample, and assigns it globally via `VirtualInstrument.sample`. When opened from a `MeasurementApp` GUI, it filters the catalog to only the samples supported by that GUI. Launch it standalone (`python -m piec.simulation.simulation_hub`) or via the **SIMULATION HUB** button inside any `MeasurementApp` GUI.

## Usage

### Example: Swapping Samples Behind Virtual Instruments

Setting `.sample` on any virtual instrument updates the single global sample shared across every virtual instrument:

```python
from piec.drivers.sourcemeter.virtual_sourcemeter import VirtualSourcemeter
from piec.simulation.resistor.simple_diode import SimpleDiode

sm = VirtualSourcemeter()
sm.sample = SimpleDiode()  # shared globally across all virtual instruments
sm.configure_voltage_source(voltage=0.5)
current = sm.get_current()
```
