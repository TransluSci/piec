Jupyter Notebook Examples
=========================

Start here
----------

`AWG to oscilloscope <https://github.com/TransluSci/piec/blob/master/Measurements/Quickstart/quick_start.ipynb>`_
introduces instrument control with sine, square, and ramp waves applied to
the existing virtual ferroelectric sample. It runs
entirely with virtual instruments and needs no Measurement subclass.

.. image:: https://mybinder.org/badge_logo.svg
   :target: https://mybinder.org/v2/gh/TransluSci/piec/master?urlpath=lab/tree/Measurements/Quickstart/quick_start.ipynb
   :alt: Launch Binder

On Binder, run one cell at a time with **Shift+Enter**, from top to bottom.
Download your files before leaving.
For local setup, see :doc:`getting_started/quickstart`.

`Local AWG-to-scope testing <https://github.com/TransluSci/piec/blob/master/Measurements/Quickstart/quick_start_local.ipynb>`_
contains independent virtual and physical sections. Run the shared imports at
the top, then skip to the section you want. The physical example uses a
Keysight 81150A and DSOX3024A with channel 1 connected directly to channel 1.

More experiments
----------------

Notebooks live in the repository's ``Measurements/`` directory:

* `AMR <https://github.com/TransluSci/piec/blob/master/Measurements/AMR/AMR_testing.ipynb>`_:
  anisotropic magnetoresistance measurements.
* `Ferroelectric testing <https://github.com/TransluSci/piec/blob/master/Measurements/Ferroelectric%20Testing/FE_testing.ipynb>`_:
  hysteresis and PUND measurements.
* `IV sweeps <https://github.com/TransluSci/piec/blob/master/Measurements/DCIV/IV_sweep_testing.ipynb>`_:
  current-voltage measurements.

Review each notebook's instrument addresses and settings before running.
