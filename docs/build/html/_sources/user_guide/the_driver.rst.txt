The Driver
==========

Every instrument in PIEC is represented by a **driver** — a Python class that makes the
communication with a physical (or virtual) instrument into an interface the code can work with.

Driver inheritance hierarchy
-----------------------------

PIEC drivers are organized as a four-level class hierarchy. Each level inherits from the one
above it, adding specificity:

.. code-block:: text

   Level 1 — Instrument
       Base class for all drivers. Requires only an address to initialize.
       Provides the core open/close/read/write communication methods.

   Level 2 — Communication protocol
       Examples: SCPI_Instrument
       Adds helpers for instruments that use Standard Commands for Programmable
       Instruments (SCPI), such as *IDN?, *RST, *CLS.

   Level 3 — Generic instrument type
       Examples: Oscilloscope, AWG, DMM, LockIn, SourceMeter
       Defines the abstract interface (methods and properties) that all instruments
       of that category must implement. Code at the measurement level talks to this
       interface, making drivers interchangeable.

   Level 4 — Specific model
       Examples: Keysight81150a, KeysightDSOX3024A, SR830, Keithley2400
       Implements the Level 3 interface for a particular manufacturer and model
       using that instrument's exact command set.

This design means you can swap out one oscilloscope driver for another without changing any
measurement code, as long as both implement the same Level 3 interface.

What each level provides
------------------------

**Instrument** (``piec.drivers.instrument.Instrument``)
   All drivers inherit from this class. It:

   * Accepts an address string (VISA resource string, COM port, etc.) at initialization.
   * Opens and manages the connection to the instrument.
   * Exposes ``read()``, ``write()``, and ``query()`` methods used by all subclasses.

**SCPI_Instrument** (``piec.drivers.scpi_instrument.SCPI_Instrument``)
   Inherits from ``Instrument``. Adds convenience wrappers for the most common SCPI commands:

   * ``idn()`` — sends ``*IDN?`` and returns the instrument identification string.
   * ``reset()`` — sends ``*RST`` to restore factory defaults.
   * ``clear()`` — sends ``*CLS`` to clear the status registers and error queue.

**Generic instrument type classes**
   Each category (AWG, Oscilloscope, DMM, etc.) defines the set of methods that a
   measurement class can rely on — for example, an Oscilloscope is expected to have methods
   for setting the timebase, configuring channels, and capturing a waveform.

**Specific model drivers**
   These are the classes you instantiate in your code. They translate the generic interface
   into the exact SCPI strings (or vendor API calls) that your hardware understands. For the
   full list of available drivers, see :doc:`../supported_instruments`.

Using a driver
--------------

Import the specific driver class and instantiate it with the instrument's address:

.. code-block:: python

   from piec.drivers.keysight81150a import Keysight81150a

   awg = Keysight81150a('GPIB0::8::INSTR')
   print(awg.idn())   # Confirms connection

For help finding an instrument's address, see :doc:`finding_address`.