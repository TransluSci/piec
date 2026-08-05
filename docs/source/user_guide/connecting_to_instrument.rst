Connecting to the Instrument
============================

Before you can run a measurement, you need to link PIEC to your physical (or virtual) hardware. You can do this automatically using PIEC's autodetection system, or manually by finding your instrument's VISA address.

Instrument Autodetection
------------------------

PIEC features a useful autodetection system that automatically identifies connected instruments and maps them to their appropriate Python drivers.

How to Use Autodetect
^^^^^^^^^^^^^^^^^^^^^

You can invoke the ``autodetect()`` function in a few different ways depending on what information you have available:

1. **By Instrument Category (Recommended)**: 
   If you know you need an oscilloscope, you can simply pass the broad category string to the function. PIEC will scan all connected devices until it finds one that matches that instrument type.
   
   .. code-block:: python

      from piec.drivers.autodetect import autodetect

      # Pass the string type
      my_scope = autodetect('scope')
      my_dmm = autodetect('dmm')

   Valid category strings include any instrument category folder name located in the
   ``src/piec/drivers/`` directory (e.g., ``'oscilloscope'``, ``'awg'``,
   ``'lockin'``, ``'dmm'``). The folder must contain a same-named interface module,
   such as ``oscilloscope/oscilloscope.py``, defining exactly one ``Instrument``
   subclass. The Python class name is discovered automatically and does not need to
   match the category string. PIEC also provides convenience aliases such as
   ``'scope'`` and ``'stepper'``.

2. **By Hardware Address**: 
   If you know the exact VISA resource address of the instrument (e.g., a GPIB or USB string), you can pass it directly. PIEC will probe that specific address and load the correct specific model driver for it.

   .. code-block:: python

      # Pass the physical VISA address
      my_awg = autodetect('GPIB0::8::INSTR')

3. **Verbose Output**:
   If you are having trouble connecting or want to see the sequence of probing under the hood, use the ``verbose=True`` flag.

   .. code-block:: python

      my_instrument = autodetect('scope', verbose=True)

   This will print out the addresses being checked, the identification strings being returned, and the driver class ultimately selected.

How Autodetect Works
^^^^^^^^^^^^^^^^^^^^

1. **Scanning/Probing**: When invoked, PIEC targets the appropriate VISA resources and sends a standard identification query (typically ``*IDN?``).
2. **Matching**: It compares the instrument's response against the ``AUTODETECT_ID`` strings defined in every Level 3 driver class within the library.
3. **Caching**: The system stores identification substrings and their corresponding
   driver class paths in a local JSON registry file (typically
   ``registry_cache.json``). If this file does not exist, PIEC creates it
   automatically.

This cache avoids rescanning and importing every driver module on subsequent matches.
Hardware is still probed for its identification response before selecting a driver.

Supporting Autodetect in New Drivers
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

To ensure your custom model driver works with this system, define an
``AUTODETECT_ID`` class attribute in the Level 3 driver. Autodetect scans driver files
recursively, so no import or manual registry entry is required. See
:doc:`../contributing/adding_driver` for details.

Finding Your Instrument's Address Manually
------------------------------------------

If you prefer to bypass autodetection or are debugging, you need the instrument's **VISA resource string** (also called its address). This is a string like ``'GPIB0::7::INSTR'`` or ``'USB0::0x0958::0x17A7::MY62080068::0::INSTR'`` that uniquely identifies the instrument on your computer.

Listing available instruments
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Use PIEC's ``PiecManager`` class to scan for connected instruments. Under the hood, this manager leverages PyVISA for standard instruments, but it also hooks into specialized hardware APIs (such as Digilent or MCC devices) allowing them to all be natively discovered in one simple command:

.. code-block:: python

   from piec.drivers.utilities import PiecManager

   pm = PiecManager()
   print(pm.list_resources())
   # Example output:
   # ('GPIB0::7::INSTR', 'USB0::0x0958::0x17A7::MY62080068::0::INSTR')

Each string in the output is a VISA address you can pass to a PIEC driver. Standard instruments use the following address formats:

* **GPIB**: ``GPIB<bus>::<primary_address>::INSTR`` (e.g., ``'GPIB0::7::INSTR'``). The address is configured on the instrument's front panel.
* **USB**: ``USB0::0x0958::0x17A7::...::INSTR``. These are determined automatically by the OS and PyVISA.
* **Ethernet (TCPIP)**: ``TCPIP::192.168.1.100::INSTR``. These use the instrument's IP address.

Manual Connection Example
^^^^^^^^^^^^^^^^^^^^^^^^^

Once you have the address, import the specific driver class and instantiate it:

.. code-block:: python

   from piec.drivers.oscilloscope.k_dsox3024a import KeysightDSOX3024a

   # Connect using the manual address
   scope = KeysightDSOX3024a('USB0::0x0958::0x17A7::MY62080068::0::INSTR')
   print(scope.idn())
   # Example output:
   # 'AGILENT TECHNOLOGIES,DSO-X 3024A,MY62080068,02.40'

Virtual mode
------------

PIEC drivers support an explicit **virtual mode** that simulates instrument responses
without any physical hardware. This is useful for developing and testing measurement
workflows offline. Failed physical connections raise ``ConnectionError`` and never
silently switch to virtual mode when constructing a driver directly. Use **virtual mode** to simulate the instrument. The
``autodetect()`` function catches failed probes and returns no match instead; it also
never substitutes a virtual instrument.

Use a virtual driver directly, or pass ``'VIRTUAL'``/``'VIRTUAL_<type>'`` where an
address is accepted (case-insensitive):

.. code-block:: python

   from piec.drivers.oscilloscope.virtual_oscilloscope import VirtualScope

   scope = VirtualScope()
   print(scope.idn())   # Returns a simulated IDN string

   from piec.drivers.autodetect import autodetect

   awg = autodetect('virtual_awg')

Virtual instruments respond to all the same method calls as real instruments but generate synthetic data instead of communicating with hardware.
