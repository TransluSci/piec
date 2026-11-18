# Simulation Module

Simulated sample models for virtual instruments and hardware-free testing. The module follows a 3-level hierarchy mirroring `piec.drivers`:

1. **Level 1 (`sample.py`)**: `Sample` — minimal base class holding `name`, `parameter_dict`, and baseline state for the universal physical stimuli and observables below.
2. **Level 2 (`<category>/<category>.py`)**: Pure contract interfaces (`ResistiveMaterial`, `FerroelectricMaterial`, `MOKEMaterial`, `AMRMaterial`, `ExampleSample`). Each category overrides only the physical I/O methods required for that measurement type with `raise NotImplementedError`, without implementing physics.
3. **Level 3 (`<category>/<model>.py`)**: Concrete physics models implementing those Level 2 methods directly from their scalar or dictionary parameters (`parameter_dict`).

## Universal Physical Stimuli & Observables

Virtual instruments interact with **any** `Sample` exclusively through this unified physical vocabulary—no experiment-specific branching or method names in drivers:

| Direction | Method | Physical Meaning | Virtual Instrument Caller |
|---|---|---|---|
| **Stimulus (In)** | `set_voltage(v)` | Apply DC voltage (V) | `VirtualSourcemeter`, `VirtualCalibrator` |
| **Stimulus (In)** | `set_current(i)` | Apply DC current (A) | `VirtualSourcemeter`, `VirtualCalibrator` |
| **Stimulus (In)** | `set_field(field)` | Apply magnetic field (Oe) | `VirtualFieldController` |
| **Stimulus (In)** | `set_angle(angle)` | Set orientation angle (deg) | `VirtualStepper` |
| **Stimulus (In)** | `apply_waveform(v, t)` | Apply time-domain waveform | `VirtualAwg` |
| **Observable (Out)** | `get_voltage()` | Read terminal / detector voltage (V) | `VirtualSourcemeter`, `VirtualDMM` |
| **Observable (Out)** | `get_current()` | Read terminal current (A) | `VirtualSourcemeter` |
| **Observable (Out)** | `get_resistance()` | Read electrical resistance (Ohm) | `VirtualLockin` |
| **Observable (Out)** | `get_field()` | Read magnetic field (Oe) | `VirtualGaussmeter` |
| **Observable (Out)** | `get_angle()` | Read orientation angle (deg) | `VirtualStepper` |
| **Observable (Out)** | `get_waveform()` | Read captured `(voltage_V, time_s)` | `VirtualScope` |

Because Level 1 `Sample` provides neutral defaults for every stimulus and observable, any sample can be placed into any virtual experiment (for example, putting `OhmicResistor` into `AMR` yields an angle-independent resistance trace).

## Categories

*   **`resistor/`**: Two-terminal resistive/I-V samples.
    *   Level 2: `ResistiveMaterial` (`resistor.py`)
    *   Level 3: `OhmicResistor` / `Resistor` (`ohmic_resistor.py`), `SimpleDiode` (`simple_diode.py`)
*   **`fe_material/`**: Ferroelectric capacitor samples.
    *   Level 2: `FerroelectricMaterial` (`fe_material.py`)
    *   Level 3: `LandauFerroelectric` / `Ferroelectric` (`landau_ferroelectric.py`)
*   **`magnetic/moke/`**: Magneto-Optic Kerr Effect (MOKE) samples ($H \rightarrow M, V_{\text{photodiode}}$).
    *   Level 2: `MOKEMaterial` (`moke.py`)
    *   Level 3: `ArctanMOKE` (`arctan_moke.py`)
*   **`magnetic/amr/`**: Anisotropic magnetoresistance / magneto-transport samples ($(H, \theta) \rightarrow R, V_{\text{terminal}}$).
    *   Level 2: `AMRMaterial` (`amr.py`)
    *   Level 3: `CosSquaredAMR` / `MagneticSample` (`cos_squared_amr.py`)
*   **`example/`**: Reference template (`ExampleSample`, `SpecificExampleSample`, and `readme.md`).

## Simulation Hub GUI

`src/piec/simulation/simulation_hub.py` provides `SimulationHubWindow`, which dynamically discovers every Level-2 category and Level-3 model along with its editable parameters, instantiates the configured sample, and assigns it globally via `VirtualInstrument.sample`. Launch it standalone (`python -m piec.simulation.simulation_hub`) or via the **SIMULATION HUB** button inside any `MeasurementApp` GUI.

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