Galvanostatic Charge-Discharge (GCD)
=======================================

``piec.measurement.gcd.GCD`` sources a constant positive current until the
upper terminal-voltage cutoff, then a constant negative current until the lower
cutoff. It repeats this pair ``n_cycles`` times and plots voltage versus time.
The same class and protocol run on physical and virtual sourcemeters. The first
charge begins at the attached cell's present state of charge. Physical runs use
wall-clock timing; only virtual runs attach a simulated battery and may accelerate
time.

Run the virtual demo
--------------------

From the repository root with PIEC installed (``python -m pip install -e .``):

.. code-block:: console

   python Measurements/GCD/gcd_virtual.py --cycles 3 --current 0.01 --voltage-lower 3.1 --voltage-upper 4.1

This entry point always constructs ``Keithley2400('VIRTUAL')`` and never opens a
hardware connection. Simulation time advances instantly, with no wall-clock
sleep. CSV and PNG files are saved under ``scratch/gcd`` by default. Add
``--show-plots`` to display the plot, or ``--save-dir`` to choose an output folder.
Use ``--help`` for battery capacity, initial state of charge, sampling interval,
voltage compliance, and half-cycle timeout options.

GUI and notebook
-----------------

Launch the desktop GUI with:

.. code-block:: console

   python Measurements/GCD/gcd_GUI.py

The GUI follows ``Measurements/AMR/amr_GUI.py``: it subclasses the shared
``MeasurementApp``, uses its save-directory browser, console, plot toolbar and
settings persistence, and runs acquisition on a background thread. Configure
current, voltage cutoffs, cycles, sampling interval, timeout, compliance,
and sense mode, then click **Run Measurement** or press **Ctrl+Enter**. The
instrument selector defaults to ``VIRTUAL``, retains shared Refresh/Autodetect,
and accepts manually entered VISA addresses. Axis dropdowns default to voltage
versus time. Battery capacity and initial SOC inputs apply only to virtual SMUs.

**Pause** disables SMU output and suspends acquisition time; **Resume** continues
the same half-cycle. **Stop** saves partial data with ``status='aborted'``.
Closing during a run stops and saves before isolating the output and releasing
the connection. Cleanup does not reset the instrument. Each virtual run starts
with a fresh simulated battery and restores the previous shared virtual sample
afterward. Physical runs use the connected cell and ignore simulation settings.

**Animate virtual run** adds a small display delay between readings so live
plots and Pause/Stop are easy to inspect. This does not change simulated time.
Clear it for the fastest run. **Save voltage plot** saves the PNG beside the CSV.
The shared close dialog offers to save inputs and plot selections for next time.

Open ``Measurements/GCD/GCD_testing.ipynb`` in Jupyter for the notebook workflow.
It follows the AMR notebook's imports, instrument setup, measurement parameters,
run, CSV reload, and plotting sections, with an additional cycle summary and
explicit cleanup. Run cells from top to bottom using a kernel with this checkout
installed. Its address defaults to ``VIRTUAL``; replace ``smu_address`` with the
physical SMU's VISA address for wall-clock operation. The run cell checks the
actual driver type before attaching a battery or enabling accelerated time.

Python usage
------------

.. code-block:: python

   from piec.drivers.sourcemeter.keithley2400 import Keithley2400
   from piec.drivers.virtual_instrument import VirtualInstrument
   from piec.measurement.gcd import GCD
   from piec.simulation.battery import Battery

   smu = Keithley2400('VIRTUAL')
   # For physical operation, use the SMU's VISA address instead of VIRTUAL.
   virtual = isinstance(smu, VirtualInstrument)
   original_sample = smu.sample if virtual else None
   try:
       if virtual:
           smu.sample = Battery(capacity_ah=0.001, initial_soc=0.2)
       experiment = GCD(
           smu, current=0.01, voltage_lower=3.1, voltage_upper=4.1,
           n_cycles=3, sample_interval=1.0, max_half_cycle_time=1000,
           voltage_compliance=5.0, virtual_time=virtual,
           save_dir='scratch/gcd', show_plots=False, save_plots=True)
       experiment.run_experiment()
   finally:
       # run_experiment handles output isolation, including errors and Stop.
       if virtual:
           VirtualInstrument.set_virtual_sample(original_sample)

Physical SMUs and output-off state
----------------------------------

The SMU must support both current polarities and explicitly implement
``set_off_mode(off_mode='HIMP')``, advertising ``HIMP`` in its ``off_mode``
capabilities. The Keithley 2400 and the virtual sourcemeter implement this
interface. GCD rejects missing HIMP support before sending output commands.
Simulation settings never grant physical drivers access to accelerated timing.

GCD selects HIMP **before** the first output-off command, then configures current
sourcing, voltage compliance, and sense wiring. Charge/discharge reversals change
the current setpoint without switching the relay off and on at every reversal.
Pause isolates the output; Resume continues the same half-cycle. Stop and Pause
are checked during wall-clock waits in intervals of at most 50 ms. An ongoing
instrument query remains subject to the transport's timeout.

``safe_close()`` overrides Experiment's default reset/initialize cleanup. It
reapplies HIMP, disables output, and sets the current setpoint to zero, attempting
all three operations even if one fails. A reset is deliberately omitted: the
Keithley 2400 reset default is NORM, which is unsuitable for leaving a battery
connected. See `Keithley's battery-cycling application note
<https://www.tek.com/de/documents/application-note/807-battery-discharge-charge-cycling-using-keithley-series-2400-sourcemete>`_.

The GUI's close handler and notebook cleanup use this same shutdown. A shutdown
failure is reported rather than claiming output is off. If acquisition and
shutdown both fail, the acquisition exception is preserved and ``cleanup_error``
records the shutdown failure. A save failure leaves data available in memory
and records ``save_error``.

Physical behavior is tested with a scripted transport and a controlled clock;
no physical instruments were connected or operated during development. Set
current, cutoffs, compliance, and wiring for the actual cell before physical use.

Existing simulation support and additions
-----------------------------------------

The existing ``VirtualSourcemeter`` already implements the SMU's current-source
configuration, current sign changes, voltage/current reads, and voltage
compliance. Virtual samples are shared across instruments through
``VirtualInstrument.set_virtual_sample`` or ``smu.sample``. Replacing a sample
therefore affects other virtual instruments too; the demo restores it afterward.

The default sample is a ``Ferroelectric``. Its inherited ``current_response``
is a pass-through, and the virtual SMU supplies a zero time coordinate on reads.
It has no battery capacity or state of charge, so it cannot produce GCD cycling.
``Resistor`` is also static, and ``Dielectric`` does not integrate sourced current.

Two simulation additions supply the missing behavior:

* ``Battery(Sample)`` stores capacity, state of charge, a linear open-circuit
  voltage curve, and a series resistance. Positive current charges the battery:
  ``SOC += current * seconds / (3600 * capacity_ah)``. Terminal voltage is
  ``voltage_empty + SOC * (voltage_full - voltage_empty) + current * resistance``.
* ``VirtualSourcemeter.advance_time(seconds)`` applies the actual simulated
  current to a dynamic sample without sleeping. Reads alone never change SOC;
  output-off stepping applies zero current. When voltage compliance limits the
  source, the returned current reflects the sample response to the limited voltage.

The battery is a deterministic demonstration model, without chemistry, aging,
thermal effects, or self-discharge. SOC clamps to [0, 1]. An unreachable voltage
cutoff terminates at ``max_half_cycle_time`` rather than cycling forever.

Measurement conventions and outputs
-------------------------------------

GCD inherits the current ``Experiment`` base, declares
``_instruments = ('sourcemeter',)``, and uses the standard filename and
metadata/data CSV helpers. Each CSV contains configuration, SMU ID, timestamp,
run status, completed cycle count, and virtual sample parameters, followed by
``time (s)``, ``voltage (V)``, ``current (A)``, ``cycle`` (one-based), and ``phase``
(``charge`` or ``discharge``). History stores an independent metadata snapshot.
The ``processed`` flag remains false because the saved values are raw readings.

Cutoffs are checked at each measured point. Voltage may cross a cutoff by one
sampling interval; reducing ``sample_interval`` reduces this overshoot. Charge
and discharge can share a timestamp at reversal, showing the instantaneous
series-resistance voltage step. Compliance must exceed both cutoff magnitudes
so the measurement can reach them while sourcing constant current.

Output is disabled even on timeout, interruption, or read failure. Partial data
is saved with ``status='aborted'`` and the exception is re-raised. Completed runs
save a voltage-versus-time PNG beside the CSV. Both measurement and simulation
parameters are validated before the run. Physical SMUs always use wall-clock
timing (``virtual_time=False``); virtual SMUs with a dynamic sample may use
``virtual_time=True`` for acceleration. The hardware-independent protocol is the
same in either mode.

For interactive control, ``GCD`` exposes AMR-style ``pause_requested`` and
``abort_requested`` flags plus ``get_data_snapshot()`` for safe live plotting.
``simulation_delay`` defaults to zero and can pace virtual runs for display;
it never changes the simulated sampling interval. GUI plotting and PNG saving
run on the main thread, while the measurement worker handles acquisition and CSV.

Call ``run_experiment()`` again after Stop to restart the same measurement
instance. Terminal runs clear stale abort/pause flags, reset elapsed time and
cycle count, create a new CSV, and retain earlier history snapshots. A direct
virtual rerun continues from the attached sample's SOC; the GUI and notebook run
cell attach a fresh battery for repeatable demonstrations.
