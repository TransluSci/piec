# AMR Measurement Documentation

> AMR setup profiles decouple magnetic field control, sample excitation, and voltage readout. The architecture supports **Lock-in internal AC excitation** or **external DC sourcemeter excitation**, and **Lock-in AC** or **DMM DC voltage readout**. Manually selected front-panel instrument settings are preserved by default.

This document describes the Anisotropic Magnetoresistance (AMR) measurement system, excitation and readout options, software architecture, and operation via Python script/notebook and the Graphical User Interface (GUI).

---

## Overview

**Anisotropic Magnetoresistance (AMR)** is a property of ferromagnetic materials where electrical resistance depends on the angle $\theta$ between the current direction and magnetization:

$$R(\theta) = R_{\perp} + (R_{\parallel} - R_{\perp}) \cos^2(\theta) = R_{avg} + \Delta R \cos(2\theta)$$

Experimental data is fitted to extract the average resistance $R_{avg}$, AMR amplitude $\Delta R$, and angular offset $\theta_0$:

$$y = A + B \cos(2(\theta - \theta_0))$$

---

## Hardware Architecture & Modes

The bench combines magnetic field generation, angular positioning, sample excitation, and voltage readout:

### 1. Magnetic Field & Orientation
* **Field Generation (Calibrator)**: DC calibrator (`EDC522` or `VirtualCalibrator`) drives the electromagnet via a linear field calibration factor (default `10000 Oe/V`).
* **Field Verification (Optional DMM / Hall Sensor)**: Reads the active magnetic field to verify stabilization.
* **Sample Rotation (Stepper)**: High-resolution stepper motor (`Geos_Stepper` or `VirtualStepper`) rotates the sample relative to the magnetic field.

### 2. Sample Excitation Modes
* **Internal Lock-in (AC)**: The Lock-in amplifier's built-in Sine Out oscillator drives AC current through the sample. Configured by `Amplitude (V)` and `Frequency (Hz)`.
* **External Sourcemeter (DC)**: A dedicated sourcemeter (`Keithley2400` or `VirtualSourcemeter`) supplies a constant current. Configured by `Current (A)` and `Compliance (V)`.
* **Automated Safe Shutdown**: External current sources automatically execute `output(on=False)` upon run completion, abort, or error.

### 3. Voltage Readout Modes
* **Lock-in Amplifier (AC)**: Measures in-phase ($X$) and quadrature ($Y$) voltages across the sample contacts with high SNR.
* **Multimeter / DMM (DC)**: Measures DC voltage across the sample contacts ($X = V_{dc}$, $Y = 0.0$), preserving the canonical `("angle", "field", "x", "y")` schema (`amr: 1`).

### 4. Manual Knob Preservation Guarantee
When `initialize_lockin=False` (default preserve mode), the software **never** sends configuration commands or setting queries to the lock-in amplifier. All physical front-panel knobs and settings (amplitude, frequency, sensitivity, time constant) are preserved untouched, and the driver only issues data readout commands (`quick_read()` / `get_X_Y()`).

---

## Software Architecture

* **`MagnetoTransport`** (`src/piec/measurement/magneto_transport.py`):
  Base class managing instrument coordination, pre-run bench tuning (`test_excitation()`, `auto_gain()`), and standardized `BaseMeasurement` lifecycles.
* **`AMR`** (`src/piec/measurement/amr.py` or `magneto_transport.py`):
  Concrete AMR measurement class executing angular sweeps without endpoint overshoot and exporting canonical schema dataframes.
* **Adapters** (`src/piec/measurement/adapters/amr.py`):
  * `SampleExcitation`: Encapsulates internal oscillator vs. external sourcemeter with automated safe shutdown.
  * `TransportReadout`: Encapsulates Lock-in AC vs. DMM DC readout, with strictly readout-only communication when in preserve mode.

---

## Python / Notebook Usage

```python
from piec.measurement.amr import AMR
from piec.drivers.lockin.srs830 import SRS830
from piec.drivers.sourcemeter.keithley2400 import Keithley2400
from piec.drivers.dc_calibrator.edc522 import EDC522
from piec.drivers.stepper_motor.arduino_stepper import Geos_Stepper

# 1. Instantiate instruments
calibrator = EDC522("GPIB0::06::INSTR")
stepper = Geos_Stepper("COM3")
lockin = SRS830("GPIB0::08::INSTR")

# Option A: Standard AC AMR (Lock-in internal excitation + Lock-in readout)
exp = AMR(
    calibrator=calibrator,
    stepper=stepper,
    lockin=lockin,
    field=100.0,
    angle_step=5.0,
    total_angle=360.0,
)

# Option B: DC Current AMR (External sourcemeter + Lock-in readout)
# sourcemeter = Keithley2400("GPIB0::24::INSTR")
# exp = AMR(
#     calibrator=calibrator,
#     stepper=stepper,
#     lockin=lockin,
#     current_source=sourcemeter,
#     current=1e-4, compliance=2.0,
#     field=100.0, angle_step=5.0, total_angle=360.0,
# )

# 2. Pre-run bench verification (optional)
status = exp.test_excitation()
print(f"Preview: V={status.voltage:.3e} V, R={status.resistance}, Overloaded={status.overloaded}")

# 3. Run measurement sweep
df = exp.run_experiment(output_dir="data/AMR")
```

---

## Graphical User Interface (`Measurements/AMR/amr_GUI.py`)

Run the GUI with:
```bash
python Measurements/AMR/amr_GUI.py
```

### 1. Static Inputs & Connections
* **`Calibrator (Field):`** VISA address for the electromagnet calibrator. Includes **Refresh**, **Autodetect**, and **Test Stepper** buttons.
* **`Stepper (Angle):`** VISA / COM address for the rotation stepper motor.
* **`Excitation Source:`** Choose between:
  * `Lock-in Internal (AC)`: Uses Lock-in Sine Out oscillator. Sourcemeter Address is disabled.
  * `External Sourcemeter (DC)`: Uses external sourcemeter. Activates **Sourcemeter Address**.
* **`Sourcemeter Address:`** VISA address of the Keithley 2400 or `VIRTUAL` (active when External Sourcemeter is selected).
* **`Voltage Readout:`** Choose between:
  * `Lock-in (AC)`: Measures $X, Y$ via Lock-in amplifier.
  * `DMM (DC)`: Measures DC voltage via DMM.
* **`Lock-in Address:`** VISA address of the Lock-in amplifier.
* **`DMM Address:`** VISA address of the DMM.

### 2. Measurement Parameters (Dynamic Inputs)
* **`Magnetic Field (Oe):`** Target field strength.
* **`Angle Step (deg):`** Increment per rotation step.
* **`Total Angle (deg):`** Total sweep range (e.g. 360°).
* **`Measure Time (s):`** Settling / dwell time per angle.
* **`Ext Current (A)` & `Ext Compliance (V):`** Sourcemeter excitation setpoints (active in External Sourcemeter mode).
* **`Lock-in Amplitude (V)` & `Lock-in Frequency (Hz):`** Lock-in oscillator excitation (active in Lock-in Internal mode).
* **`Lock-in Sensitivity:`** Desired sensitivity if auto-configuring; leave as is to preserve manual dials.
* **`Initialize Lock-in?:`** When **unchecked** (default), preserves your physical front-panel knobs. When **checked**, applies the software amplitude/frequency/sensitivity.

### 3. Bench Setup & Live Tuning
* **Active Setup Badge:** Displays live summary (e.g. `Setup: Excitation = Lock-in Internal (AC) | Readout = Lock-in (AC)`).
* **`Test Excitation` Button:** Briefly energizes the source, reads $X, Y$, calculates voltage magnitude $V$ and estimated sample resistance $R = V / I$, checks for overload (green OK vs. red OVERLOAD badge), and safely de-energizes the source.
* **`Auto-Gain` Button:** Auto-ranges Lock-in sensitivity before starting the run and updates the UI entry.
* **Scrollable Sidebar:** The left panel includes smooth mousewheel scrolling and a vertical scrollbar, ensuring all controls and diagnostics are accessible on any screen size.

### 4. Running the Sweep
1. Configure parameters and select a **Save Directory**.
2. Click **Test Excitation** to verify signal and overload status.
3. Click **Run Measurement** (or press `Ctrl+Enter`).
4. Monitor live curve plotting ($X$ vs Angle, $Y$ vs Angle, etc.) and execution logs in real time. Pause/Resume and Stop are supported.
