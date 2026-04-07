Adding a Driver
===============

This page explains how to add support for a new instrument by writing a piec driver.

Where to put the file
---------------------

Drivers are organized by instrument category under ``src/piec/drivers/``. Place your
driver file directly in the appropriate category folder alongside the interface file:

.. code-block:: text

   src/piec/drivers/
   └── oscilloscope/            # Category folder
       ├── oscilloscope.py      # Level 2 interface
       ├── k_dsox3024a.py       # Level 3 driver (yours goes here)
       └── virtual_oscilloscope.py

If a suitable category folder does not exist, create one with a matching interface file.

Choosing the right base class
------------------------------

PIEC uses a 3-level hierarchy. Your driver (Level 3) should inherit from:

* The **Level 2 category class** (e.g., ``Oscilloscope``, ``Awg``, ``Dmm``, ``Lockin``)
  so that measurement code can use your driver interchangeably with others of the same
  type.
* The **Level 1 convenience class** ``Scpi`` if the instrument uses SCPI commands, or
  ``Instrument`` directly for non-SCPI instruments (serial, vendor API, etc.).

.. code-block:: python

   from .oscilloscope import Oscilloscope
   from ..scpi import Scpi

   class MyNewScope(Oscilloscope, Scpi):
       AUTODETECT_ID = "MY_SCOPE_MODEL"
       # Implementation ...

See :doc:`../user_guide/the_driver` for a full description of the hierarchy.

Implementing virtual mode
--------------------------

Every driver should support virtual mode — instantiation with ``'VIRTUAL'`` as the address —
so contributors and users can test without physical hardware. Each category also provides a
``VirtualInstrument`` (e.g., ``VirtualScope``) that returns simulated responses for
development and testing.

.. todo::
   Document the virtual mode convention in detail: which base class methods to override, how
   to generate synthetic responses, and how to write virtual mode tests.

Adding to the supported instruments table
-----------------------------------------

Once your driver is working, add a row to the table in :doc:`../supported_instruments` with
the class name, category, connection type, and any notes.