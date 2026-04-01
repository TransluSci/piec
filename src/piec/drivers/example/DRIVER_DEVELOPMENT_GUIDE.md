# `piec` Instrument Driver Development Guide

This guide outlines the strict requirements and conventions for creating new instrument drivers within the `piec` library. Adhering to these rules ensures a globally consistent, interface-compliant, and minimal codebase across all supported instruments.

## 1. Class Inheritance
Every new instrument driver must inherit from both:
1. **The Specific Instrument Category Base Class** (e.g., `Oscilloscope`, `Awg`, `Sourcemeter`, `DMM`, `Lockin`).
2. **The `Scpi` Base Class** (or `Instrument` if it is a non-SCPI device).

```python
from .awg import Awg
from ..scpi import Scpi

class NewInstrumentModel(Awg, Scpi):
    # Driver implementation
    pass
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

## 5. Method Conventions: `set_` vs `configure_`
Function naming strictly determines scope:
* **`set_<property>` Methods:** Must perform a **SINGLE** action. For instance, `set_frequency` only changes the frequency. They correspond directly to SCPI writes assigning one explicit hardware parameter. 
* **`configure_<module>` Methods:** Must perform **MULTIPLE** actions by wrapping and calling several individual `set_` functions. For instance, `configure_waveform` might call `set_waveform`, `set_frequency`, and `set_amplitude`. 
  - For EVERY `configure_` command, initialize all non-essential arguments to `None` in the signature, and only invoke the corresponding `set_` method if the parameter is not `None`.

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

## 7. SCPI Communication & Lean Code
* Read variables using `self.instrument.query("SCPI?")`.
* Write variables using `self.instrument.write("SCPI")`.
* We aim for a "lean code" philosophy. Parameter type validation logic (e.g., generic `check_params` testing) should not be manually implemented. Rely on the global parameter checking tools or let the instrument throw a native hardware error. Include `ValueError` raises strictly for missing obligatory arguments when `None` is provided.
