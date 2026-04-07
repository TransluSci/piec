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

.. todo::
   Add a self-contained virtual instrument example here that a new user can copy-paste and
   run immediately after ``pip install piec``. The example should:

   * Import the relevant driver(s) in virtual mode.
   * Create a ``HysteresisLoop`` measurement object.
   * Call ``run_experiment()``.
   * Show what the output looks like.

Next steps
----------

* Learn about the :doc:`../user_guide/guis` for a no-code interface.
* Read :doc:`../user_guide/running_measurements` for a deeper look at how measurements work.
* Browse :doc:`../measurements/ferroelectric`, and other measurement
  pages for experiment-specific documentation.