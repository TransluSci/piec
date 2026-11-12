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
2.  **Continuous Mode**: Acquires `round(cycle_period * sample_rate)` raw samples per cycle along the triangle waveform—either via timed `set_field()` steps with direct instruments or via hardware-paced DAQ waveform output (`write_AO_scan`) and synchronized analog input scanning (`read_AI_scan`) when using shared DAQ emulators—and interpolates each completed cycle onto the `points_per_cycle` grid for cycle averaging.

When multiple cycles are requested (`cycles >= 1`, after optional `discard_cycles`), completed cycles are averaged point-by-point around the full closed hysteresis loop and saved alongside the raw cycle data.

## Hardware Setup

Every MOKE experiment uses two primary instruments and one optional field monitor:

1.  **Field Controller (`field_controller`)**: Sets the applied magnetic field in Oersted (Oe) (`FieldController` or `VirtualFieldController`).
2.  **Digital Multimeter (`dmm`)**: Measures the optical signal voltage from the photodiode or balanced photodetector bridge (`DMM` or `VirtualDMM`).
3.  **Gaussmeter (`gaussmeter`, Optional)**: Measures the actual magnetic field in Oersted (`Gaussmeter` or `VirtualGaussmeter`). When omitted (`None`), the measurement records the field controller's calibrated setpoint estimate.

### Optional DAQ and Source Emulators

For setups where an electromagnet power supply and photodetector are driven through a multi-channel DAQ board (such as an MCC `USB1208HS` or `USB231`) or a standard sourcemeter/calibrator rather than standalone field controllers, PIEC provides emulator adapters in `piec.drivers.emulators`:
*   `DaqFieldController(daq, ao_channel, gain=100.0, offset=0.0)`: Wraps a DAQ analog output channel as a `FieldController` (with hardware-paced triangle waveform output via `write_AO_scan` in continuous mode).
*   `DaqAsDMM(daq, ai_channel)`: Wraps a DAQ analog input channel as a `DMM`.
*   `DaqAsGaussmeter(daq, ai_channel, gain=100.0, offset=0.0)`: Wraps a DAQ analog input channel connected to a Hall probe or field monitor output as a `Gaussmeter`.
*   `SourceAsFieldController(source_instrument, set_value, gain=..., offset=0.0)`: Wraps a DC calibrator or sourcemeter output as a `FieldController`.

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
*   **Geometry**: `longitudinal`, `polar`, or `transverse` (saved in measurement metadata).
*   **Acquisition Mode**: `stepped` (discrete field points with `Dwell Time (s)`) or `continuous` (timed triangle sweep with `Cycle Period (s)` and `Sample Rate (Hz)`).
*   **Field Min / Field Max (Oe)**: Lower and upper magnetic field limits for the bipolar triangle cycle.
*   **Points / Cycle**: Number of field steps per cycle in `stepped` mode, and the number of points in the phase-interpolated cycle average in `continuous` mode (where raw samples per cycle are determined by `Cycle Period * Sample Rate`).
*   **Cycles & Discard Cycles**: Number of measured hysteresis loops to average and number of initial conditioning loops to exclude from the average.

### 3. Running a Measurement
1.  **Configure**: Set the sweep parameters and select a **Save Directory**.
2.  **Start**: Click **Run** to begin acquisition.
3.  **Monitor**: Switch between **Cycle average**, **Latest cycle**, and **Live signal** views in real time.
4.  **Control**: Use **Pause/Resume** or **Stop** at any time; stopping safely returns the field controller to `0.0 Oe` and saves the collected data.

## Features Summary

*   **Standard Instrument Abstraction**: Built directly around `FieldController`, `DMM`, and optional `Gaussmeter` interfaces, with drop-in DAQ and source emulators when needed.
*   **Stepped & Continuous Bipolar Triangle Sweeps**: Consistent `0 -> +H_max -> 0 -> -H_min -> 0` waveform across both stepped and continuous modes.
*   **Ideal Virtual Simulation**: Uses the Level-3 `ArctanMOKE` model (`piec.simulation.magnetic_material`) for clean, noiseless hysteresis loops in simulation mode.
*   **Cycle Averaging & CSV Export**: Automatically saves both raw multi-cycle data and point-by-point cycle-averaged hysteresis loops with full experiment and instrument metadata.
*   **Safe Shutdown**: Always returns the magnetic field setpoint to zero after completion or abort.
