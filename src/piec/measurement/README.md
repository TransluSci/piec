# Measurement Waveforms

This directory contains classes for managing discrete waveform generation, measurement coordination, and data capture. It abstracts the complexity of synchronizing Arbitrary Waveform Generators (AWG), Oscilloscopes, Lock-in Amplifiers, and other instruments into reusable experiments.

## Directory Structure

- **`experiment.py`**: Contains `Experiment`, the common base for all measurement types. `DiscreteWaveform`, `IVSweep`, and `MagnetoTransport` inherit from it; their specific implementations inherit through those classes.
- **`discrete_waveform.py`**: Contains the `DiscreteWaveform` base class and specific implementations:
    -   `HysteresisLoop`: For ferroelectric hysteresis measurements using triangular waveforms.
    -   `ThreePulsePund`: For PUND (Positive-Up-Negative-Down) switching measurements.
- **`magneto_transport.py`**: Contains `MagnetoTransport` and `AMR` (Anisotropic Magnetoresistance) classes for controlling magnets, stepper motors, and lock-in amplifiers.
- **`iv_sweep.py`**: Contains `IVSweep` for sourcemeter voltage sweeps.
- **`amr.py`**: Re-exports `AMR` and magneto-transport helpers.

`Experiment` provides save-directory initialization, metadata collection, and
independent history snapshots. `DiscreteWaveform`, `IVSweep`, and
`MagnetoTransport` initialize this shared state after setting their measurement
parameters and declare all required instrument attributes in `_instruments`.
Call `experiment.safe_close()` to reset each declared instrument using its
`initialize()` method.
The collector stores instrument IDs and current public parameters, including
dictionary-valued settings such as plot configuration. Each measurement refreshes
metadata before saving and records a history snapshot at the end of its run.

## Usage

### Hysteresis Measurement

Use `HysteresisLoop` to coordinate an AWG and Oscilloscope for capturing PE loops.

```python
from piec.measurement.discrete_waveform import HysteresisLoop
from piec.drivers.oscilloscope.k_dsox3024a import KeysightDSOX3024a
from piec.drivers.awg.k_33500B import Keysight33500B

# Initialize instruments (drivers usually defined in piec.drivers)
scope = KeysightDSOX3024a('USB0::...')
awg = Keysight33500B('USB0::...')

# Create experiment
experiment = HysteresisLoop(
    awg=awg, 
    osc=scope, 
    frequency=1000, 
    amplitude=5.0, 
    save_dir=r'C:\Data'
)

# Run the full sequence: configure -> capture -> save -> analyze
experiment.run_experiment()
```

### Magneto-Transport (AMR)

Use `AMR` to control field and angle for magnetoresistance measurements.

```python
from piec.measurement.magneto_transport import AMR

# Initialize required instruments...
# experiment = AMR(dmm=dmm, calibrator=calib, arduino=stepper, lockin=lockin, field=1000)
# experiment.run_experiment()
```

## Creating New Experiments

All measurement GUIs inherit settings persistence from `MeasurementApp`. Closing
a window prompts to save its inputs, instrument addresses, save directory,
checkboxes, and plot selections. Settings load automatically on the next launch.
Dynamic panels should call `_cache_dynamic_inputs()` before replacing their
widgets and `_apply_saved_dynamic()` after building the new panel, so each
measurement type retains its own values.

Declare a GUI's required instrument categories in `_instruments`. The parent
creates address selectors (defaulting to `VIRTUAL`), Refresh, Autodetect, and
connection-test buttons. Refresh preserves selected addresses, even when a device
is disconnected. The generated fields are included in saved GUI settings.

```python
class MyWaveformApp(MeasurementApp):
    _instruments = ('awg', 'oscilloscope')

    def run_measurement(self):
        instruments = self.connect_instruments()
        awg = instruments['awg']
        scope = instruments['oscilloscope']
        # Configure the instruments and capture the measurement here.
```

No model-specific driver imports are needed in the GUI. Category names and aliases
use the driver discovery system. `connect_instruments()` opens the selected
addresses with matching driver types and closes partial connections on failure.
Optional per-instrument constructor arguments can be passed by category name;
simulation-only arguments belong in `virtual_options`, for example
`virtual_options={'awg': {'simulation_points': 1000}}`. `close_instruments()`
releases GUI-owned connections and runs automatically when the window closes,
after the experiment's `safe_close()`.

Autodetect closes its temporary probe connections and leaves unmatched selections
unchanged. Categories with one registered, manual-only driver (currently Geo's
stepper) retain explicit-address connection support; they are not automatically
detected. No fallback model is guessed for categories with multiple drivers.

GUIs and notebooks in `Measurements` default to the relative `scratch` directory,
which is ignored by Git. Choose a different save directory for data to keep.

To create a new waveform measurement:
1.  Inherit from `DiscreteWaveform`.
2.  Define `configure_awg()` to setup the specific pulse/shape.
3.  Define `analyze()` to process the captured data.
