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

The codebase is structured around the `IVSweep` class, which handles the core measurement logic.

### `IVSweep` Class
*   **Location**: `src/piec/measurement/iv_sweep.py`
*   **Role**: Manages the sourcemeter driver, coordinates the voltage sweep, and handles data collection.
*   **Key Methods**:
    *   `configure_sourcemeter()`: Sets up the voltage source mode, applies current compliance, and sets the sensing mode (2W/4W).
    *   `sweep()`: Executes the voltage ramp. Loops through the target voltages, waits the dwell time, measures both V and I, and stores the results in a pandas DataFrame.
    *   `save_data()`: Exports the measurement data and metadata to a CSV file.
    *   `run_experiment()`: The main entry point that configures the instrument, runs the sweep, turns off the output, and saves the data.

## How to Use the GUI

The GUI (`Measurements/DCIV/IV_sweep_GUI.py`) provides an intuitive interface for configuring and executing IV sweeps.

### 1. Instrument Connection
*   **Sourcemeter Address**: A dropdown menu allows you to select the VISA address for the connected sourcemeter.
*   **Virtual Mode**: Select `VIRTUAL` to run a simulation without connected hardware.
*   **Refresh**: Updates the list of available VISA resources.
*   **Sense Mode**: Select between `2W` and `4W` sensing.

### 2. Measurement Parameters
*   **V Start (V)**: The initial voltage of the sweep.
*   **V Stop (V)**: The final voltage of the sweep.
*   **Number of Steps**: How many voltage points to measure between V Start and V Stop.
*   **Current Compliance (A)**: The maximum allowable current. If the device attempts to draw more current, the sourcemeter will limit it to this value.
*   **Dwell Time (s)**: The delay at each step before taking a measurement, allowing the system to stabilize.

### 3. Running a Measurement
1.  **Configure**: Set all parameters and specify a **Save Directory**.
2.  **Start**: Click **Run Measurement** (or press `Ctrl+Enter`).
3.  **Monitor**: 
    *   The plot will update with the data once the sweep is complete.
    *   Use the plot configuration dropdowns to change the X and Y axes (e.g., plot Current vs. Voltage).
    *   Console output will display the status of the sweep and confirm when data is saved.

## Features Summary

*   **Virtual Hardware Support**: Seamlessly switch between real hardware and virtual drivers for testing.
*   **Safety**: Enforces current compliance limits to protect sensitive devices.
*   **Data Management**: Automatically saves data and metadata to CSV files.
*   **Dynamic Plotting**: Easily visualize the collected Current-Voltage characteristics.
