Quickstart
==========

Your first signal: AWG to oscilloscope
----------------------------------------

Start with the `AWG-to-scope notebook
<https://github.com/TransluSci/piec/blob/master/Measurements/Quickstart/quick_start.ipynb>`_.
Apply a sine, square, or ramp wave to the shared virtual ferroelectric sample,
plot the scope response, and save a CSV. No hardware or Measurement subclass needed.

.. image:: https://mybinder.org/badge_logo.svg
   :target: https://mybinder.org/v2/gh/TransluSci/piec/master?urlpath=lab/tree/Measurements/Quickstart/quick_start.ipynb
   :alt: Launch the AWG-to-scope notebook on Binder

When JupyterLab opens, run one cell at a time with **Shift+Enter**, from top
to bottom. Start with the sine wave, then try the square wave and ramp. The first Binder build can take several minutes. Download
your results before leaving: the session's files are temporary.

To run locally, clone the repository and run these commands from its root::

   python -m pip install -e . jupyterlab
   python -m jupyter lab Measurements/Quickstart/quick_start.ipynb

For physical instruments, open the separate `local testing notebook
<https://github.com/TransluSci/piec/blob/master/Measurements/Quickstart/quick_start_local.ipynb>`_.
Run its imports cell, then skip to either the virtual or physical section.
See the :doc:`../user_guide/connecting_to_instrument` guide for VISA setup.
Binder runs remotely and cannot access your local USB/GPIB instruments.
See :doc:`../notebook_examples` for more examples.

Prefer a GUI? From the repository root, run::

   python Measurements/Quickstart/quick_start_local_GUI.py

Choose Virtual mode or connect physical instruments with the dropdowns or Autodetect.
Capture sine, square, or ramp waveforms, inspect them directly in the plot window,
and optionally save captures to CSV. This desktop GUI runs locally, not on Binder.

For a complete measurement workflow, try the hysteresis example below using
PIEC's **virtual instrument mode**. You can run it after installing PIEC.

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
