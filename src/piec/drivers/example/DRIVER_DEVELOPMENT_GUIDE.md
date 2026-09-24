# Instrument Driver Development Guide

This guide outlines the strict requirements and conventions for creating new instrument drivers within the `piec` library. Adhering to these rules ensures a globally consistent, interface-compliant, and minimal codebase across all supported instruments.

## Contribution Workflow

These rules apply to manual development, AI chats, and repository agents:

* **Existing category:** copy `<category>/<category>.py` to
  `<category>/<model_name>.py`. Rename the class and inherit from the original
  category, with any protocol convenience class first, e.g. `SpecificAwg(Scpi, Awg)`.
* Preserve method docstrings, signatures, defaults, and return formats. Fill in
  bodies and class-level capabilities from the manual; append model-specific details.
* Copied stubs hide inherited methods. Delegate to `super()` when reusing an
  implementation. Remove copied `@optional` decorators from supported methods;
  omit unsupported optional methods to inherit the parent's skip behavior.
* **New category:** add only its minimal `__init__.py`, `<category>.py` interface,
  one `virtual_<category>.py` implementation, and first model. Copy the new
  interface to start that model. Discovery requires no registration edits.
  **Designing the category manually is HIGHLY recommended** to avoid erroneous
  functions and check that the base class attributes make sense. Define common
  names and capability defaults for features all instruments of that type should
  have; individual drivers translate these into each manufacturer's commands.
* Existing files are read-only, including `instrument.py`, `autodetect.py`,
  shared virtual infrastructure, parent interfaces, and other drivers. Give AI
  an exact allowed-file list, report shared-code blockers separately, and review
  the diff and untracked files yourself.
* **DO NOT ADD OR MODIFY TESTS, fixtures, or notebooks.** Run the existing dynamic
  tests with `python -m pytest tests/driver/ -v`, then `python -m pytest tests/ -v`.
  Verify commands against the manual and physical hardware before contributing.

## 1. The 3-Level Architecture

PIEC drivers follow a strict 3-level hierarchy to ensure consistency and modularity.

### Level 1: The Foundation (`Instrument`)
All instruments in the library MUST inherit from the base `Instrument` class.
It defines core VISA communication, validation, state tracking, and the common
lifecycle interface (`idn`, `reset`, `clear`, `error`, `wait`, `self_test`,
`operation_complete`, and `initialize`). Hardware implementations belong in
protocol convenience classes or model drivers; the base interface alone does
not provide every device's behavior.

### Convenience Classes (e.g., `Scpi`)
`Scpi` is a **convenience class**, not a structural level. It provides vetted implementations of standard IEEE 488.2 / SCPI-99 functions (like `idn`, `reset`, `clear`, `error`, `wait`, `self_test`, `operation_complete`, `initialize`) that most SCPI-compliant instruments share.

**How it works with Level 2 base classes:**

Level 2 classes inherit the common lifecycle interface from `Instrument`.
Several existing categories also redeclare lifecycle stubs to document their
requirements. A new category does not need to repeat the base interface:

* A driver that inherits **only** from the Level 2 class has the correct interface and can override each skeleton with its own native protocol commands.
* A driver that **also** inherits from `Scpi` can reuse its real SCPI implementations via MRO. If you copied lifecycle stubs into the model class, fill them with delegation to `super()` or the required hardware-specific implementation; copied blank stubs would hide the inherited implementations.

> [!IMPORTANT]
> **Verification**: Always cross-check the instrument manual. If your instrument is SCPI-compliant but does *not* support a standard `Scpi` method (e.g., `*RST` doesn't reset properly), or uses a different command string, you MUST override the method in your Level 3 driver.

### Level 2: Instrument-Type Interface (`example.py`, `oscilloscope.py`)
These files define the **Template/Interface** for an entire category of instruments.
* They list all **requirements** (methods and attributes) for that type.
* They inherit common lifecycle methods from `Instrument`; redeclare one only
  to document a category-specific requirement, not to add hardware commands.
* They contain no specific SCPI command strings — only the "vocabulary" of the instrument type.

Design the minimum requirements of the instrument type: the most general
interface, with consolidations for convenience where useful. Prefer `set_`,
`get_`, and `configure_` methods; use the other conventions below when needed.
Define common capability defaults for features expected on all models, and use
`@optional` for useful features found on many instruments but absent from others.
Model drivers translate these common names into each manufacturer's commands.

### Level 3: Specific Instrument Model (`agilent_33220a.py`)
This is the **Actual Implementation** of the driver.
* Inherits from the Level 2 Category (e.g., `Awg`) and optionally from the `Scpi` convenience class.
* Implements the Level 2 interface using specific hardware commands.
* When using a protocol convenience class, put it **before** the category class so its real implementations take priority over the category's skeleton methods.

**Path A — SCPI-compliant instrument** (most common):
```python
from .awg import Awg
from ..scpi import Scpi

# Inherits real SCPI implementations (idn, reset, clear, etc.) from Scpi
class Agilent33220a(Scpi, Awg):
    AUTODETECT_ID = "33220A"
    # Only implement the instrument-specific methods...
```

**Path B — Non-SCPI instrument** (proprietary protocol):
```python
from .oscilloscope import Oscilloscope

# No Scpi mixin — override the skeletons with native protocol commands
class MyProprietaryScope(Oscilloscope):
    AUTODETECT_ID = "PROPSCOPE"

    def idn(self):
        return self.instrument.query("ID?")

    def reset(self):
        self.instrument.write("FACTORY_RESET")
        self.set_trigger_sweep("AUTO")  # ensure AUTO mode per the contract
        self._initialize_state()
    # ... override remaining skeletons ...
```

## 2. Constructor (`__init__`)
* **DO NOT** write a custom `__init__` method if its only purpose is to call `super().__init__(resource_name, **kwargs)`. The base `Instrument` class handles standard initialization.
* **IF** you must write a custom constructor for hardware configuration queries, it must take `*args, **kwargs` and pass them exactly to `super()`:

```python
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Custom queries here...
```

* Virtual operation must be explicit. Pass the exact address `VIRTUAL` to a
  concrete model class for model-profiled virtual dispatch, or use
  `autodetect("VIRTUAL_<type>")` for category discovery. A failed physical
  connection raises `ConnectionError`; it does not silently create a virtual
  instrument.

### Virtual Driver Constructors

If a virtual driver is requested, inherit from `VirtualInstrument` first and the
Level 2 category second. Its constructor must call `super().__init__()` exactly once:

```python
from ..virtual_instrument import VirtualInstrument
from .example import Example

class VirtualExample(VirtualInstrument, Example):
    def __init__(self, address="VIRTUAL", **kwargs):
        super().__init__(address=address, **kwargs)
```

Never call `VirtualInstrument.__init__()` and the category initializer separately.
Passing the exact address `"VIRTUAL"` to a concrete model driver selects the
category's virtual driver before the physical constructor runs. The returned virtual
instance uses the concrete model's capability class attributes while retaining the
virtual driver's behavior:

```python
from piec.drivers.awg.k_81150a import Keysight81150a
from piec.drivers.awg.virtual_awg import VirtualAwg

awg = Keysight81150a("VIRTUAL")
assert isinstance(awg, VirtualAwg)
assert awg.channel == Keysight81150a.channel
```

Model-profiled virtual drivers enable parameter validation by default so their
simulated methods enforce the selected hardware's limits. Pass
`check_params=False` explicitly to disable this behavior. Physical drivers and
directly instantiated category virtual drivers retain the normal project-wide
default.

Class-level capabilities must describe the model's initial operating state.
Virtual dispatch deliberately skips the physical constructor, so limits assigned
only during `__init__` are not available to the profiled virtual class.

`VIRTUAL_<type>` addresses are reserved for category discovery through
`autodetect`, such as `autodetect("VIRTUAL_AWG")`; concrete model constructors
reject that form. Virtual classes may also be instantiated directly when generic
category capabilities are desired.

`VirtualInstrument` centrally provides `simulation_points`, with a default of
10,000 samples and an advisory warning above 1,000,000 samples. This is simulation
policy, not a hardware capability. Virtual drivers that generate arrays should use
`self.simulation_points` when they need a default or capacity and should use the
shared warning helper for large explicitly sized operations.

Do not add `"VIRTUAL"` branches to a physical model driver. Simulation behavior
belongs in the category's dedicated virtual class; model-level dispatch is handled
centrally before the physical constructor runs.

## 3. Autodetection (`AUTODETECT_ID`)
Use a verified, unique identification substring or list of substrings.
If automatic identification is unsupported or unknown, use
**`"MANUAL_ONLY:<ClassName>"`** instead of `None`, for example:

```python
AUTODETECT_ID = "MANUAL_ONLY:Geos_Stepper"
```

Keep the class-name suffix unique to avoid registry collisions. Document direct
construction with an explicit address. This is an ordinary registry string, not
special runtime handling; mocked tests passing does not prove hardware detection.
Do not make `idn()` return the marker. Replace it when a real identifier is verified.

```python
    # Single model
    AUTODETECT_ID = "MODEL_1234"

    # Multi-model family or model aliases
    AUTODETECT_ID = [
        "USB-1208HS",
        "USB-1208HS-2AO",
        "USB-1208HS-4AO",
    ]
```

When using a list of identifiers for a hardware family with differing channel counts or limits, declare the family maximum capabilities at the class level (ensuring model-profiled virtual dispatch works out-of-the-box), and let the physical constructor inspect `self.idn()` (e.g. matching `max(matches, key=len)`) to configure instance-specific capabilities.


## 4. Class Attributes (Capabilities & Limits)
Class attributes define the valid parameters an instrument can accept. The parent base classes (e.g., `Oscilloscope`, `Awg`) define a strict vocabulary of these attribute names.
* Drivers MUST explicitly assign their supported capabilities using these exact class attribute names (e.g., `frequency`, `voltage`, `waveform`).
* Preserve the interface's capability names and required options. Map vendor
  terminology into that vocabulary instead of replacing it with vendor-specific
  names. The dynamic tests require a model's lists to include the parent's
  required values; additional supported options must remain consistent with the
  interface contract.
* Channel lists describe physical availability. Use an empty list only when that
  channel type is absent. A fixed or non-configurable property does not make the
  channel absent: advertise its actual limits and retain the standard setter or
  configure method as a documented no-op when no hardware command is needed.
* Interface names are manufacturer-independent. Model drivers map vendor names,
  channel identifiers, modes, and ranges into this common vocabulary so
  measurement code does not need model-specific branches.
* Read and acquisition methods cannot be no-ops when their channel type is
  advertised. They must return the interface's documented data. For example, a
  DAQ without hardware-paced scanning must implement `read_AI_scan` with a
  documented software-paced fallback.

### Parent Declarations and Model Values

**If a capability can be a tuple on one instrument and a list on another,
initialize it to `None` in the parent.** The model supplies its actual range or
options at class level. For example, `Awg.load_impedance = None` allows a model
to declare `(1.0, 10000.0)` or `[50.0, 1000.0]`, according to its manual.

A non-`None` parent declaration fixes the type: `(None, None)` requires a
two-element tuple, while `[]` requires a list. Parent list entries are required
options that the model must retain. Leaving `None` on the model disables
validation; fill in known limits. Report conflicting parent declarations
separately instead of editing them in a model-only contribution.

### Attribute Formatting Rules
The class attributes must follow a specific syntax based on what kind of parameter they restrict:
1. **Lists (Discrete Sets):** If the argument takes a limited number of defined values, use a list of the appropriate type. Examples:
   ```python
   channel = [1, 2]
   waveform = ['SIN', 'SQU', 'RAMP']
   ```
2. **Tuples (Ranges):** If the argument accepts any numeric value within an interval, use a two-element tuple `(min, max)`. Examples:
   ```python
   amplitude = (0.01, 10.0) # Vpp
   offset = (-5.0, 5.0) 
   ```
   If the instrument offers a discrete selection of continuous ranges, use a
   list of tuples. Use a one-element list when there is only one supported
   range, and an empty list when there are no available options. Examples:
   ```python
   voltage_range = [(-10.0, 10.0), (-5.0, 5.0)]
   fixed_voltage_range = [(-10.0, 10.0)]
   unsupported_option = []
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
   *(If a parameter truly has no known class attribute boundaries, set it to
   `None`.)*

> [!WARNING]
> **`None` is copied literally into model-profiled virtual drivers.** Virtual
> dispatch skips the physical model's `__init__`, so a capability declared as
> `None` at class level will remain `None` in `ModelDriver("VIRTUAL")` even if
> the physical constructor normally replaces it with a concrete value. Since
> `None` disables automatic validation, declare the model's initial operating
> range or option list at class level. For example, a model that initializes in
> high-bandwidth mode should declare that mode's initial `amplitude` and
> `frequency` limits directly on the class.

## 5. Method Conventions: `set_`, `configure_`, and `run_`
Function naming strictly determines scope:
* **`set_<property>` Methods:** Must perform a **SINGLE** action. For instance, `set_frequency` only changes the frequency. They correspond directly to SCPI writes assigning one explicit hardware parameter. 
* **`get_<property>` Methods:** Must **RETURN** a single, unformatted value (e.g., a status bit, a scalar measurement).
* **`read_<property>` Methods:** Must **RETURN** formatted or complex data (e.g., an array of waveform points, a multi-value response, or a post-processed string). 
  - **Formatting**: The specific data structure (typically a `pandas.DataFrame`) must adhere to the return specification detailed in the parent class's docstring.
* **`configure_<module>` Methods:** Must perform **MULTIPLE** actions by wrapping and calling several individual `set_` functions. For instance, `configure_waveform` might call `set_waveform`, `set_frequency`, and `set_amplitude`. 
  - Preserve the parent signature. When designing a new interface, use `None`
    for optional settings and call their `set_` methods only when supplied.
    Existing parent-defined convenience defaults remain part of the contract.
* **`quick_read` Method:** A specialized **convenience function** (common in Oscilloscopes) used to return whatever data is currently ready or displayed on the hardware (e.g., a cursor value or mean measurement). It is used for fast, unformatted polling.
* **`run_<routine>` Methods:** Used for **hardware-executed routines** where the instrument performs a complete operation internally (at hardware speed) and then returns the results. The key distinction is that a `run_` method triggers autonomous instrument behavior — unlike `set_` (which only writes a parameter) or `configure_` (which just calls multiple `set_` methods). Examples:
  - `run_voltage_sweep(...)` — the sourcemeter executes the full I-V sweep internally and returns all data points at once.
  - `run_current_sweep(...)` — same for current sweep.
  - This is fundamentally different from manually looping `set_source_voltage` + `quick_read` in Python.

## 6. Method Signatures and Default Parameters
* Method signatures must perfectly mirror the parent interface.
* **DO NOT** invent magnitude or state defaults in a model's `set_` methods.
  Copy the parent signature exactly, including required arguments and any existing
  defaults. When designing a new interface, keep magnitude/state arguments
  required or use `None` with explicit validation, rather than inventing defaults
  such as `voltage=0.0`, `waveform="SIN"`, or `frequency=1000`.
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
* For VISA-based drivers, read variables using `self.instrument.query("SCPI?")`
  and write variables using `self.instrument.write("SCPI")`, with commands from
  the manual. Non-VISA drivers use their applicable transport or convenience
  class, such as `Digilent` for Universal Library communication.
* **The Role of `Scpi`**: Inheritance from `Scpi` is a convenience to avoid rewriting the same basic `*IDN?`, `*RST`, `*CLS`, `*ESR?`, `*WAI`, `*TST?`, `*OPC?` commands. However, the driver developer is responsible for verifying that the inherited `reset()`, `clear()`, etc., map correctly to the instrument's manual.
* **When to skip `Scpi`**: For a proprietary protocol, inherit from the category
  alone and implement the required native behavior. The common lifecycle
  interface is inherited from `Instrument`, possibly with category-specific
  documentation; its placeholders are not hardware implementations.

## 8. Automatic State Tracking
The `piec` framework automatically tracks the "last set" value of any parameter that has a corresponding class attribute. 
* After a wrapped public method succeeds, the decorator records each non-`None`
  argument whose name matches a capability attribute as `self._current_<name>`.
  This applies to public methods generally, not just `set_` methods, and includes
  applied argument defaults. Failed calls do not record their arguments.
* State tracking and string normalization operate even when `check_params=False`;
  that flag controls automatic parameter validation.
* These attributes are useful for **dependent parameter checks** (handled by the framework) and for **driver-side conditional logic**.
* **Example:** If you need to know the current `mode` to set the correct `voltage` range, you can access `self._current_mode`.

## 8a. Automatic String Lowercasing
The `auto_check_params` decorator **automatically converts all string arguments to lowercase** before they are passed into your driver method. This means:
* Driver implementations should always expect lowercase strings (e.g. `'sin'`, not `'SIN'`).
* You do **not** need to call `.lower()` inside your methods — the framework handles it.
* Validation is case-insensitive regardless of how class attribute values are written — the validation function lowercases both sides before comparing, so `'sin'`, `'SIN'`, and `'Sin'` all pass against `['SIN', 'SQU', 'RAMP']` or `['sin', 'squ', 'ramp']` equally.
* If your instrument requires an uppercase string in its command (e.g. the instrument rejects `FUNC sin`), call `.upper()` on the argument inside your method before writing it to the instrument.

> [!CAUTION]  
> **Initial State is `None`:** The framework initially sets tracked attributes
> to `None`. Dependent validation can skip a check when the dependency is unknown.
> If your driver relies on an existing hardware setting, query it in `__init__`
> and synchronize the relevant state before relying on it. Do not add a
> constructor solely to query state the driver does not need, or guess a state
> when a required query fails.
> This synchronization applies only to physical instances. A model-profiled
> virtual instance does not run the physical constructor, so its usable limits
> must already be present in the model's class attributes.

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

Virtual drivers follow the same rule: simulate required methods, and implement
optional methods only when that simulation is needed. Otherwise inherit the skip
behavior; copying a physical model's capabilities does not add simulated features.

### 9b. Automatic Optional (Child-Specific Methods)
Any public method that a specific driver defines **beyond** what the parent class provides is automatically treated as optional. If measurement code calls that method on a different driver that doesn't have it, it gracefully skips.

```python
# In a Keysight-specific driver:
class KeysightDSOX3024a(Scpi, Oscilloscope):
    def read_statistics(self):  # Not in parent Oscilloscope — auto-optional
        return self.instrument.query(":MEAS:STAT?")
```

This works because all standard methods exist on every driver via the parent class. Only truly missing child-specific methods trigger the skip mechanism.

## 10. Argument Mapping

In cases where the Level 2 interface uses a generic argument (e.g., `channel=1`, `mode='CONSTANT'`) but the hardware expects a different value (e.g., `channel='A'`, `mode='FIXED'`), the Level 3 driver is responsible for its own internal mapping:

```python
    def set_mode(self, channel, mode):
        # Map generic PIEC mode to specific hardware command
        mode_map = {'constant': 'FIXED', 'sweep': 'SWE'}
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

Category autodetection uses the folder and interface-file names, then discovers the
single `Instrument` subclass defined in that interface module. The Python class name
does not need to match the category name. For example,
`drivers/my_inst/my_inst.py` may define `class MyInstSomethingElse(Instrument)` without adding a
registry entry. The interface module must define exactly one canonical category class.
Convenience aliases such as `scope` are optional API additions maintained separately.

Virtual drivers use the same zero-registration approach. Put one `virtual_*.py` file
in the category folder and define one class there that inherits from
`VirtualInstrument`. Neither the rest of the filename nor the class name must match
the category. Autodetect reports an ambiguity if a category defines more than one
virtual driver.
