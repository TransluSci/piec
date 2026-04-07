Adding a Measurement
====================

This page explains how to add a new experiment type to piec.

Where to put the file
---------------------

Measurements live in ``src/piec/measurement/``. Add your class to an existing module if it
fits a category that already exists (e.g., ``discrete_waveform.py`` for AWG + oscilloscope
experiments), or create a new module for a distinct experiment category:

.. code-block:: text

   src/piec/measurement/
   ├── discrete_waveform.py   # AWG + oscilloscope experiments
   ├── magneto_transport.py   # Magnetotransport experiments
   └── your_category.py       # New module if needed

Choosing the right base class
------------------------------

* Inherit from ``DiscreteWaveform`` if your experiment uses an AWG to apply a waveform and
  an oscilloscope to capture the response.
* Inherit from ``MagnetoTransport`` for experiments involving magnetic fields and transport
  measurements.
* Inherit from the base ``Measurement`` class directly for experiments that don't fit an
  existing category.

Implementing the required methods
-----------------------------------

Your measurement class must implement:

``configure_awg(self)``
   Build and send the specific waveform or pulse sequence to the AWG. Called automatically
   by ``run_experiment()``.

``analyze(self)``
   Read the raw captured data, compute physical quantities, and generate / save plots.
   Call the appropriate function from ``piec.analysis`` if one exists.

Adding analysis functions
--------------------------

If your measurement requires new analysis code, add it to the appropriate module in
``src/piec/analysis/`` (e.g., ``hysteresis.py``, ``pund.py``), or create a new module.
Document each public function with a docstring that describes arguments, return values, and
units.

Writing tests
--------------

.. todo::
   Describe how to write a test for a new measurement using virtual instrument drivers so
   the test can run in CI without hardware.

Documenting the measurement
-----------------------------

Add a new ``.rst`` file to ``docs/source/measurements/`` following the template of existing
pages (:doc:`../measurements/ferroelectric`, etc.). Then add it to
the ``Measurements`` toctree in ``docs/source/index.rst``.