The Driver
==========

Every instrument in PIEC is represented by a **driver** — a Python class that wraps the
communication with a physical (or virtual) instrument into a consistent interface that
measurement code can work with.

Driver inheritance hierarchy
-----------------------------

Within ``piec.drivers``, drivers are organized as a strict **3-level class hierarchy**.
Each level inherits from the one above it, adding specificity:

.. code-block:: text

   Level 1 — Instrument (base) / Scpi (convenience)
       The base Instrument class defines the minimum requirements of any
       instrument driver, wrapping PyVISA for resource management. The Scpi
       class optionally extends this with vetted implementations for
       Standard Commands for Programmable Instruments (SCPI)-compliant
       devices (e.g., *IDN?, *RST, *CLS).

   Level 2 — Instrument-type interface
       Examples: Oscilloscope, Awg, Lockin, SourceMeter, Dmm
       Defines the required methods and parameter standards that all
       drivers of that category must implement. Measurement code talks
       to this interface, making drivers interchangeable.

   Level 3 — Specific instrument model
       Examples: KeysightDSOX3024a, Agilent33220a, SR830, Keithley2400
       Inherits from a Level 2 class and a Level 1 base (usually Scpi)
       and implements the hardware-specific logic using that instrument's
       exact command set.

This design means you can swap out one oscilloscope driver for another without changing any
measurement code, as long as both implement the same Level 2 interface.

Each instrument category also provides a ``VirtualInstrument`` (e.g.,
``VirtualScope``, ``VirtualAwg``) that returns simulated responses, enabling
development and testing without physical hardware.

What each level provides
------------------------

**Level 1 — Instrument** (``piec.drivers.instrument.Instrument``)
   The foundation for all drivers. It:

   * Accepts an address string (VISA resource string, COM port, or ``'VIRTUAL'``) at
     initialization.
   * Opens and manages the connection via PyVISA (or falls back to a virtual backend).
   * Provides the ``AutoCheckMeta`` framework for automatic parameter validation and
     state tracking based on class attributes. Setting a class attribute to ``None``
     bypasses this validation, allowing for custom driver-side handling.
   * Exposes ``read()``, ``write()``, and ``query()`` methods used by all subclasses.

**Level 1 — Scpi** (``piec.drivers.scpi.Scpi``)
   A **convenience class**, not a separate structural level. It inherits from
   ``Instrument`` and provides vetted implementations of standard IEEE 488.2 SCPI
   commands that most SCPI-compliant instruments share:

   * ``idn()`` — sends ``*IDN?`` and returns the instrument identification string.
   * ``reset()`` — sends ``*RST`` to restore factory defaults.
   * ``clear()`` — sends ``*CLS`` to clear the status registers and error queue.
   * ``wait()`` — sends ``*WAI`` to wait for pending operations.
   * ``error()`` — sends ``*ESR?`` to read the error status register.

   Drivers should always cross-check the instrument manual. If the instrument does
   *not* support a standard ``Scpi`` method (or uses a different command string), the
   Level 3 driver must override that method.

**Level 2 — Instrument-type interface classes**
   Each category (``Oscilloscope``, ``Awg``, ``Dmm``, ``Lockin``, ``SourceMeter``, etc.)
   defines the set of methods and class attributes that a measurement class can rely on.
   For example, an ``Oscilloscope`` is expected to have methods for setting the timebase,
   configuring channels, and capturing a waveform. These files contain no specific SCPI
   command strings — only the "vocabulary" of the instrument type. Level 2 interfaces
   also support optional functionality. Methods can be decorated with ``@optional``, or
   custom Level 3 driver methods can be automatically treated as optional. This allows
   measurement routines to skip unsupported methods gracefully across different hardware.

**Level 3 — Specific model drivers**
   These are the classes you instantiate in your code. They inherit from a Level 2
   category class **and** a Level 1 base (usually ``Scpi``), then translate the generic
   interface into the exact SCPI strings (or vendor API calls) that the hardware
   understands:

   .. code-block:: python

      from .awg import Awg
      from ..scpi import Scpi

      class Keysight81150a(Awg, Scpi):
          AUTODETECT_ID = "81150A"
          # Implementation ...

   .. note::
      To see a complete implementation template, refer to the ``src/piec/drivers/example/`` directory. It contains the ``Example`` Level 2 interface and the ``SpecificExample`` Level 3 driver. Please read the :doc:`adding a driver <../contributing/adding_driver>` guide before writing custom drivers.

   For the full list of available drivers, see :doc:`../supported_instruments`.

Folder structure
----------------

The driver hierarchy maps directly to the folder structure within ``src/piec/drivers/``:

* **Level 1** base files (e.g., ``instrument.py``, ``scpi.py``) sit directly in the root ``drivers/`` directory.
* **Level 2** interface files are located in a folder named after the instrument category, and the Python file shares this name (e.g., ``oscilloscope/oscilloscope.py``).
* **Level 3** specific model files are placed alongside their Level 2 interface in the same category folder (e.g., ``oscilloscope/k_dsox3024a.py``).

Virtual instruments
-------------------

Each instrument category provides a ``VirtualInstrument`` class (e.g.,
``VirtualScope``, ``VirtualAwg``, ``VirtualLockin``) that returns simulated
responses. Virtual instruments allow you to develop and test measurement code
without any physical hardware connected — simply pass ``'VIRTUAL'`` as the address:

.. code-block:: python

   from piec.drivers.oscilloscope.virtual_oscilloscope import VirtualScope

   scope = VirtualScope()
   print(scope.idn())  # Returns a simulated identification string

Using a driver
--------------

Import the specific driver class and instantiate it with the instrument's address:

.. code-block:: python

   from piec.drivers.awg.k_81150a import Keysight81150a

   awg = Keysight81150a('GPIB0::8::INSTR')
   print(awg.idn())   # Confirms connection

For help connecting or finding an instrument's address, see :doc:`connecting_to_instrument`.

Parameter validation
--------------------

Every piec driver has built-in parameter validation that checks method arguments against
the instrument's known capabilities before sending any command to hardware. This is
controlled by the ``check_params`` flag at instantiation and is **off by default**:

.. code-block:: python

   # Default — no validation performed (fastest for scripting)
   awg = Keysight81150a('GPIB0::8::INSTR')

   # Validation enabled — arguments are checked on every method call
   awg = Keysight81150a('GPIB0::8::INSTR', check_params=True)

When ``check_params=True``, every method call validates its arguments against the driver's
class attributes before executing:

* **List** (e.g. ``waveform = ['SIN', 'SQU', 'RAMP']``) — the argument must be one of the
  listed values.
* **Tuple** (e.g. ``amplitude = (0.01, 10.0)``) — the argument must fall within that
  numeric range (inclusive).
* **Dictionary** (e.g. ``frequency = {'waveform': {'SIN': (1e-6, 30e6), ...}}``) — the
  valid range depends on the current value of another parameter. piec resolves the
  dependency automatically using the current instrument state.
* **None** — validation for that parameter is skipped entirely. The driver handles it
  internally. This is the standard way for a driver to opt out of automatic checking for
  a specific parameter.

If a value fails validation, a ``ValueError`` is raised before any command is sent to the
instrument.

.. note::
   **String arguments are automatically lowercased** before validation and before being
   passed to the driver method, so ``'SIN'``, ``'sin'``, and ``'Sin'`` are all equivalent
   from the caller's perspective.

   Validation is case-insensitive regardless of how class attribute values are written —
   the validator lowercases both sides before comparing. If a driver needs to send an
   uppercase string to the instrument, it should call ``.upper()`` on the argument inside
   the method body before writing it.

Class attributes
----------------

Every driver class exposes its valid parameter ranges as **class attributes**. You can
inspect these directly — without connecting to any hardware — to understand what values
an instrument accepts:

.. code-block:: python

   from piec.drivers.awg.k_81150a import Keysight81150a

   print(Keysight81150a.channel)    # [1, 2]
   print(Keysight81150a.amplitude)  # (0.01, 10.0)
   print(Keysight81150a.waveform)   # ['SIN', 'SQU', 'RAMP', 'PULS', ...]

Attribute values follow a consistent syntax:

* **List** — a finite set of accepted values (e.g. channel numbers, waveform types)
* **Tuple** — a continuous numeric range ``(min, max)``
* **Dictionary** — a nested structure where the valid range depends on another argument
* **None** — no automatic bounds; the driver validates this parameter itself

These attributes are defined at the Level 2 interface for the instrument category and
overridden at Level 3 with the specific model's real values. The parent Level 2 class
defines the *vocabulary* (attribute names that must exist); the Level 3 driver fills in
the actual numbers from the instrument manual.

State tracking
--------------

Whenever a ``set_`` method completes successfully, piec automatically records the
value that was set as an instance attribute ``self._current_<name>``. For example,
after calling ``awg.set_waveform(1, 'sin')``, the driver stores
``awg._current_waveform = 'sin'``.

All state attributes are initialized to ``None`` at connection time and updated as
methods are called. They serve two purposes:

1. **Dependent validation** — when ``check_params=True``, if a parameter's valid range
   depends on another (e.g. ``frequency`` depends on ``waveform``), piec looks up the
   current state automatically so you do not need to pass the dependency explicitly
   every time.

2. **Driver-side logic** — driver implementations can read ``self._current_<attr>`` to
   make decisions based on the last known hardware state without issuing an extra query
   to the instrument.