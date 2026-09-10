# DCIV Measurement Documentation

This document explains the DC Current-Voltage (DCIV) sweep measurement setup, the software architecture behind it, and how to operate the system using the Graphical User Interface (GUI).

## Overview

**DCIV (Current-Voltage)** sweep is a fundamental electrical characterization technique. It involves applying a sequence of DC voltages across a device under test (DUT) and measuring the resulting current at each voltage step. This measurement is crucial for understanding the basic electrical properties of materials and devices, such as resistance, diode characteristics, and breakdown voltage.

### Measurement Process

The measurement ramps the voltage from a starting value (`V Start`) to an ending value (`V Stop`) in a specified number of discrete steps. At each voltage step:
1. The source sets the target voltage.
2. The system waits for a specified `Dwell Time` to allow transients to settle.
3. The current through the device and the actual voltage across it are measured and recorded.

## Hardware Setup

The measurement system relies on a Source Measure Unit (SMU) or Sourcemeter to simultaneously source voltage and measure current.

### The Sourcemeter
The core instrument is a **Sourcemeter** (e.g., Keithley 2400 or a Virtual representation).
*   **Source Mode**: Configured as a voltage source with a user-defined current compliance (limit) to protect the device from excessive current.
*   **Sense Mode**: Can be configured for 2-Wire (standard) or 4-Wire (Kelvin) sensing. 4-Wire sensing is preferred for low-resistance measurements to eliminate the effects of lead resistance.

## Software Architecture

The codebase is structured around the `IVSweep` class, which inherits from `BaseMeasurement` and implements PIEC's standardized measurement lifecycle.

### `IVSweep` Class
*   **Location**: `src/piec/measurement/iv_sweep.py`
*   **Role**: Coordinates the sourcemeter driver, conducts the voltage sweep, publishes bounded snapshots, and manages safe shutdown and atomic persistence.
*   **Target Contract**:
    *   **Zero I/O in `__init__`**: Instrument configuration and queries are deferred to the protected `_configure_instruments` hook.
    *   **Standard Schema**: Schema `iv_sweep`, version 1.
    *   **Plain Column Headers**: `voltage` and `current` (no embedded units in column headers).
    *   **Metadata Units**: JSON-encoded unit mapping `{"voltage": "V", "current": "A"}` stored in `column_units_json`.
*   **Key Lifecycle Methods & Hooks**:
    *   `run_experiment(*, on_update=None, save=True, save_partial=None, options=None)`: Main execution entry point running the full canonical lifecycle and returning the resulting `pandas.DataFrame`.
    *   `_configure_instruments(request)`: Configures the sourcemeter at electrical zero (0.0 V) with output disabled, setting current compliance and sensing mode (2W/4W).
    *   `_capture_data(request, on_update)`: Executes a paced, cancellable pre-ramp from 0.0 V to `v_start`, followed by the voltage sweep with cancellable dwell times and reads. Publishes mutation-isolated snapshots and preserves raw data in memory on interruption.
    *   `_safe_shutdown(recorder)`: Executes paced shutdown back to electrical zero (0.0 V), guarantees that output disable is attempted even if voltage ramping encounters an error, and verifies zero voltage.
    *   `session(*, save=False, save_partial=None, options=None)`: Context manager for interactive scripts and Jupyter notebooks.

## How to Use the GUI

The GUI (`Measurements/DCIV/IV_sweep_GUI.py`) provides an interface for configuring and executing IV sweeps using `MeasurementRunner`.

### 1. Instrument Connection
*   **Sourcemeter Address**: Select the VISA address for the connected sourcemeter or choose `VIRTUAL` for simulation.
*   **Refresh**: Updates the list of available VISA resources.
*   **Sense Mode**: Select between `2W` (standard) and `4W` (Kelvin) sensing.

### 2. Measurement Parameters
*   **V Start (V)**: The initial voltage of the sweep.
*   **V Stop (V)**: The final voltage of the sweep.
*   **Number of Steps**: How many voltage points to measure between V Start and V Stop.
*   **Current Compliance (A)**: The maximum allowable current compliance limit.
*   **Dwell Time (s)**: The settling delay at each step before taking a measurement.

### 3. Running a Measurement
1.  **Configure**: Set all parameters and specify a **Save Directory** (leave empty or default for in-memory only).
2.  **Start**: Click **RUN MEASUREMENT** (or press `Ctrl+Enter`). Execution runs in a dedicated background worker via `MeasurementRunner`.
3.  **Monitor & Control**: 
    *   Live snapshots are published via `DisplayQueue` and plotted in real time.
    *   Click **STOP** to request cooperative software stop; the system safely ramps to 0.0 V and disables output.
    *   Use the plot configuration dropdowns (`voltage`, `current`) to change axes.
    *   The log console displays lifecycle status, verified hardware safety, and published filenames.

## Features Summary

*   **Virtual Hardware Support**: Seamlessly switch between real hardware and virtual sourcemeters.
*   **Guaranteed Hardware Safing**: Attempts output disable even if ramp-down fails, and coordinates safe application shutdown.
*   **Atomic Persistence**: Windows/SMB-aware atomic publication prevents partially written files.
*   **Standardized Schema**: Clean lowercase column headers with canonical unit metadata.
*   **Live Snapshot Visualization**: Real-time display updates decoupled from acquisition execution.
