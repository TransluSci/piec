# Calibrated source/DMM MOKE

The headless `MokeMeasurement` uses one sourcemeter to command the magnet setup
and one DMM to read the detector's voltage output. It follows the standalone
`IVSweep` lifecycle. There is no AWG/scope dependency, required gaussmeter,
separate virtual measurement, or amplifier gain inside the measurement.

This implementation is a software-paced, point-by-point measurement. The
repository includes a `MeasurementApp` GUI and a sequential notebook under
`Measurements/MOKE`. Hardware-timed acquisition and automatic gaussmeter
calibration collection remain later steps.

## Runnable interfaces

`Measurements/MOKE/MOKE_GUI.py` provides instrument selection, in-plane or
out-of-plane geometry metadata, calibration loading, loop settings, safe stop,
and live raw/last-cycle/cycle-average plots. Its virtual path uses the ordinary
measurement with `VirtualSourcemeter`, `VirtualDMM`, and the separate
`HystereticMagneticMaterial`; it does not define a virtual measurement class.

`Measurements/MOKE/MOKE_testing.ipynb` runs that same virtual setup one step at
a time and includes commented templates for physical instruments and an
optional gaussmeter readout. The adjacent `moke_measurement.md` is the concise
operator guide.

## Calibration is a measurement input

`FieldCalibration` stores measured pairs of **direct sourcemeter output** and
field at the sample. If setting that sourcemeter to 5 V produces 500 Oe, record
`(5, 500)`. Any amplifier, current regulator, and magnet response is already
included in that pair. Do not multiply by another amplifier calibration.

```python
from piec.analysis.field_calibration import FieldCalibration

# Example only: replace these pairs with measurements of your assembled setup.
points = [(-5.0, -500.0), (0.0, 0.0), (1.0, 100.0), (5.0, 500.0)]
calibration = FieldCalibration(
    points, output_unit="V", field_unit="Oe", name="in_plane_setup"
)
assert calibration.field_at_output(5.0) == 500.0
assert calibration.output_at_field(250.0) == 2.5
calibration.save_csv("in_plane_calibration.csv")  # Refuses to overwrite.
calibration = FieldCalibration.load_csv("in_plane_calibration.csv")
```

Use `output_unit="A"` if the direct source command is current. Field units are
explicit labels, not implicit conversions. Curves can be nonlinear and either
increasing or decreasing. Interpolation is piecewise linear; extrapolation is
rejected. Inverse lookup requires strictly monotonic field values.

To collect a calibration manually, select a **source setting**, apply it using
your setup's safe operating procedure, wait for settling, read the gaussmeter,
and record both numbers. Repeat, then pass the resulting list to
`FieldCalibration`. For example, after applying 1 V and observing 98 Oe, append
`(1.0, 98.0)` to the list. The list can start empty; creating the usable curve
requires at least two distinct source settings. No existing calibration is
required to collect those pairs, and the measurement must not invent a curve.

The CSV columns are `source_output,field,output_unit,field_unit,name`; `name` is
optional when loading. Units must be consistent across the table. The
`Measurements/MOKE/example_calibration.csv` table is illustrative simulation
data, not a calibration for anyone's real hardware.

This version represents a single-valued output-to-field relationship. It does
not implement a history-dependent magnet calibration or branch-specific curves.
If repeated source settings produce different measured fields, do not collapse
them into a falsely unique inverse calibration. Sample hysteresis and magnet
calibration are separate concerns.

## Measurement usage

Supply already constructed source and DMM drivers. Values in `output_values`
are in **source units**, not magnetic-field units. They describe one complete
cycle, including the return to the starting setting.

```python
import numpy as np
from piec.measurement.moke import MokeMeasurement

outputs = np.r_[np.linspace(-5, 5, 101), np.linspace(5, -5, 101)[1:]]
experiment = MokeMeasurement(
    sourcemeter=source,
    dmm=detector_dmm,
    calibration=calibration,
    output_values=outputs,
    compliance=0.01,       # A for voltage sourcing; V for current sourcing
    max_output_step=0.1,  # Source units per programmed ramp increment
    ramp_delay=0.01,      # Seconds between ramp increments
    dwell_time=0.1,       # Seconds at each acquired setpoint
    n_cycles=3,
    geometry="in_plane",
    output_dir="results",
)
data = experiment.run_experiment()
```

The numerical limits above are examples, not recommended hardware settings.
Choose compliance, ramp increments, and settling time for the actual setup.
The caller provides the geometry-appropriate instrument and calibration;
geometry does not silently select channels or alter the calibration. The
default source channel is the driver's default. An explicit `source_channel`
requires a driver supporting the standard channel argument.

To sweep specified fields, first convert your closed field sequence with
`calibration.output_at_field(fields)` and pass those outputs to the constructor.
For piecewise operation, use `with experiment.session(save=False) as session:`
and call `session.configure_instruments()` and `session.capture_data()` inside
that scope. Shutdown runs on session exit. Standalone configure/capture calls
create their own transient scopes and safe on return. `set_output(value)` and
`set_field(value)` only program the source; they do not enable output. They require
the current execution owner or an idle command lease, rejecting foreign threads.

Each acquired row stores actual elapsed time, cycle and point indices, sweep
direction, commanded source output, calibrated field, and raw detector voltage.
Calibrated field is an estimate from the command, **not a live measured field**.
Source limiting/compliance or a changed physical setup can invalidate that
estimate; this version does not monitor source readback or compliance status.

An optional `on_update(snapshot)` callback receives data after every DMM read.
When a field reader is enabled, the callback follows both detector and field
reads, so each published row contains a complete pair.
`experiment.raw_data` retains the complete acquired dataset after a run.
Snapshots provide a bounded raw window, the last complete cycle, and the average
of complete cycles. Averaging is by point in the ordered cycle, so opposite
branches at the same field are not combined. Partial cycles remain in raw/saved
data but do not enter the average. Call `request_stop()` for cooperative
cancellation. A stopped measurement saves acquired rows when saving is enabled.

The normal lifecycle is configure, capture, shut down, analyze, save, update
`run_records`. Analysis retains detector volts; it does not claim to calibrate Kerr
angle or magnetization. Files use the existing metadata-plus-data CSV format,
including a JSON copy of the full calibration table and its units. Exceptions
leave partial data available on the object but do not automatically save it.

The default shutdown ramps the command to electrical zero and disables output.
This is not a degaussing routine, and zero command does not guarantee zero field.
For hardware requiring a different discharge/shutdown sequence, inject
`shutdown_handler=callback` (called as `callback(source)`); that callback owns the complete safe-state procedure.
The setup must begin idle and be exclusively controlled by this measurement.

## Optional measured-field plotting

Supply `field_reader`, a no-argument callable returning one measured magnetic
field value, to use a gaussmeter for the plot's field axis. The repository has
no common gaussmeter driver interface yet: pass your device's bound read method
or a setup-specific conversion function rather than requiring a particular
instrument model. Configure the gaussmeter externally before running MOKE.

Add these keyword arguments to the constructor above:

```python
field_reader=read_field_in_oe,  # Your configured readout function
field_reader_unit="Oe",       # Must explicitly match calibration.field_unit
field_reader_name="Lab gaussmeter",  # Prefer its instrument identity/model
```

For a gaussmeter whose analog output is read through a second DMM, the callable
can apply its **readout** conversion, independent of the source calibration:

```python
def read_field_in_oe():
    return field_dmm.get_voltage() * gaussmeter_oe_per_volt
```

Use the readout conversion appropriate to your configured instrument; the
measurement does not guess scales, equate units, or perform unit conversions.
`field_reader_unit` declares the callable's final field units, not volts.

With this option enabled, both `field_calibrated` and
`field_measured` are retained in raw data, the last cycle, and the cycle
average. `experiment.field_column` and `snapshot.field_column` select the
measured column. With no field reader they select the calibrated column, and
there is no measured-field column. Plotting code can use the same expression:

```python
snapshot = experiment.snapshot()
ax.plot(
    snapshot.last_cycle[snapshot.field_column],
    snapshot.last_cycle["detector_voltage"],
)
ax.set_xlabel(f"{snapshot.field_column} ({experiment.calibration.field_unit})")
ax.set_ylabel("detector_voltage (V)")
```

This is field readout for plotting, **not closed-loop field control**. Source
commands and the supplied calibration are unchanged. Each setpoint settles,
then the detector and field reader are read sequentially. `time` and
`field_time` record their respective read-completion times; they are not
simultaneous hardware-triggered samples. Sweep direction follows the calibrated
command sequence, not noisy measured-field differences.

The cycle average averages both measured field and detector voltage by matching
point indices of complete cycles. It does not regrid detector readings onto a
common measured-field axis or mix the two sweep branches. Saved metadata records
the selected field column, readout name, units, and sequential acquisition.

If an enabled field reader raises an error or returns an invalid/non-finite
value, acquisition stops and executes the normal safe shutdown. Completed pairs
remain available, but the failing pair is not appended. There is no silent
substitution of calibrated field for a failed gaussmeter reading.

## Magnetic material simulation

`HystereticMagneticMaterial` takes magnetic field, not volts or calibration.
It retains a population of switching-domain states, so the same field can give
different magnetization after different histories. The model is qualitative,
deterministic, and independent of both measurement classes and drivers.

```python
from piec.simulation.hysteretic_magnetic_material import HystereticMagneticMaterial

material = HystereticMagneticMaterial(coercive_field=50, switching_width=10)
magnetization = material.response([-500, 0, 500, 0, -500])
# [-1, -1, +1, +1, -1]: opposite remanence at zero field.
detector_volts = 0.5 + 0.02 * magnetization  # Example optical setup, not calibration.
```

All material field parameters use the same units as its field input. The
simulated setup maps source output to field, applies field to the material,
and converts magnetization into detector voltage. That wiring is separate
from the source/DMM interfaces. The existing `VirtualDMM` is not automatically
a simulated optical detector: this work does not change its existing behavior.
Tests use the unchanged `VirtualSourcemeter` plus a voltage-reader test double
to exercise the ordinary MOKE measurement against this model.

## GUI execution

The MOKE GUI uses `MeasurementRunner` with a non-daemon worker, bounded display
queue, and separate lossless control queue. Tk polls queues on its own thread.
Terminal receipt does not imply worker exit; instrument connections are closed
only after the worker has exited and the runner confirms safe closing. Unsafe
shutdown retains connections for recovery and blocks normal closing.
