Adding a Driver
===============

This page explains how to add support for a new instrument by writing a piec driver.

Where to put the file
---------------------

Drivers are organized by instrument category under ``src/piec/drivers/``. Place your
driver file directly in the appropriate category folder alongside the interface file. 
For example, in the case of the Keysight DSOX 3024a, we navigate to the ``oscilloscope`` folder:

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
* **Optionally, a Level 1 convenience class** like ``Scpi`` (for SCPI commands) or ``Digilent`` 
  (for Digilent devices). If no convenience class fits, you do not need to inherit from one—your 
  driver will safely rely on the base ``Instrument`` features inherited by the Level 2 interface.

.. code-block:: python

   from .oscilloscope import Oscilloscope
   from ..scpi import Scpi

   class KeysightDSOX3024a(Oscilloscope, Scpi): # Scpi is optional!
       AUTODETECT_ID = "DSO-X 3024A"
       # Implementation ...

See :doc:`../user_guide/the_driver` for a full description of the hierarchy.

Class Attributes (Parameter Restrictions)
-----------------------------------------

Within the Level 2 interface and Level 3 drivers, class attributes are used to strictly define the valid boundaries for function arguments. The attribute's name MUST match the argument it restricts.

PIEC supports three formats for restricting parameters:

* **Discrete Lists**: For arguments accepting only specific values (e.g., ``channel = [1, 2]``).
* **Continuous Tuples**: For arguments accepting a continuous range, using a ``(min, max)`` geometric tuple (e.g., ``voltage = (-5.0, 5.0)``).
* **Dependent Dictionaries**: For arguments whose valid range depends on another parameter. The dictionary key is the name of the dependency (e.g., ``frequency = {'waveform': {'SIN': (0, 1e6)}}``).

Auto-Detection (AUTODETECT_ID)
------------------------------

All drivers SHOULD define a class-level string attribute named ``AUTODETECT_ID``. This attribute is a unique substring expected to be returned by the instrument when queried with a standard ``.idn()`` command (e.g., ``AUTODETECT_ID = "33220A"``).

If you do not define this attribute, it will not be possible to use your driver with PIEC's autodetection feature. The autodetection system works by scanning connected devices and matching their ``.idn()`` responses to the correct driver. It then dynamically caches this mapping over to a JSON registry file. If that registry file doesn't exist, PIEC will generate it automatically. 

For more details on this mechanism, see the :doc:`Autodetect Guide <../user_guide/connecting_to_instrument>`.

Method Conventions
------------------

When writing methods, strictly adhere to PIEC's naming and implementation conventions:

* **``set_<property>``**: Performs a single, explicit hardware action (e.g., ``set_frequency``).
* **``configure_<module>``**: Performs multiple actions by wrapping several ``set_`` commands. All non-essential parameters in its signature must natively default to ``None``.
* **``get_<property>``**: Returns a single, unformatted scalar value.
* **``read_<property>``**: Returns complex or formatted data structures (e.g., a ``pandas.DataFrame``).
* **``quick_read``**: A convenience function for fast polling of whatever data is immediately available or displayed on the hardware.
* **``run_<routine>``**: Hardware-executed routines (like sweeps) that perform an entire internal operation without software looping, returning the results directly.

Constructor and State Tracking
------------------------------

PIEC uses an ``AutoCheckMeta`` framework that automatically tracks the "last set" value of any parameter governed by a class attribute. If a ``set_<property>(value)`` succeeds, ``self._current_<property>`` is updated.

.. warning::
   Upon first connection, all tracked attributes are initialized to ``None``. Always perform a hardware query in your custom ``__init__`` method to synchronize these states immediately.

If you must override ``__init__``, ensure you accept ``*args, **kwargs`` and pass them to ``super()``:

.. code-block:: python

   def __init__(self, *args, **kwargs):
       super().__init__(*args, **kwargs)
       # Perform initial hardware queries to synchronize _current_ states

Optional Methods
----------------

Optional functionality guarantees measurement code works across basic and advanced instruments without changes.

1. **Interface Optionality**: Level 2 base classes can use the ``@optional`` decorator (imported from ``piec.drivers.instrument``) to stub features not supported universally.
2. **Child-Specific Auto-Skip**: Any custom public method you define in a Level 3 driver that does not natively exist in the parent class is automatically treated as optional. If a measurement calls it on a different driver that lacks it, PIEC safely skips it.

Example Template
----------------

For a full structural reference outlining these attributes and method conventions, check out the example driver:

.. literalinclude:: ../../../src/piec/drivers/example/example.py
   :language: python

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