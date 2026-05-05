Quickstart
==========

This page walks you through a minimal example using PIEC's **virtual instrument mode** — no
real hardware required. You can run this example immediately after installing PIEC.

.. note::
   Virtual mode is built into every PIEC driver. It simulates instrument responses so you can
   test and develop measurement workflows without physical hardware. See
   :doc:`../user_guide/connecting_to_instrument` for details on virtual mode.

Running a virtual hysteresis measurement
-----------------------------------------

.. code-block:: python

   from piec.drivers.awg.virtual_awg import VirtualAwg
   from piec.drivers.oscilloscope.virtual_oscilloscope import VirtualScope
   from piec.measurement.discrete_waveform import HysteresisLoop

   awg = VirtualAwg()
   osc = VirtualScope()
   experiment = HysteresisLoop(awg, osc, save_dir='.')
   experiment.run_experiment()  # configures, captures, saves, and analyzes

``run_experiment()`` executes the full workflow: it configures both instruments,
generates a triangle waveform, triggers acquisition, saves the raw data to CSV,
and runs the hysteresis analysis automatically.

Swap ``VirtualAwg`` / ``VirtualScope`` for real drivers (or use ``autodetect``)
and the same code runs on hardware:

.. code-block:: python

   from piec.drivers.autodetect import autodetect

   awg   = autodetect('awg')
   scope = autodetect('scope')

Next steps
----------

* Read :doc:`../user_guide/running_measurements` for a deeper look at how measurements work.
* Browse :doc:`../measurements/ferroelectric`, and other measurement
  pages for experiment-specific documentation.