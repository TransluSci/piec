# PIEC Drivers

This directory contains the instrument drivers for the PIEC project. It provides a standardized, object-oriented interface for controlling various laboratory instruments, primarily using SCPI commands via VISA (for now).

## Directory Structure

- **`instrument.py`**: Contains the `Instrument` base class. It handles connection setup and implements the `AutoCheckMeta` framework for automatic parameter validation.
- **`scpi.py`**: Defines the `Scpi` class, which inherits from `Instrument` and implements standard IEEE 488.2 SCPI commands (e.g., `*IDN?`, `*RST`, `*CLS`).
- **`utilities.py`**: Helper functions for parameter conversion and the `PiecManager` for resource management.
- **Subdirectories**: Contain specific driver implementations grouped by instrument type:
    - `awg` (Arbitrary Waveform Generators)
    - `daq` (Data Acquisition)
    - `dmm` (Digital Multimeters)
    - `lockin` (Lock-in Amplifiers)
    - `oscilloscope`
    - `pulser`
    - `rf_source`
    - `sourcemeter`
    - `stepper_motor`

## Usage

### Importing and Initialization

To use a driver, import the specific class for your instrument and instantiate it with the correct address. The address format depends on the instrument type and connection method (e.g., USB, GPIB, TCP).

```python
from piec.drivers.oscilloscope.k_dsox3024a import KeysightDSOX3024a
from piec.drivers.oscilloscope.virtual_oscilloscope import VirtualScope

# Connect to a real instrument via VISA
scope = KeysightDSOX3024a(address='TCPIP0::123.45.67.89::INSTR', check_params=True)

# Connect to a virtual instrument for testing (no hardware required)
scope = VirtualScope()
```

### Key Features

-   **Virtual Instruments**: Dedicated virtual driver classes implement their own state and simulation behavior. The base `Instrument` class does not supply canned SCPI responses.
-   **Parameter Validation**: If `check_params=True` is set during initialization, the `AutoCheckMeta` framework validates method arguments against predefined ranges and lists (e.g., checking if a voltage `vdiv` is within the allowed `vdiv` range defined in the class).
-   **Standard Commands**:
    -   `idn()`: Returns the instrument identification string.
    -   `reset()`: Resets the instrument to default settings (`*RST`).
    -   `clear()`: Clears status and error queues (`*CLS`).

### Creating New Drivers

New drivers should inherit from:
1.  `Scpi` (if the instrument uses SCPI commands).
2.  A generic category class (e.g., `Oscilloscope`) if available.
3.  `Instrument` (directly, if not using SCPI).

Define class attributes (e.g., `vdiv`, `timebase`) to enable automatic parameter validation for the corresponding methods.

See `piec.drivers.oscilloscope.k_dsox3024a` for a working example.
