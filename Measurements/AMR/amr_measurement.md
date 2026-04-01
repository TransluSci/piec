# AMR Measurement Documentation

This document explains the Anisotropic Magnetoresistance (AMR) measurement setup, the software architecture behind it, and how to operate the system using both the Jupyter Notebook and the Graphical User Interface (GUI).

## Overview

**Anisotropic Magnetoresistance (AMR)** is a property of ferromagnetic materials where the electrical resistance depends on the angle between the current direction and the magnetization direction. This setup measures the resistance of a sample while rotating it in a magnetic field.

### Theory (AMR Equation)

The resistance $R(\theta)$ of a ferromagnetic material depends on the angle $\theta$ between the current density $J$ and the magnetization $M$ according to the relation:

$$R(\theta) = R_{\perp} + (R_{\parallel} - R_{\perp}) \cos^2(\theta)$$

where:
*   $R_{\parallel}$ corresponds to the resistance when the magnetization is parallel to the current ($\theta = 0^\circ$).
*   $R_{\perp}$ corresponds to the resistance when the magnetization is perpendicular to the current ($\theta = 90^\circ$).

Using the trigonometric identity $\cos^2(\theta) = \frac{1 + \cos(2\theta)}{2}$, this can be rewritten as:

$$R(\theta) = R_{avg} + \Delta R \cos(2\theta)$$

where $R_{avg} = \frac{R_{\parallel} + R_{\perp}}{2}$ is the average resistance, and $\Delta R = \frac{R_{\parallel} - R_{\perp}}{2}$ is the amplitude of the AMR effect.

### Data Fitting

To extract the AMR amplitude and other parameters, experimental data (Resistance vs. Angle) is typically fitted to the following function:

$$y = A + B \cos(2(\theta - \theta_0))$$

where:
*   $A$ represents the average resistance ($R_{avg}$).
*   $B$ represents the AMR amplitude ($\Delta R$).
*   $\theta$ is the angle of the applied external magnetic field.
*   $\theta_0$ accounts for any angular misalignment between the sample drive and the magnetic field axis.

In a sufficiently strong magnetic field, the magnetization $M$ aligns with the external field direction, making the measured angle $\theta$ accurately reflect the magnetization angle.

## Hardware Setup & Feedback Loop

The measurement system relies on a feedback loop to accurately set and verify the magnetic field applied to the sample.

### The Feedback Loop
1.  **Field Setting (Source)**: The **DC Calibrator** (`EDC522` or Virtual) is used to drive the **Custom Magnet**. It outputs a specific voltage that corresponds to the desired magnetic field strength (Oersted).
    *   *Conversion:* The software uses a calibration factor (default `10000 Oe/V`) to convert the desired field into a voltage command for the calibrator. (This is dependant on actual hardware configuration but it is the default)
2.  **Field Sensing (Readout)**: A **Hall Sensor** measures the actual magnetic field produced by the magnet. This sensor's output is read by the **Digital Multimeter (DMM)** (`Keithley193a` or Virtual).
3.  **Verification**: After setting the field, the software waits for the magnet to stabilize, reads the voltage from the DMM, converts it back to field units, and verifies it matches the target within a tolerance (default 10%).

### Other Components
*   **Stepper Motor**: Rotates the sample relative to the magnetic field.
*   **Lock-in Amplifier**: Measures the small resistance changes (voltage drop) across the sample with high precision, typically using AC excitation to improve signal-to-noise ratio.

## Software Architecture

The codebase is structured around a parent class `MagnetoTransport` and a specific implementation `AMR`.

### `MagnetoTransport` Class
*   **Location**: `src/piec/measurement/magneto_transport.py`
*   **Role**: Manages core instrument connections and the magnetic field feedback loop.
*   **Key Methods**:
    *   `initialize()`: Checks communication with all instruments.
    *   `set_field()`: Orchestrates the Calibrator -> DMM feedback loop described above.
    *   `shut_off()`: Safely turns off the magnetic field (sets calibrator to 0V).

### `AMR` Class
*   **Location**: `src/piec/measurement/magneto_transport.py`
*   **Inherits from**: `MagnetoTransport`
*   **Role**: Manages the specific details of the AMR experiment.
*   **Key Methods**:
    *   `configure_lockin()`: Sets up the lock-in amplifier (reference frequency, gain, etc.).
    *   `capture_data()`: Loops through the specified angles, moves the stepper motor, and triggers data capture.
    *   `capture_data_point()`: Reads the averaged X/Y signals from the lock-in for a set duration.
    *   `save_data_point()`: Saves measurements to a CSV file.

## How to Use the Notebook

The Jupyter Notebook (`notebooks/amr.ipynb`) provides a step-by-step interface for running experiments, especially useful for debugging or manual control.

1.  **Imports**: Load necessary drivers and the `AMR` class.
    ```python
    from piec.measurement.magneto_transport import AMR
    from piec.drivers.dmm.keithley193a import Keithley193a
    # ... other imports
    ```
2.  **Instrument Setup**:
    *   **Autodetect**: Use `autodetect('dmm')`, etc., to find connected instruments.
    *   **Manual**: If autodetection fails (common for Arduino/Calibrator), manually instantiate them with their address (e.g., `GPIB0::9::INSTR`).
    *   **Virtual**: Use `VirtualDMM()`, etc., for testing without hardware.
3.  **Configuration**: Define experiment parameters.
    ```python
    experiment = AMR(dmm=dmm, calibrator=calibrator, ..., field=100, angle_step=5, ...)
    ```
4.  **Execution**: Run the measurement loop.
    ```python
    experiment.run_experiment()
    ```
5.  **Analysis**: The notebook includes cells to load the generated CSV data using `pandas` and plot it with `matplotlib`.

## How to Use the GUI

The GUI (`guis/amr_GUI.py`) offers a user-friendly way to configure and run measurements without writing code.

### 1. Instrument Connection
*   **Address Selection**: Dropdown menus allow you to select the VISA address for each instrument (DMM, Calibrator, Stepper, Lock-in).
*   **Virtual Mode**: Select `VIRTUAL` to run a simulation.
*   **Refresh**: Updates the list of available VISA resources.
*   **Autodetect**: Attempts to automatically identify connected instruments and select their addresses.
*   **Test Stepper**: Verifies communication with the Arduino stepper motor.

### 2. Measurement Parameters (Dynamic Inputs)
*   **Magnetic Field (Oe)**: Target field strength.
*   **Angle Step (deg)**: Increment size for rotation.
*   **Total Angle (deg)**: Total range of rotation (e.g., 360).
*   **Lock-in Settings**: Amplitude, Frequency, Sensitivity, and Initialize checkbox.
*   **Measure Time (s)**: Duration to average data at each angle.

### 3. Running a Measurement
1.  **Configure**: Set all parameters and select a **Save Directory**.
2.  **Start**: Click **Run Measurement** (or press `Ctrl+Enter`).
3.  **Monitor**:
    *   **Real-time Plot**: The graph updates automatically as new data points are acquired. You can change X/Y axes (e.g., Angle vs X, Field vs Y) on the fly.
    *   **Console**: Displays status messages ("capturing data at angle...", "Data point saved...").
4.  **Control**: Use **Pause/Resume** to temporarily halt the experiment or **Stop** to abort it.

## Features Summary

*   **Autodetection**: Automatically finds supported instruments on the VISA bus.
*   **Hardware Abstraction**: Seamlessly switch between real hardware and virtual drivers for testing.
*   **Real-time Visualization**: Watch the hysteresis loop or resistance curve build up in real-time.
*   **Data Management**: Automatically saves data and metadata to CSV files with timestamps.
*   **Safety**: Includes `shut_off` procedures to ensure the magnet is powered down after experiments.
