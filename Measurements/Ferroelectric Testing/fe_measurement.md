# Ferroelectric Measurement Documentation

This document explains the Ferroelectric measurement setup, the software architecture handling arbitrary waveforms, and how to operate the system using the Graphical User Interface (GUI) and Jupyter Notebook.

## Overview

Ferroelectric measurements involve characterizing the polarization response of a material to applied electric fields. The system currently supports two primary measurement techniques: **Hysteresis Loops** and **Three-Pulse PUND**.

### Hysteresis Loop
*   Applies a multi-cycle bipolar triangular voltage waveform.
*   Measures the resulting current to calculate the Polarization-Voltage (P-V) loop.
*   Useful for observing the macroscopic ferroelectric switching behavior, coercive field, and saturation polarization.

### Three-Pulse PUND (Positive-Up-Negative-Down)
*   Applies a specific sequence of discrete voltage pulses: a reset pulse, followed by two measurement pulses (e.g., Positive and Up).
*   By subtracting the non-switching response (second pulse) from the total response (first pulse), the true remanent switched polarization can be extracted, mitigating the effects of leakage current and parasitic capacitance.

## Hardware Setup

The measurement system relies on high-speed waveform generation and capture to properly measure transient switching currents.

### Instruments
1.  **Arbitrary Waveform Generator (AWG)** (e.g., Keysight 81150a or Virtual): Generates the precise voltage profiles (triangular waves or pulse trains) needed to drive the sample.
2.  **Oscilloscope** (e.g., Keysight DSOX3024a or Virtual): Captures the high-speed time-varying voltage and current signals from the device.

## Software Architecture

The codebase utilizes a parent class `DiscreteWaveform` to handle general instrument coordination, with subclasses for specific measurement types.

### `DiscreteWaveform` Class
*   **Location**: `src/piec/measurement/discrete_waveform.py`
*   **Role**: Base class managing the AWG and Oscilloscope feedback loop, triggering, and data capture.
*   **Key Methods**:
    *   `initialize_awg()` / `configure_oscilloscope()`: Sets up the core communication, impedance matching, and trigger settings.
    *   `apply_and_capture_waveform()`: Arms the oscilloscope, triggers the AWG output, and reads back the time-voltage data.
    *   `run_experiment()`: Executes the full workflow (configure, capture, save, analyze).

### `HysteresisLoop` Class
*   **Inherits from**: `DiscreteWaveform`
*   **Role**: Manages the specific details of a triangular wave hysteresis measurement.
*   **Key Methods**:
    *   `configure_awg()`: Constructs a dense representation of the multi-cycle triangle wave and loads it into the AWG's arbitrary memory.
    *   `analyze()`: Processes the raw current data, integrates to find polarization, and generates P-V plots.

### `ThreePulsePund` Class
*   **Inherits from**: `DiscreteWaveform`
*   **Role**: Manages the PUND pulse train generation and analysis.
*   **Key Methods**:
    *   `configure_awg()`: Constructs the complex sequence of resets and pulses (with specified delays and widths) and loads it into the AWG.
    *   `analyze()`: Calculates the switched charge by analyzing the difference between switching and non-switching current transients.

## How to Use the Notebook

The Jupyter Notebook (`Measurements/Ferroelectric Testing/FE_testing.ipynb`) offers an interactive environment for running experiments and analyzing data manually. It is particularly useful for custom pulse sequences and bespoke data processing beyond the standard GUI capabilities.

## How to Use the GUI

The GUI (`Measurements/Ferroelectric Testing/FE_testing_GUI.py`) provides a robust interface for executing standard measurement types without writing code.

### 1. Instrument Setup & Global Parameters
*   **AWG & Osc Address**: Select the VISA addresses or choose `VIRTUAL` for testing.
*   **Oscilloscope V/div**: Set the vertical scale (volts per division) for the oscilloscope capture.
*   **Sample Area (m^2)**: Essential for accurately converting integrated charge into polarization density (${\mu}C/cm^2$).
*   **Time Offset (ns)** / Automatic: Re-aligns the captured oscilloscope trace with the generated AWG signal.

### 2. Measurement Selection
Use the **Measurement Type** dropdown to select the experiment. The dynamic input panel will change accordingly:

#### Hysteresis Loop Inputs:
*   **Frequency (Hz)**: The repetition rate of the triangle wave.
*   **Amplitude (V) & Offset (V)**: The peak voltage and DC bias of the signal.
*   **Number of Cycles**: Typically set to >1 to capture a stabilized loop after initial wake-up.

#### Three-Pulse PUND Inputs:
*   **Reset Amp (V) & Width (s)**: Configuration for the pre-conditioning pulse.
*   **P/U Amp (V) & Width (s)**: Configuration for the measurement (switching and non-switching) pulses.
*   **Delays**: Wait times between the respective pulses to allow for relaxation.

### 3. Running & Monitoring
*   Click **Run Measurement** (or `Ctrl+Enter`).
*   The oscilloscope trace will be captured, saved, and analyzed automatically.
*   The interactive plot allows you to view different data dimensions (e.g., Time vs. Voltage, Time vs. Current, Applied Voltage vs. Polarization).

## Features Summary

*   **Virtual Mode**: Full hardware abstraction for offline testing of pulse sequences.
*   **Dynamic Inputs**: GUI seamlessly adapts to the parameters required by the selected measurement type.
*   **Automated Analysis**: Automatically processes raw oscilloscope captures into meaningful physical properties like Polarization.
*   **Keyboard Shortcuts**: Fast switching between measurement types (`Ctrl+1`, `Ctrl+2`).
