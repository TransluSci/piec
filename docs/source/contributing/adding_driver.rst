Adding a Driver
===============

This page explains how to add support for a new instrument by writing a piec driver.

Where to put the file
---------------------

Each driver lives in its own subdirectory under ``src/piec/drivers/``. The directory name
should be a short, lowercase identifier for the instrument model (e.g., ``keysight81150a``).
Inside it, create a ``core.py`` file containing the driver class:

.. code-block:: text

   src/piec/drivers/
   └── your_instrument/
       ├── __init__.py
       └── core.py

Export the class from ``__init__.py`` so it can be imported as
``from piec.drivers.your_instrument import YourInstrument``.

Choosing the right base class
------------------------------

Select the base class that matches your instrument:

* Inherits from ``SCPI_Instrument`` if the instrument uses SCPI commands.
* Inherits from ``Instrument`` directly for non-SCPI instruments (serial, vendor API, etc.).
* Also inherit from the appropriate generic category class (e.g., ``Oscilloscope``, ``AWG``)
  so that measurement classes can use your driver interchangeably with others of the same
  type.

See :doc:`../user_guide/the_driver` for a full description of the hierarchy.

Implementing virtual mode
--------------------------

Every driver should support virtual mode — instantiation with ``'virtual'`` as the address —
so contributors and users can test without physical hardware.

.. todo::
   Document the virtual mode convention in detail: which base class methods to override, how
   to generate synthetic responses, and how to write virtual mode tests.

Adding to the supported instruments table
-----------------------------------------

Once your driver is working, add a row to the table in :doc:`../supported_instruments` with
the class name, category, connection type, and any notes.