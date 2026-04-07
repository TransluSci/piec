Running Measurements
====================

PIEC organizes experiments as **measurement classes** — Python objects that bundle instrument
configuration, waveform generation, and data analysis into a single
``run_experiment()`` call. This page explains the general workflow that applies to all
measurement types.

General workflow
----------------

1. **Initialize instruments**

   Import and instantiate the driver(s) your measurement requires, passing each instrument's
   VISA address:

   .. code-block:: python

      from piec.drivers.keysight81150a import Keysight81150a
      from piec.drivers.keysightdsox3024a import KeysightDSOX3024A

      awg = Keysight81150a('GPIB0::8::INSTR')
      osc = KeysightDSOX3024A('GPIB0::7::INSTR')

   Use ``'virtual'`` as the address to run without hardware (see
   :doc:`connecting_to_instrument`).

2. **Create the measurement object**

   Instantiate the measurement class with your instrument objects and experimental parameters:

   .. code-block:: python

      from piec.measurement import HysteresisLoop

      experiment = HysteresisLoop(
          awg=awg,
          osc=osc,
          frequency=1000.0,   # Hz
          amplitude=5.0,      # Volts
          n_cycles=3,
          area=1.0e-9,        # m²
          save_dir='./data',
      )

3. **Run the experiment**

   Call ``run_experiment()`` to execute the full measurement sequence:

   .. code-block:: python

      experiment.run_experiment()

   Internally this method:

   * Configures the instrument to output the required waveform.
   * Sets up the oscilloscope (timebase, channels, trigger).
   * Triggers the waveform and captures the response.
   * Saves the raw data to ``save_dir``.
   * Calls ``analyze()`` to compute derived quantities and generate plots.

4. **Inspect the output**

   After ``run_experiment()`` completes, the saved data and any generated plots are in the
   directory you specified. See :doc:`data_and_analysis` for details on the file format and
   how to reload and post-process data.

Measurement class structure
----------------------------

All measurement classes follow the same pattern:

``__init__(self, ...)``
   Accepts instrument objects and measurement parameters. Stores them as instance attributes
   but does not yet configure any hardware.

``run_experiment(self)``
   Orchestrates the full measurement: configures instruments, runs the waveform/acquisition
   loop, saves data, and calls ``analyze()``.

``configure_instrument(self)``
   Implemented by each concrete measurement class. Builds and sends the specific waveform
   (e.g., triangular sweep for hysteresis, pulse sequence for PUND) to the instrument.

``analyze(self)``
   Implemented by each concrete measurement class. Reads the raw captured data, computes
   physical quantities (polarization, resistance, etc.), and generates plots.

For experiment-specific parameters and examples, see the individual measurement pages:
:doc:`../measurements/ferroelectric`, :doc:`../measurements/amr`,
:doc:`../measurements/iv_sweep`.