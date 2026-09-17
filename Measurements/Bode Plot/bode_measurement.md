# Bode Plot Measurement Documentation

This document explains the frequency response (Bode plot) measurement setup, the software architecture behind it, and how to operate the system using the Graphical User Interface (GUI).

## Overview

A **Bode plot** characterizes a device's frequency response by sweeping a sine wave across a range of frequencies and recording the gain (magnitude, in dB) and phase shift (in degrees) between the device's input and output at each frequency. It's the standard way to characterize amplifiers, filters, and other linear circuits.

### Measurement Process

The measurement sweeps a sine wave in log-spaced frequency steps from `f_start` to `f_stop`. At each step:
1. The AWG is retuned to the target frequency.
2. The oscilloscope captures the device's input and output **simultaneously**, from the same trigger event.
3. Both channels are correlated against sin/cos references at the drive frequency (a single-bin DFT / lock-in technique) to get each channel's complex amplitude.
4. Gain (`20*log10(|Vout|/|Vin|)`) and phase (`angle(Vout/Vin)`) are computed directly from that ratio.

Because gain/phase come from the two simultaneously-sampled channels rather than from the AWG's commanded amplitude, the result is immune to AWG output-level drift or source/load impedance mismatches.

Each channel's oscilloscope range is also **autoranged** by default: after every point, the range for the *next* point is resized based on the peak amplitude just measured (targeting a healthy margin above it, not a bare-minimum fit). This matters because a filter/amplifier's output can span a huge dynamic range across a sweep (a few dB near DC, tens of dB down past the rolloff) — a single fixed range sized for the passband would leave the attenuated end buried in ADC quantization noise. Autoranging can be turned off in the GUI if you want one fixed range for the whole sweep.

## Hardware Setup

*   **AWG**: Any `Awg`-category VISA driver (e.g. Rigol DG812) drives the device under test's input. Selectable from a dropdown in the GUI.
*   **Oscilloscope**: Any `Oscilloscope`-category driver that supports simultaneous dual-channel capture — currently that's the Digilent Analog Discovery 2 (`AnalogDiscovery2Oscilloscope`), which samples all enabled channels off one shared ADC clock. This is a hard requirement for the phase measurement: if you pick a scope driver without that capability, `FrequencyResponse` raises a clear error rather than silently producing a bogus (or crashing) measurement. Adding support for another scope means implementing a `get_multi_channel_data(channels)` method on its driver — see `AnalogDiscovery2Oscilloscope` in `src/piec/drivers/oscilloscope/analog_discovery_2.py` for the pattern.

### Wiring

```
AWG CH<awg_channel>       --> device under test (DUT) input
Scope CH<input_channel>   -- probes the DUT INPUT (same node the AWG drives)
Scope CH<output_channel>  -- probes the DUT OUTPUT
```

Wiring both scope channels to input and output (rather than just the output) is what makes the phase measurement possible and the gain measurement independent of the AWG's actual output level.

### Bandwidth limits

These depend on whichever AWG/scope models you pick. For the DG812 + AD2 pairing specifically: the DG812 tops out at 25 MHz sine, and the AD2's scope inputs are rated to ~30 MHz analog bandwidth, so a sweep can't usefully go past ~25 MHz even if a target/simulation curve extends further.

## Software Architecture

The codebase is structured around the `FrequencyResponse` class, which handles the core measurement logic.

### `FrequencyResponse` Class
*   **Location**: `src/piec/measurement/frequency_response.py`
*   **Role**: Manages the AWG and oscilloscope drivers, coordinates the frequency sweep, and handles data collection.
*   **Key Methods**:
    *   `configure_awg()` / `configure_scope()`: Set up the sine output and the input/output scope channels.
    *   `measure_point(frequency)`: Drives one frequency and returns the complex, simultaneously-measured input/output amplitudes.
    *   `sweep()`: Executes the full log-spaced frequency sweep, computing gain/phase at each point and unwrapping the phase trace at the end.
    *   `save_data()`: Exports the measurement data and metadata to a CSV file.
    *   `run_experiment()`: The main entry point that configures the instruments, runs the sweep, turns off the output, and saves the data.

### Plotting

`piec.analysis.frequency_response.plot_bode()` renders the standard stacked magnitude(dB)/phase(deg)-vs-log-frequency Bode plot from a `FrequencyResponse.data` DataFrame.

## How to Use the GUI

The GUI (`Measurements/Bode Plot/bode_plot_GUI.py`) provides an interface for configuring and executing a Bode sweep.

### 1. Instrument Connection

*   **AWG Model**: A dropdown of supported AWG drivers (Rigol DG812/DG1000(Z)/DG4000, Agilent 33220A/33500, Keysight 81150A, Siglent SDG2000X). Picking a model just selects which driver class gets instantiated — the address field always uses VISA for these.
*   **AWG Address**: A dropdown of detected VISA resources. Click **Refresh** if the AWG isn't listed yet.
*   **Oscilloscope Model**: A dropdown of supported oscilloscope drivers. Selecting **Analog Discovery 2 (WaveForms)** swaps the address field below to a WaveForms device-index entry (`-1` = first device found); selecting any other model swaps it back to a VISA-address dropdown. Only the Analog Discovery 2 currently supports the simultaneous dual-channel capture this measurement needs (see Hardware Setup) — picking another model will fail with a clear error when you try to run.
*   **Oscilloscope Address**: VISA address or WaveForms device index, depending on the model selected above.
*   This GUI requires real hardware for both instruments — there's no "VIRTUAL" option, since the phase measurement fundamentally needs a real simultaneous dual-channel capture that the generic virtual scope doesn't simulate.

> **Note**: Only one process can hold the Analog Discovery 2 open at a time. Close the WaveForms desktop application before running this GUI.

### 2. Measurement Parameters
*   **AWG Channel / Input Scope Channel / Output Scope Channel**: Which physical channels are wired where (see Wiring above).
*   **Start / Stop Frequency (Hz)**: The sweep range.
*   **Points per Decade**: Log-spaced point density (10 is a reasonable default for a smooth curve).
*   **Drive Amplitude (Vpp)**: The AWG's commanded sine amplitude.
*   **Input / Output Ch Start Range (V)**: The oscilloscope's full-scale vertical range for each channel at the start of the sweep. With autoranging on (default), this is just a starting point — the range updates automatically as the sweep progresses. With autoranging off, this is the fixed range for the entire sweep, so it needs enough headroom to avoid clipping across your DUT's whole expected output swing.
*   **Autorange channels during sweep**: Toggles the per-point autoranging described above.

### 3. Running a Measurement
1.  **Configure**: Set all parameters and specify a **Save Directory**.
2.  **Start**: Click **Run Measurement** (or press `Ctrl+Enter`).
3.  **Monitor**: The Bode plot (magnitude on top, phase on bottom) updates live as each frequency point is measured. Use **Pause**/**Stop** to control a running sweep.
4.  Console output logs progress and confirms when data is saved.

## Features Summary

*   **Phase-accurate dual-channel measurement**: Input and output are sampled from the same trigger event, not two separate acquisitions.
*   **Live Plotting**: Watch the Bode curve build point-by-point during a long sweep.
*   **Data Management**: Automatically saves data and metadata to CSV files, in the same format used across piec's other measurements.
