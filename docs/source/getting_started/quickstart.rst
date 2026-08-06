Quickstart
==========

This page walks you through a minimal example using PIEC's **virtual instrument mode** — no
real hardware required. You can run this example immediately after installing PIEC.

.. note::
   Virtual mode is provided by dedicated virtual driver classes. The base driver does not
   simulate generic SCPI responses. See
   :doc:`../user_guide/connecting_to_instrument` for details on virtual mode.

Running a virtual hysteresis measurement
-----------------------------------------

.. code-block:: python

   from piec.drivers.awg.k_81150a import Keysight81150a
   from piec.drivers.oscilloscope.k_dsox3024a import KeysightDSOX3024a
   from piec.measurement.discrete_waveform import HysteresisLoop

   awg = Keysight81150a("VIRTUAL")
   osc = KeysightDSOX3024a("VIRTUAL")
   experiment = HysteresisLoop(awg, osc, save_dir='.')
   experiment.run_experiment()  # configures, captures, saves, and analyzes

``run_experiment()`` executes the full workflow: it configures both instruments,
generates a triangle waveform, triggers acquisition, saves the raw data to CSV,
and runs the hysteresis analysis automatically.

The exact ``"VIRTUAL"`` address selects each category's virtual implementation
while preserving the concrete model's capability attributes. Instantiate
``VirtualAwg`` or ``VirtualScope`` directly when generic category capabilities
are preferable.

Pass physical addresses instead (or use ``autodetect``) and the same code runs
on hardware:

.. code-block:: python

   from piec.drivers.autodetect import autodetect

   awg   = autodetect('awg')
   scope = autodetect('scope')

Next steps
----------

* Read :doc:`../user_guide/running_measurements` for a deeper look at how measurements work.
* Browse :doc:`../measurements/ferroelectric`, and other measurement
  pages for experiment-specific documentation.
