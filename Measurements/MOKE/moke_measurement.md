# MOKE Measurement Documentation

This document explains the Magneto-Optic Kerr Effect (MOKE) measurement setup, the software architecture behind it, and how to operate the system using both the Jupyter Notebook and the Graphical User Interface (GUI).

## Overview

The **Magneto-Optic Kerr Effect (MOKE)** measures changes in the polarization or intensity of light reflected from a magnetized surface to trace optical hysteresis loops. By sweeping an applied magnetic field $H$ and recording the optical detector voltage, MOKE characterizes key magnetic properties such as coercivity ($H_c$), remanence, and switching width across three standard optical geometries:
*   **Longitudinal**: Probes magnetization in the plane of the sample and parallel to the plane of incidence.
*   **Polar**: Probes the out-of-plane magnetization component.
*   **Transverse**: Probes the in-plane magnetization component perpendicular to the plane of incidence.

### Measurement Process & Bipolar Triangle Sweep

Each MOKE cycle sweeps the magnetic field along a closed bipolar triangle waveform:

$$0 \rightarrow +H_{\max} \rightarrow 0 \rightarrow -H_{\min} \rightarrow 0$$

Two acquisition modes are supported:
1.  **Stepped Mode**: Commands each discrete field point (`points_per_cycle` points per cycle) along the triangle waveform via `set_field()`, waits `dwell_time` (and optionally verifies that the measured field settles within `field_tolerance` when a gaussmeter is enabled), and records the optical voltage and field.
2.  **Continuous Mode**: Acquires `round(cycle_period * sample_rate)` raw input samples per cycle along the triangle waveform—either via timed `set_field()` steps with direct instruments or via hardware-paced DAQ waveform output (`write_AO_scan` at `ao_sample_rate`) and synchronized analog input scanning (`read_AI_scan` at `sample_rate`) when using shared DAQ emulators—and block-averages (downsamples) each completed cycle onto the `points_per_cycle` grid for cycle averaging.

When multiple cycles are requested (`cycles >= 1`, after optional `discard_cycles`), completed cycles are averaged point-by-point around the full closed hysteresis loop and saved alongside the raw cycle data.

## Hardware Setup

Every MOKE experiment uses two primary instruments and one optional field monitor:

1.  **Field Controller (`field_controller`)**: Sets the applied magnetic field in Oersted (Oe) (`FieldController` or `VirtualFieldController`).
2.  **Digital Multimeter (`dmm`)**: Measures the optical signal voltage from the photodiode or balanced photodetector bridge (`DMM` or `VirtualDMM`).
3.  **Gaussmeter (`gaussmeter`, Optional)**: Measures the actual magnetic field in Oersted (`Gaussmeter` or `VirtualGaussmeter`). When omitted (`None`), the measurement records the field controller's calibrated setpoint estimate.

### Optional DAQ and Source Emulators

For setups where an electromagnet power supply and photodetector are driven through a multi-channel DAQ board (such as an MCC `USB1208HS` or `USB231`) or a standard sourcemeter/calibrator rather than standalone field controllers, PIEC provides emulator adapters in `piec.drivers.emulators`:
*   `DaqFieldController(daq, ao_channel, gain=100.0, offset=0.0, ao_sample_rate=1000.0)`: Wraps a DAQ analog output channel as a `FieldController` (with hardware-paced triangle waveform output via `write_AO_scan` at `ao_sample_rate` in continuous mode).
*   `DaqAsDMM(daq, ai_channel)`: Wraps a DAQ analog input channel as a `DMM`.
*   `DaqAsGaussmeter(daq, ai_channel, gain=100.0, offset=0.0)`: Wraps a DAQ analog input channel connected to a Hall probe or field monitor output as a `Gaussmeter`.
*   `SourceAsFieldController(source_instrument, set_value, gain=..., offset=0.0)`: Wraps a DC calibrator or sourcemeter output as a `FieldController`.

### Shared MCC DAQ lab wiring (USB-1208HS / USB-231)

The MOKE GUI defaults to **DIFF** for the shared DAQ in both stepped and continuous modes. Under **Connection Setup → DAQ channels**, use the logical AI numbers shown below. Each differential voltage is the positive terminal voltage minus the negative terminal voltage.

The input dropdowns show the fixed terminal pairs in **DIFF** and the individual AIN terminals in **SE**. Select **Unassigned** for unused inputs. Switching to **DIFF** clears any selections above logical AI3.

| Geometry | Magnet output | Field monitor | Photodiode |
|---|---|---|---|
| Longitudinal | AO0 | AI0 (AIN0 − AIN1) | AI2 (AIN4 − AIN5) |
| Polar | AO1 | AI1 (AIN2 − AIN3) | AI3 (AIN6 − AIN7) |

In a notebook, call `daq.set_input_mode("DIFF")` after connecting the DAQ (`USB1208HS` or `USB231`) and before creating the DAQ adapters. For single-ended wiring, select **SE** in the GUI or pass `"SE"` to `set_input_mode()`. In SE mode, logical AI3 reads AIN3 relative to AGND.

For continuous shared-DAQ runs, `DaqFieldController` configures the output waveform clock (`ao_sample_rate`, default `1,000 Hz` under **Connection Setup → DAQ channels**), while `MOKE` configures the input acquisition clock (`sample_rate`, default `10,000 Hz`). With the default `0.2 s` cycle period, `ao_sample_rate=1000` on `DaqFieldController`, `sample_rate=10000`, and `points_per_cycle=200` on `MOKE`, each cycle generates `200` AO points (`50` per quarter-cycle), acquires `2,000` raw AI samples per channel, and averages onto `200` points per cycle ($10\times$ downsample).

## Software Architecture

The codebase is structured around the `MOKE` measurement class and the 3-level `magnetic_material` simulation package.

### `MOKE` Class
*   **Location**: `src/piec/measurement/moke.py`
*   **Inherits from**: `Experiment`
*   **Role**: Coordinates the field controller, optical DMM, and optional gaussmeter across stepped or continuous triangle sweeps, computes cycle averages, and safely zeroes the field on completion or interruption.
*   **Key Methods**:
    *   `run_experiment(save=True)`: Main public entry point that validates parameters, runs stepped (`_stepped()`) or continuous (`_continuous()` / `_daq_continuous()`) acquisition, zeroes the field in a `finally` block, and saves the data.
    *   `save_data()`: Writes the raw cycle data CSV and, when at least one cycle is completed, the cycle-averaged `_average.csv` file with experiment and instrument metadata.
    *   `safe_close()`: Commands `0.0 Oe` on the field controller without resetting shared input hardware.
    *   `request_pause()`, `request_resume()`, `request_stop()`: Thread-safe controls used by the GUI to pause, resume, or stop an active acquisition.

### `MagneticMaterial` & `ArctanMOKE` Simulation
*   **Location**: `src/piec/simulation/magnetic_material/`
*   **Role**: `MagneticMaterial` (`magnetic_material.py`) defines the Level-2 magnetic sample skeleton (`set_field`, `get_magnetization`, `get_moke_voltage`, `get_resistance`), and `ArctanMOKE` (`arctan_moke.py`) implements the Level-3 noiseless analytical arctan hysteresis loop used by `VirtualFieldController`, `VirtualDMM`, and `VirtualGaussmeter`.

## How to Use the Notebook

The Jupyter Notebook (`Measurements/MOKE/MOKE_testing.ipynb`) provides an interactive step-by-step interface for running virtual or physical MOKE measurements.

1.  **Imports**: Load `MOKE`, virtual or physical drivers (`VirtualFieldController`, `VirtualDMM`, `VirtualGaussmeter`), and `ArctanMOKE`.
2.  **Instrument Setup**:
    *   **Virtual**: Instantiate `VirtualFieldController('VIRTUAL')`, `VirtualDMM('VIRTUAL')`, and optional `VirtualGaussmeter('VIRTUAL')` connected to an `ArctanMOKE` sample.
    *   **Physical**: Instantiate your `FieldController`, `DMM`, and optional `Gaussmeter` (or uncomment the DAQ / source emulator setup cells to wrap an MCC DAQ or sourcemeter).
3.  **Configuration & Execution**:
    ```python
    experiment = MOKE(
        field_controller=field_controller,
        dmm=dmm,
        gaussmeter=gaussmeter,  # or None if no gaussmeter is used
        geometry='longitudinal',
        mode='stepped',
        field_min=-500.0,
        field_max=500.0,
        points_per_cycle=200,
        cycles=3,
        discard_cycles=1,
        dwell_time=0.01,
        save_dir='scratch',
    )
    experiment.run_experiment()
    ```
4.  **Analysis**: Load the saved raw and cycle-averaged CSV files with `standard_csv_to_metadata_and_data` and plot `signal (V)` vs. `field (Oe)`.

## How to Use the GUI

From the repository root, launch the GUI (`Measurements/MOKE/moke_GUI.py`):

```console
python Measurements/MOKE/moke_GUI.py
```

### 1. Instrument Connection
*   **Field Controller & DMM**: Select the VISA/instrument address for the **Field Controller** and optical **DMM** from the dropdown menus (or leave as `VIRTUAL` for ideal noiseless simulation).
*   **Use Gaussmeter**: Check **Use gaussmeter** to enable the optional **Gaussmeter** address selector and record measured field values; leave it unchecked to use the field controller's calibrated setpoint estimate.
*   **Refresh & Autodetect**: Refresh available resources or automatically match connected instruments.
*   **Connection Setup... (Optional Emulators)**: Open **Connection Setup...** to map roles to shared DAQ channels (`DaqFieldController`, `DaqAsDMM`, `DaqAsGaussmeter`) or a current/voltage source (`SourceAsFieldController`) when not using standalone instruments.

### 2. Measurement Parameters
*   **Geometry & Mode (Static Setup)**: Select `longitudinal`, `polar`, or `transverse` geometry and `stepped` or `continuous` acquisition mode. The input panel dynamically switches between **STEPPED INPUTS** (`Point dwell (s)`, plus `Field tolerance (Oe)` and `Settling timeout (s)` when **Use gaussmeter** is enabled) and **CONTINUOUS INPUTS** (`Cycle period (s)` and `Input sample rate (Hz)`).
*   **Field amplitude (Oe)**: Symmetric magnetic field amplitude ($\pm H_{\max}$) for the bipolar triangle cycle (`0 -> +H_max -> 0 -> -H_max -> 0`).
*   **Points per cycle / average**: Number of field steps per cycle in `stepped` mode, and the number of block-averaged (downsampled) points per cycle in `continuous` mode (where raw input samples per cycle are determined by `Cycle period * Input sample rate`).
*   **Cycles to average & Discard initial cycles**: Number of steady-state hysteresis loops to average and number of initial conditioning loops to exclude from the average.

### 3. Running a Measurement
1.  **Configure**: Set the sweep parameters and select a **Save Directory**.
2.  **Start**: Click **Run** to begin acquisition.
3.  **Monitor & Plot Configuration**: Switch between **Cycle average**, **Most recent cycle**, and **Live signal** views in real time, and select any combination of **X-axis** and **Y-axis** arrays (`field (Oe)`, `time (s)`, `requested field (Oe)`, `signal (V)`) during or after acquisition.
4.  **Control**: Use **Pause/Resume** or **Stop** at any time; stopping safely returns the field controller to `0.0 Oe` and saves the collected data.

## Features Summary

*   **Standard Instrument Abstraction**: Built directly around `FieldController`, `DMM`, and optional `Gaussmeter` interfaces, with drop-in DAQ and source emulators when needed.
*   **Stepped & Continuous Bipolar Triangle Sweeps**: Consistent `0 -> +H_max -> 0 -> -H_min -> 0` waveform across both stepped and continuous modes.
*   **Ideal Virtual Simulation**: Uses the Level-3 `ArctanMOKE` model (`piec.simulation.magnetic_material`) for clean, noiseless hysteresis loops in simulation mode.
*   **Cycle Averaging & CSV Export**: Automatically saves both raw multi-cycle data and point-by-point cycle-averaged hysteresis loops with full experiment and instrument metadata.
*   **Safe Shutdown**: Always returns the magnetic field setpoint to zero after completion or abort.
