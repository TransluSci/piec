# Instrument Driver Development Guide

This guide outlines the strict requirements and conventions for creating new instrument drivers within the `piec` library. Adhering to these rules ensures a globally consistent, interface-compliant, and minimal codebase across all supported instruments.

## 1. The 3-Level Architecture

PIEC drivers follow a strict 3-level hierarchy to ensure consistency and modularity.

### Level 1: The Foundation (`Instrument`)
All instruments in the library MUST inherit from the base `Instrument` class. This class handles the core VISA communication and standard PIEC behavior.

### Convenience Classes (e.g., `Scpi`)
`Scpi` is a **convenience class**, not a structural level. It provides vetted implementations of standard functions (like `reset`, `clear`, `idn`) that most SCPI-compliant instruments share. 
* **Crucially**: If a method like `reset()` is expected for a certain instrument type, it MUST be defined in the Level 2 interface, even if the Level 3 driver eventually uses the `Scpi` implementation.
* **Verification**: Always cross-check the instrument manual. If your instrument is SCPI-compliant but does *not* support a standard `Scpi` method (e.g., `*RST` isn't `reset`), or uses a different command string, you MUST override the method in your Level 3 driver or provide an alternative implementation following the Level 2 naming convention.

### Level 2: Instrument-Type Interface (`example.py`, `oscilloscope.py`)
These files define the **Template/Interface** for an entire category of instruments.
* They list all **requirements** (methods and attributes) for that type.
* They contain no specific SCPI command strings — only the "vocabulary" of the instrument type.

### Level 3: Specific Instrument Model (`agilent_33220a.py`)
This is the **Actual Implementation** of the driver.
* Inherits from the Level 2 Category (e.g., `Awg`) and a Level 1 base (usually `Scpi` or `Instrument`).
* Implements the Level 2 interface using specific hardware commands.

```python
from .awg import Awg
from ..scpi import Scpi

# Level 3 Driver inherits from Level 2 (Awg) and a Convenience/Base (Scpi)
class Agilent33220a(Awg, Scpi):
    AUTODETECT_ID = "33220A"
    # Implementation...
```

## 2. Constructor (`__init__`)
* **DO NOT** write a custom `__init__` method if its only purpose is to call `super().__init__(resource_name, **kwargs)`. The base `Instrument` class handles standard initialization.
* **IF** you must write a custom constructor for hardware configuration queries, it must take `*args, **kwargs` and pass them exactly to `super()`:

```python
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Custom queries here...
```

## 3. Autodetection (`AUTODETECT_ID`)
Every driver MUST (if possible) define a class-level string attribute named `AUTODETECT_ID`. This is a unique substring expected to be returned by the instrument when queried with an .idn() command.

```python
    AUTODETECT_ID = "MODEL_1234"
```

## 4. Class Attributes (Capabilities & Limits)
Class attributes define the valid parameters an instrument can accept. The parent base classes (e.g., `Oscilloscope`, `Awg`) define a strict vocabulary of these attribute names.
* Drivers MUST explicitly assign their supported capabilities using these exact class attribute names (e.g., `frequency`, `voltage`, `waveform`).
* **NEVER** introduce new vocabulary terms (like `waveform = ['WEIRD_WAVE']`) in the child class that do not exist in the parent class's definitions.

**Attribute Formatting Rules:**
The class attributes must follow a specific syntax based on what kind of parameter they restrict:
1. **Lists (Discrete Sets):** If the argument takes a limited number of defined values, use a list of the appropriate type. Examples:
   ```python
   channel = [1, 2]
   waveform = ['SIN', 'SQU', 'RAMP']
   ```
2. **Tuples (Ranges):** If the argument accepts any continuous float/int value within a range, use a geometric tuple `(min, max)`. Examples:
   ```python
   amplitude = (0.01, 10.0) # Vpp
   offset = (-5.0, 5.0) 
   ```
3. **Dictionaries (Dependent Arguments):** If the valid range or options of an argument depend on the state of *another* argument (e.g., the maximum frequency is restricted depending on the waveform selected), write this as a dictionary. The primary key is the name of the argument it depends on:
   ```python
   frequency = {
       'waveform': {
           'SIN': (1e-6, 30e6),
           'SQU': (1e-6, 10e6),
           'DC': None
       }
   }
   ```
   *(If a parameter has no known class attribute boundaries, set it to `None`.)*

## 5. Method Conventions: `set_`, `configure_`, and `run_`
Function naming strictly determines scope:
* **`set_<property>` Methods:** Must perform a **SINGLE** action. For instance, `set_frequency` only changes the frequency. They correspond directly to SCPI writes assigning one explicit hardware parameter. 
* **`get_<property>` Methods:** Must **RETURN** a single, unformatted value (e.g., a status bit, a scalar measurement).
* **`read_<property>` Methods:** Must **RETURN** formatted or complex data (e.g., an array of waveform points, a multi-value response, or a post-processed string). 
  - **Formatting**: The specific data structure (typically a `pandas.DataFrame`) must adhere to the return specification detailed in the parent class's docstring.
* **`configure_<module>` Methods:** Must perform **MULTIPLE** actions by wrapping and calling several individual `set_` functions. For instance, `configure_waveform` might call `set_waveform`, `set_frequency`, and `set_amplitude`. 
  - For EVERY `configure_` command, initialize all non-essential arguments to `None` in the signature, and only invoke the corresponding `set_` method if the parameter is not `None`.
* **`quick_read` Method:** A specialized **convenience function** (common in Oscilloscopes) used to return whatever data is currently ready or displayed on the hardware (e.g., a cursor value or mean measurement). It is used for fast, unformatted polling.
* **`run_<routine>` Methods:** Used for **hardware-executed routines** where the instrument performs a complete operation internally (at hardware speed) and then returns the results. The key distinction is that a `run_` method triggers autonomous instrument behavior — unlike `set_` (which only writes a parameter) or `configure_` (which just calls multiple `set_` methods). Examples:
  - `run_voltage_sweep(...)` — the sourcemeter executes the full I-V sweep internally and returns all data points at once.
  - `run_current_sweep(...)` — same for current sweep.
  - This is fundamentally different from manually looping `set_source_voltage` + `quick_read` in Python.

## 6. Method Signatures and Default Parameters
* Method signatures must perfectly mirror the parent interface.
* **DO NOT** provide arbitrary magnitude or state defaults in your `set_` functions. Parameters like `voltage=0.0`, `waveform="SIN"`, or `frequency=1000` must be set to `None` in the signature.
* Drivers must enforce explicit parameter assignments, looking like:
  ```python
  def set_voltage(self, channel=1, voltage=None):
      if voltage is None:
          raise ValueError("voltage must be provided")
      self.instrument.write(f"SOUR{channel}:VOLT {voltage}")
  ```
* **EXCEPTIONS:** 
  - Structural/targeting defaults like `channel=1`.
  - Boolean flag toggles like `on=True`, `ac=False`, or `four_wire=False`.
  - **Convenience `configure_` Methods:** These are allowed to retain sensible default values if those defaults are established in the parent interface. 

## 7. Communication & Protocol Convenience
* Read variables using `self.instrument.query("SCPI?")`.
* Write variables using `self.instrument.write("SCPI")`.
* **The Role of `Scpi`**: Inheritance from `Scpi` is a convenience to avoid rewriting the same basic commands. However, the driver developer is responsible for verifying that the inherited `reset()`, `clear()`, etc., map correctly to the instrument's manual.

## 8. Automatic State Tracking
The `piec` framework automatically tracks the "last set" value of any parameter that has a corresponding class attribute. 
* Whenever a `set_<property>(value=...)` method finishes successfully, the decorator updates `self._current_<property>` with that value.
* These attributes are useful for **dependent parameter checks** (handled by the framework) and for **driver-side conditional logic**.
* **Example:** If you need to know the current `mode` to set the correct `voltage` range, you can access `self._current_mode`.

## 8a. Automatic String Lowercasing
The `auto_check_params` decorator **automatically converts all string arguments to lowercase** before they are passed into your driver method. This means:
* Driver implementations should always expect lowercase strings (e.g. `'sin'`, not `'SIN'`).
* You do **not** need to call `.lower()` inside your methods — the framework handles it.
* Validation is case-insensitive regardless of how class attribute values are written — the validation function lowercases both sides before comparing, so `'sin'`, `'SIN'`, and `'Sin'` all pass against `['SIN', 'SQU', 'RAMP']` or `['sin', 'squ', 'ramp']` equally.
* If your instrument requires an uppercase string in its command (e.g. the instrument rejects `FUNC sin`), call `.upper()` on the argument inside your method before writing it to the instrument.

> [!CAUTION]  
> **Initial State is `None`:** Upon first connection, all tracked attributes are initialized to `None`. This means the first few `set_` calls (where one parameter depends on another) might skip validation or cause errors if your logic expects a value. Always perform a hardware query in `__init__` (see Rule 2) to synchronize these states immediately.

## 9. Optional Methods

PIEC has two mechanisms for optional methods, ensuring measurement code **never needs to change** regardless of which specific driver is connected.

### 9a. `@optional` Decorator (Parent Base Classes)
Some standard instrument features are not universally supported across all models. Use `@optional` in the **category base class** to mark these:

```python
from ..instrument import Instrument, optional

class Oscilloscope(Instrument):
    @optional
    def set_channel_impedance(self, channel, channel_impedance):
        """Sets the channel impedance, e.g. 1MOhm, 50Ohm"""
```

* Only use `@optional` in base classes (e.g., `Oscilloscope`, `Awg`), **never** in specific drivers.
* If a specific driver supports the feature, override the method as usual.
* If it doesn't, do nothing — calls will print `[OPTIONAL SKIP]` and return `None`.

### 9b. Automatic Optional (Child-Specific Methods)
Any public method that a specific driver defines **beyond** what the parent class provides is automatically treated as optional. If measurement code calls that method on a different driver that doesn't have it, it gracefully skips.

```python
# In a Keysight-specific driver:
class KeysightDSOX3024a(Oscilloscope, Scpi):
    def read_statistics(self):  # Not in parent Oscilloscope — auto-optional
        return self.instrument.query(":MEAS:STAT?")
```

This works because all standard methods exist on every driver via the parent class. Only truly missing child-specific methods trigger the skip mechanism.

## 10. Argument Mapping

In cases where the Level 2 interface uses a generic argument (e.g., `channel=1`, `mode='CONSTANT'`) but the hardware expects a different value (e.g., `channel='A'`, `mode='FIXED'`), the Level 3 driver is responsible for its own internal mapping:

```python
    def set_mode(self, channel, mode):
        # Map generic PIEC mode to specific hardware command
        mode_map = {'CONSTANT': 'FIXED', 'SWEEP': 'SWE'}
        hw_mode = mode_map.get(mode)
        if hw_mode is None:
             raise ValueError(f"Mode {mode} not supported by this instrument")
        self.instrument.write(f"SOUR{channel}:FUNC:{hw_mode}")
```

This ensures the user's measurement code can remain model-agnostic.

## 11. Repository Folder Structure

To keep the `drivers` directory organized, follow this nesting pattern:
1. **Category Folder**: (e.g., `drivers/oscilloscope/`)
2. **Interface File**: Named after the category (e.g., `oscilloscope.py`).
3. **Model Drivers**: Put directly in the category folder, named after the model (e.g., `dsox3024a.py`).

```text
piec/
  drivers/
    oscilloscope/
      oscilloscope.py       (Level 2 Interface)
      dsox3024a.py          (Level 3 Driver - Keysight)
      tds6604.py            (Level 3 Driver - Tektronix)
```
