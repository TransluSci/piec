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
       Examples: Oscilloscope, Awg, Lockin, Sourcemeter, DMM
       Defines the required methods and parameter standards that all
       drivers of that category must implement. Measurement code talks
       to this interface, making drivers interchangeable.

   Level 3 — Specific instrument model
       Examples: KeysightDSOX3024a, Agilent33220A, SRS830, Keithley2400
       Inherits from a Level 2 class, optionally with Scpi or Digilent,
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

   * Accepts a physical VISA resource string or serial address at initialization.
   * Opens and manages physical connections via PyVISA. A failed physical connection
     raises ``ConnectionError`` rather than silently switching to simulation.
   * Uses ``AutoCheckMeta`` to intercept an exact ``VIRTUAL`` address on a concrete
     categorized model before physical initialization. The base ``Instrument``
     constructor itself remains physical-only. Category-style ``VIRTUAL_<type>``
     discovery is handled by ``autodetect()``.
   * Provides the ``AutoCheckMeta`` framework for automatic parameter validation and
     state tracking based on class attributes. Setting a class attribute to ``None``
     bypasses this validation, allowing for custom driver-side handling.
   * Stores the communication resource as ``self.instrument``; physical drivers use
     its ``read()``, ``write()``, and ``query()`` methods.

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
   Each category (``Oscilloscope``, ``Awg``, ``DMM``, ``Lockin``, ``Sourcemeter``, etc.)
   defines the set of methods and class attributes that a measurement class can rely on.
   For example, an ``Oscilloscope`` is expected to have methods for setting the timebase,
   configuring channels, and capturing a waveform. These files contain no specific SCPI
   command strings — only the "vocabulary" of the instrument type. Level 2 interfaces
   also support optional functionality. Methods can be decorated with ``@optional``, or
   custom Level 3 driver methods can be automatically treated as optional. This allows
   measurement routines to skip unsupported methods gracefully across different hardware.

**Level 3 — Specific model drivers**
   These are the classes you instantiate in your code. They inherit from a Level 2
   category class, optionally with a convenience class such as ``Scpi``, then translate the generic
   interface into the exact SCPI strings (or vendor API calls) that the hardware
   understands:

   .. code-block:: python

      from .awg import Awg
      from ..scpi import Scpi

      class Keysight81150a(Scpi, Awg):
          AUTODETECT_ID = "81150A"
          # Implementation ...

   The base-class order is significant: the convenience class comes first so
   its defined methods take priority.

   .. note::
      Start by copying the category interface into a new model file, preserving
      its docstrings and signatures. Follow :doc:`adding a driver <../contributing/adding_driver>`
      for inheritance, implementation, and validation steps.

   For the full list of available drivers, see :doc:`../supported_instruments`.

Folder structure
----------------

The driver hierarchy maps directly to the folder structure within ``src/piec/drivers/``:

* **Level 1** base files (e.g., ``instrument.py``, ``scpi.py``) sit directly in the root ``drivers/`` directory.
* **Level 2** interface files are located in a folder named after the instrument category, and the Python file shares this name (e.g., ``oscilloscope/oscilloscope.py``).
* **Level 3** specific model files are placed alongside their Level 2 interface in the same category folder (e.g., ``oscilloscope/k_dsox3024a.py``).

Virtual instruments
-------------------

Each instrument category provides a ``VirtualInstrument`` subclass (e.g.,
``VirtualScope``, ``VirtualAwg``, ``VirtualLockin``) that returns simulated
responses. Instantiate the generic virtual class directly, or pass the exact
address ``'VIRTUAL'`` to a concrete model class:

.. code-block:: python

   from piec.drivers.oscilloscope.virtual_oscilloscope import VirtualScope

   scope = VirtualScope()
   print(scope.idn())  # Returns a simulated identification string

   from piec.drivers.awg.k_81150a import Keysight81150a

   awg = Keysight81150a('VIRTUAL')
   print(awg.channel)  # Model capabilities with VirtualAwg behavior

Using a driver
--------------

Import the specific driver class and instantiate it with the instrument's address:

.. code-block:: python

   from piec.drivers.awg.k_81150a import Keysight81150a

   awg = Keysight81150a('GPIB0::8::INSTR')
   print(awg.idn())   # Confirms connection

For help connecting or finding an instrument's address, see :doc:`connecting_to_instrument`.

Oscilloscope waveform data
--------------------------

The physical Keysight DSOX3024A and LeCroy SDA6020 drivers read one selected
channel, a list of selected channels, or the channels displayed on the scope.
With the desired signals connected and channels displayed:

.. code-block:: python

   from piec.drivers.autodetect import autodetect

   scope = autodetect('scope', check_params=True)
   scope.configure_acquisition(channel=1)
   data = scope.get_data()  # Columns: Time, Voltage
   data.plot(x='Time', ylabel='Voltage (V)')

   scope.configure_acquisition(channel=[2, 1])
   data = scope.get_data()  # Columns: Time, CH2, CH1

``get_data()`` returns a pandas DataFrame with time in seconds and voltages in
volts. A single channel, including a one-element list such as ``[3]``, returns
``Time, Voltage``. Multiple channels return ``Time`` followed by ``CH<n>``
columns in selection order.

Before an explicit acquisition selection, ``get_data()`` reads displayed
channels. ``reset()`` or ``initialize()`` clears that selection; passing
``channel=None`` to ``configure_acquisition()`` retains it. Resetting also
changes hardware settings, so configure the scope again before reading.
Use ``get_data()`` for scope waveform reads; ``quick_read()`` is no longer part
of the oscilloscope interface.

Arbitrary waveforms
-------------------

Upload and select an arbitrary waveform in separate steps:

.. code-block:: python

   data = [0, 1, 0, -1]
   awg.create_arb_waveform(channel=1, data=data)
   awg.set_arb_waveform(channel=1)

``arb_name=None`` is the default for both methods. On the 81150A, this uses the
temporary volatile buffer without saving a waveform to nonvolatile memory.
To save a waveform, supply a name when uploading, then use the same name to
select it:

.. code-block:: python

   awg.create_arb_waveform(channel=1, data=data, arb_name='STAIRCASE')
   awg.set_arb_waveform(channel=1, arb_name='STAIRCASE')

Named storage support depends on the model driver. The 81150A reserves the
name ``VOLATILE``; use ``None`` or omit ``arb_name`` for temporary uploads.
Uploading and selecting do not enable output. Configure the frequency,
amplitude, offset, and load for the connected setup, then call
``awg.output(channel=1, on=True)`` when ready.

On the 81150A, input values describe relative sample levels, not voltages.
The scaling helper uses the largest absolute value and preserves the waveform's
relative levels without recentering it. For example, ``[0, 1, 0, -1]`` and
``[0, 5, 0, -5]`` produce approximately the same scaled waveform. Positive-only
data such as ``[0, 0.5, 1]`` uses approximately half the total DAC span.

The printed peak-to-peak ratio estimates the DAC span before transfer; it does
not measure output voltage. For an 81150A, read the stored waveform span with:

.. code-block:: python

   print(awg.instrument.query(':DATA1:ATTR:PTP? VOLATILE').strip())

A value near ``1.0`` means the stored waveform uses the full DAC span.
Verify the shape and physical voltage on the connected scope.

Parameter validation
--------------------

Every piec driver has built-in parameter validation that checks method arguments against
the instrument's known capabilities before sending any command to hardware. This is
controlled by the ``check_params`` flag at instantiation and is **off by default**:

.. code-block:: python

   # Automatic validation off; model-specific checks may still run
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
* **None** — automatic capability checks for that parameter are skipped. The driver
  handles its bounds or allowed values internally; annotated types are still checked.

Where a method declares parameter types, validation checks those types too.
For example, ``configure_acquisition(channel=[1, 2])`` checks each selected
channel against the scope's supported channels. Annotated integer channels do
not accept strings such as ``'1'`` or floats such as ``1.0``.

Model-profiled virtual drivers are the exception to the default-off policy. Constructing
``ModelDriver("VIRTUAL")`` enables validation automatically so the simulation enforces that
model's class-level capabilities. Pass ``check_params=False`` explicitly to opt out.

Incorrect annotated types raise ``TypeError``; unsupported capability values
raise ``ValueError`` before the method sends hardware commands. For interactive
driver testing, enable ``check_params=True`` when connecting. You can also
enable it on an existing instance with ``scope.check_params = True``.

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
   print(Keysight81150a.amplitude)  # (0, 5); instance limits depend on amplifier mode
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

If a capability can be a tuple on one model and a list on another, the parent
declares it as ``None``. A parent value of ``(None, None)`` fixes the type as a
tuple; ``[]`` fixes it as a list. Models supply their actual limits or options.

State tracking
--------------

After a wrapped public method succeeds, piec records non-``None`` arguments whose
names match capability attributes as ``self._current_<name>``. This includes
argument defaults and applies even with ``check_params=False``. For example,
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
