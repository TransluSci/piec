Finding Your Instrument's Address
==================================

Before connecting to an instrument, you need its **VISA resource string** (also called its
address). This is a string like ``'GPIB0::7::INSTR'`` or
``'USB0::0x0958::0x17A7::MY62080068::0::INSTR'`` that uniquely identifies the instrument on
your computer.

Listing available instruments
------------------------------

Use pyvisa (installed automatically with PIEC) to scan for connected instruments:

.. code-block:: python

   from pyvisa import ResourceManager

   rm = ResourceManager()
   print(rm.list_resources())
   # Example output:
   # ('GPIB0::7::INSTR', 'USB0::0x0958::0x17A7::MY62080068::0::INSTR')

Each string in the output is an address you can pass to a PIEC driver. Identify your
instrument by its GPIB address (set on the instrument's front panel) or by its USB vendor and
product ID.

GPIB addresses
--------------

For GPIB instruments, the address takes the form ``GPIB<bus>::<primary_address>::INSTR``.
The primary address (e.g., ``7``) is configured on the instrument itself — check the front
panel menu or the instrument manual.

USB addresses
-------------

USB instrument addresses are determined automatically by pyvisa. The vendor ID (e.g.,
``0x0958``) and product ID identify the manufacturer and model; the serial number
(e.g., ``MY62080068``) uniquely identifies the specific unit.

Virtual mode
------------

PIEC drivers support a **virtual mode** that simulates instrument responses without any
physical hardware. This is useful for developing and testing measurement workflows offline.

To use virtual mode, pass ``'virtual'`` as the address when instantiating a driver:

.. code-block:: python

   from piec.drivers.keysight81150a import Keysight81150a

   awg = Keysight81150a('virtual')
   print(awg.idn())   # Returns a simulated IDN string

Virtual instruments respond to all the same method calls as real instruments but generate
synthetic data instead of communicating with hardware. The :doc:`../getting_started/quickstart`
example uses virtual mode so you can run it without any connected equipment.