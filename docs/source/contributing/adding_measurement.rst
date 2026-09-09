Adding a Measurement
====================

This page explains how to add a new experiment type to piec. The complete,
normative guide and checklist are maintained in
``src/piec/measurement/MEASUREMENT_DEVELOPER_GUIDE.md``.

Where to put the file
---------------------

Measurements live in ``src/piec/measurement/``. Add your class to an existing module if it
fits a category that already exists (e.g., ``discrete_waveform.py`` for AWG + oscilloscope
experiments), or create a new module for a distinct experiment category:

.. code-block:: text

   src/piec/measurement/
   ├── base.py                # BaseMeasurement engine and session
   ├── contracts.py           # Lifecycle states, events, tokens, snapshots
   ├── runner.py              # Thread-safe MeasurementRunner
   ├── persistence.py         # Handle CSV writer, atomic publication, bundles
   ├── discrete_waveform.py   # AWG + oscilloscope experiments
   ├── magneto_transport.py   # Magnetotransport experiments
   └── your_category.py       # New module if needed

The Base Class
--------------

Every measurement class MUST inherit from ``BaseMeasurement``:

.. code-block:: python

   from piec.measurement import BaseMeasurement

   class MyMeasurement(BaseMeasurement):
       def __init__(self, instrument, *, output_dir=None, metadata=None):
           super().__init__(
               output_dir=output_dir,
               measurement_schema="my_schema",
               column_units={"voltage": "V", "current": "A"},
               metadata=metadata,
           )

Implementing Protected Lifecycle Hooks
--------------------------------------

``BaseMeasurement`` owns the public lifecycle methods (``run_experiment()``,
``session()``, ``configure_instruments()``, ``capture_data()``, ``safe_shutdown()``,
``request_stop()``, and ``snapshot()``). Subclasses **must not override** these public
methods; instead, implement the protected hooks:

``_validate_options(self, options)``
   Validate measurement-specific run options before acquiring an execution reservation.

``_configure_instruments(self, request)``
   Prepare each instrument (ranges, modes, triggers) while keeping outputs strictly disabled.

``_capture_data(self, request, on_update=None)``
   Execute the acquisition loop and return raw tabular data as a ``pandas.DataFrame``.
   Periodically check ``self._coordinator.is_stop_requested`` to support cooperative cancellation.

``_safe_shutdown(self, recorder=None)``
   De-energize hardware outputs and ramp safe states. This hook is guaranteed to execute
   on every exit path (success, cancellation, error, or interrupt).

``_analyze_data(self, raw_data, request)``
   Perform scientific calculations on raw data and return the analyzed ``pandas.DataFrame``.

``_stage_side_artifacts(self, data, request, reservation)``
   Optional hook for measurements that produce companion files (such as plots or summary logs)
   published atomically alongside the primary CSV.

Data Columns and Units
----------------------

All measurements enforce plain lowercase column names (e.g., ``voltage``, ``current``, ``time``).
Units are serialized exclusively in metadata through ``column_units_json``. Never embed unit
strings in column headers.

Background Execution with MeasurementRunner
-------------------------------------------

GUI applications and asynchronous tasks use ``MeasurementRunner`` to execute measurements
in dedicated non-daemon worker threads with bounded display queues and close coordination:

.. code-block:: python

   from piec.measurement import MeasurementRunner

   runner = MeasurementRunner(measurement)
   token = runner.start()

See ``src/piec/measurement/MEASUREMENT_DEVELOPER_GUIDE.md`` for the complete guide,
executable examples, safety policies, persistence details, and the developer review checklist.
