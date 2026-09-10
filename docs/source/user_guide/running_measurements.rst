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

      from piec.drivers.awg.k_81150a import Keysight81150a
      from piec.drivers.oscilloscope.k_dsox3024a import KeysightDSOX3024a

      awg = Keysight81150a('GPIB0::8::INSTR')
      osc = KeysightDSOX3024a('GPIB0::7::INSTR')

   To run without hardware, instantiate the category's dedicated virtual driver
   instead (see :doc:`connecting_to_instrument`).

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
          output_dir='./data',
      )

3. **Run the experiment**

   Call ``run_experiment()`` to execute the full measurement sequence:

   .. code-block:: python

      data = experiment.run_experiment(save=True)

   Internally this method:

   * Configures the instrument to output the required waveform.
   * Sets up the oscilloscope (timebase, channels, trigger).
   * Triggers the waveform and captures the response.
   * Processes the data in memory using ``process_hysteresis()``.
   * Atomically publishes the analyzed dataset to ``output_dir`` alongside any generated plots.

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

``run_experiment(self, save=True, ...)``
   Orchestrates the full measurement: validates options, configures instruments, runs
   the acquisition, analyzes the data in memory, and publishes results atomically.

``configure_instruments(self)``
   Configures instruments for the experiment protocol (e.g. waveform definition, timebase,
   voltage scaling, trigger routing).

``capture_data(self)``
   Performs the acquisition sequence under strict safety and cooperative cancellation controls.

For experiment-specific parameters and examples, see the individual measurement pages:
:doc:`../measurements/ferroelectric`, :doc:`../measurements/amr`,
:doc:`../measurements/iv_sweep`.
