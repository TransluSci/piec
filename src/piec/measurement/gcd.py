"""Galvanostatic charge-discharge cycling through the sourcemeter interface."""

import math
import operator
from pathlib import Path
import time
import threading

import matplotlib.pyplot as plt
from matplotlib.figure import Figure
import pandas as pd

from piec.analysis.utilities import create_measurement_filename, metadata_and_data_to_csv
from piec.drivers.virtual_instrument import VirtualInstrument
from piec.measurement.experiment import Experiment


class GCD(Experiment):
    """Charge at +current and discharge at -current between voltage cutoffs.

    Parameters use SI units: current (A), voltage limits/compliance (V), sampling
    interval and maximum half-cycle duration (s). ``n_cycles`` counts complete
    charge/discharge pairs. Cutoffs use measured terminal voltage, so crossing
    can overshoot by one sampling interval. ``voltage_compliance`` must exceed
    both cutoff magnitudes. Physical SMUs use wall-clock timing. For a virtual
    SMU with a dynamic sample, ``virtual_time=True`` accelerates the same protocol.
    The driver must explicitly support high-impedance (HIMP) output-off mode.

    Uses Experiment metadata/history and PIEC's standard metadata-plus-data CSV.
    Failed runs retain and save partial data with status='aborted', then raise.
    Output is disabled on completion, timeout, interruption, or read failure.
    """

    mtype = 'gcd'
    _instruments = ('sourcemeter',)
    _columns = ['time (s)', 'voltage (V)', 'current (A)', 'cycle', 'phase']

    def __init__(self, sourcemeter, current=0.01, voltage_lower=3.1,
                 voltage_upper=4.1, n_cycles=3, sample_interval=1.0,
                 max_half_cycle_time=1000.0, voltage_compliance=5.0,
                 sense_mode='2W', virtual_time=False, save_dir='scratch',
                 show_plots=True, save_plots=True, simulation_delay=0.0):
        self.sourcemeter = sourcemeter
        self.current = current
        self.voltage_lower = voltage_lower
        self.voltage_upper = voltage_upper
        self.n_cycles = n_cycles
        self.sample_interval = sample_interval
        self.max_half_cycle_time = max_half_cycle_time
        self.voltage_compliance = voltage_compliance
        self.sense_mode = sense_mode
        self.off_mode = 'HIMP'
        self.virtual_time = virtual_time
        self.show_plots = show_plots
        self.save_plots = save_plots
        self.simulation_delay = simulation_delay
        self.abort_requested = False
        self.pause_requested = False
        self._data_lock = threading.Lock()
        self._rows = []
        self._paused_duration = 0.0
        self.data = None
        self.filename = None
        self.plot_filename = None
        self.completed_cycles = 0
        self.status = 'ready'
        self.cleanup_error = None
        self.save_error = None
        self._validate_parameters()
        super().__init__(save_dir=save_dir)

    def _validate_parameters(self):
        for name in ('current', 'voltage_lower', 'voltage_upper',
                     'sample_interval', 'max_half_cycle_time', 'voltage_compliance'):
            if not math.isfinite(getattr(self, name)):
                raise ValueError(f'{name} must be finite')
        if self.current <= 0 or self.sample_interval <= 0 or self.max_half_cycle_time <= 0:
            raise ValueError('current, sample_interval, and max_half_cycle_time must be positive')
        if not math.isfinite(self.simulation_delay) or self.simulation_delay < 0:
            raise ValueError('simulation_delay must be finite and nonnegative')
        if self.voltage_lower >= self.voltage_upper:
            raise ValueError('voltage_lower must be below voltage_upper')
        if self.voltage_compliance <= max(abs(self.voltage_lower), abs(self.voltage_upper)):
            raise ValueError('voltage_compliance must exceed both voltage cutoff magnitudes')
        if isinstance(self.n_cycles, bool) or operator.index(self.n_cycles) < 1:
            raise ValueError('n_cycles must be a positive integer')
        if self.sense_mode not in ('2W', '4W'):
            raise ValueError("sense_mode must be '2W' or '4W'")
        setter = getattr(type(self.sourcemeter), 'set_off_mode', None)
        if ('HIMP' not in getattr(type(self.sourcemeter), 'off_mode', ())
                or not callable(setter) or getattr(setter, '_is_optional', False)):
            raise ValueError('GCD requires implemented HIMP output-off support')
        # Reject out-of-range requests before a model-profiled virtual SMU can
        # silently clamp them (or a real instrument rejects them).
        for name, values in (('current', (-self.current, self.current)),
                             ('voltage_compliance', (self.voltage_compliance,))):
            lo, hi = getattr(self.sourcemeter, name)
            if any((lo is not None and v < lo) or (hi is not None and v > hi) for v in values):
                raise ValueError(f'{name} exceeds sourcemeter capabilities')
        if self.virtual_time:
            if (not isinstance(self.sourcemeter, VirtualInstrument)
                    or not callable(getattr(type(self.sourcemeter), 'advance_time', None))):
                raise ValueError('virtual_time requires a virtual SMU with advance_time support')
            if not callable(getattr(self.sourcemeter.sample, 'advance_time', None)):
                raise ValueError('virtual_time requires a dynamic virtual sample, such as Battery')

    def configure_sourcemeter(self):
        """Configure current sourcing, voltage sensing, and wiring with output off."""
        # Select HIMP before the first OFF command; NORM can load a battery.
        self.sourcemeter.set_off_mode(off_mode=self.off_mode)
        self.sourcemeter.output(on=False)
        self.sourcemeter.configure_current_source(
            current=0.0, voltage_compliance=self.voltage_compliance)
        self.sourcemeter.set_sense_function(sense_func='VOLT')
        self.sourcemeter.set_sense_mode(sense_mode=self.sense_mode)

    def safe_close(self):
        """Isolate the cell and clear the current setpoint without resetting SMU.

        A factory reset restores NORM on the Keithley 2400, so Experiment's
        default initialize/reset cleanup is inappropriate for an attached battery.
        Attempt every shutdown operation even if another command fails.
        """
        errors = []
        for operation in (
                lambda: self.sourcemeter.set_off_mode(off_mode=self.off_mode),
                lambda: self.sourcemeter.output(on=False),
                lambda: self.sourcemeter.set_source_current(current=0.0)):
            try:
                operation()
            except Exception as error:
                errors.append(error)
        if errors:
            raise RuntimeError('GCD shutdown failed: ' + '; '.join(map(str, errors))) from errors[0]

    def get_data_snapshot(self):
        """Return an independent snapshot for a GUI polling during acquisition."""
        with self._data_lock:
            rows = list(self._rows)
        return pd.DataFrame(rows, columns=self._columns)

    def _check_controls(self):
        """Honor AMR-style pause/abort flags with output disabled during pauses."""
        if self.abort_requested:
            return False
        if self.pause_requested:
            paused_at = time.monotonic()
            self.sourcemeter.output(on=False)
            while self.pause_requested and not self.abort_requested:
                time.sleep(0.05)
            self._paused_duration += time.monotonic() - paused_at
            if self.abort_requested:
                return False
            self.sourcemeter.output(on=True)
        return True

    def _wait_interval(self, seconds):
        """Wait in short intervals so Stop/Pause respond during long dwells."""
        deadline = time.monotonic() + seconds
        while True:
            paused_before = self._paused_duration
            if not self._check_controls():
                return False
            deadline += self._paused_duration - paused_before
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return True
            time.sleep(min(0.05, remaining))

    def cycle(self):
        """Capture every half-cycle, retaining partial samples even on failure."""
        with self._data_lock:
            self._rows = []
        self._paused_duration = 0.0
        elapsed = 0.0
        start = time.monotonic()
        try:
            for cycle in range(1, self.n_cycles + 1):
                for phase, current, cutoff in (
                        ('charge', self.current, self.voltage_upper),
                        ('discharge', -self.current, self.voltage_lower)):
                    if self.abort_requested:
                        return
                    self.sourcemeter.set_source_current(current=current)
                    self.sourcemeter.output(on=True)
                    phase_start = elapsed if self.virtual_time else time.monotonic() - start - self._paused_duration
                    while True:
                        if not self._check_controls():
                            return
                        if not self.virtual_time:
                            elapsed = time.monotonic() - start - self._paused_duration
                        voltage = float(self.sourcemeter.get_voltage())
                        measured_current = float(self.sourcemeter.get_current())
                        if not math.isfinite(voltage) or not math.isfinite(measured_current):
                            raise ValueError('Sourcemeter returned a non-finite reading')
                        if not self.virtual_time:
                            elapsed = time.monotonic() - start - self._paused_duration
                        with self._data_lock:
                            self._rows.append((elapsed, voltage, measured_current, cycle, phase))
                        if (phase == 'charge' and voltage >= cutoff) or (
                                phase == 'discharge' and voltage <= cutoff):
                            break
                        remaining = self.max_half_cycle_time - (elapsed - phase_start)
                        if remaining <= 1e-9:
                            raise TimeoutError(f'Cycle {cycle} {phase} did not reach {cutoff} V')
                        step = min(self.sample_interval, remaining)
                        if self.virtual_time:
                            self.sourcemeter.advance_time(step)
                            elapsed += step
                            if self.simulation_delay and not self._wait_interval(self.simulation_delay):
                                return
                        else:
                            if not self._wait_interval(step):
                                return
                self.completed_cycles = cycle
        finally:
            self.data = self.get_data_snapshot()

    def save_data(self):
        """Save parameters, instrument ID, run status, and captured data to CSV."""
        if self.data is None:
            raise RuntimeError('No data to save; run the experiment first')
        if self.filename is None:
            self.filename = create_measurement_filename(self.save_dir, self.mtype)
        self._update_metadata()
        metadata_and_data_to_csv(self.metadata, self.data, self.filename)

    def analyze(self):
        """Plot voltage versus elapsed time and optionally save a PNG beside CSV."""
        if self.data is None or self.data.empty:
            return
        if not self.show_plots and not self.save_plots:
            return
        if self.show_plots:
            fig, ax = plt.subplots()
        else:
            # Saving a PNG must not create a Tk window when used by a GUI.
            fig = Figure()
            ax = fig.subplots()
        try:
            ax.plot(self.data['time (s)'], self.data['voltage (V)'])
            ax.set(xlabel='Time (s)', ylabel='Voltage (V)', title='GCD cycling')
            ax.axhline(self.voltage_lower, color='gray', linestyle='--', linewidth=0.8)
            ax.axhline(self.voltage_upper, color='gray', linestyle='--', linewidth=0.8)
            fig.tight_layout()
            if self.save_plots:
                if self.filename is None:
                    raise RuntimeError('Save data before saving its plot')
                self.plot_filename = str(Path(self.filename).with_suffix('.png'))
                fig.savefig(self.plot_filename, dpi=150)
            if self.show_plots:
                plt.show()
        finally:
            plt.close(fig)

    def run_experiment(self):
        """Configure, cycle, disable output, save, plot, and record history."""
        if self.status == 'running':
            raise RuntimeError('This GCD experiment is already running')
        self._validate_parameters()
        # A new run on a stopped/completed instance starts with fresh controls.
        # On first entry, preserve controls queued by the GUI before its worker starts.
        if self.status != 'ready':
            self.abort_requested = False
            self.pause_requested = False
        self.data = None
        self.filename = None
        self.plot_filename = None
        self.completed_cycles = 0
        self.cleanup_error = None
        self.save_error = None
        with self._data_lock:
            self._rows = []
        self.status = 'running'
        self.__dict__.pop('simulation_sample', None)
        error = None
        try:
            if isinstance(self.sourcemeter, VirtualInstrument):
                sample = self.sourcemeter.sample
                self.simulation_sample = {
                    'name': sample.name,
                    'parameters': dict(sample.parameter_dict),
                    'starting_soc': getattr(sample, 'soc', None),
                }
            self.configure_sourcemeter()
            self.cycle()
            self.status = 'aborted' if self.abort_requested else 'complete'
        except BaseException as acquisition_error:
            error = acquisition_error
            self.status = 'aborted'
        finally:
            try:
                self.safe_close()
            except Exception as shutdown_error:
                self.cleanup_error = str(shutdown_error)
                self.status = 'aborted'
                error = error if error is not None else shutdown_error
            if self.data is not None:
                try:
                    self.save_data()
                    self._update_history()
                except Exception as save_error:
                    self.save_error = str(save_error)
                    error = error if error is not None else save_error
        if error is not None:
            raise error
        self.analyze()
        # Include the generated plot path in saved metadata and history.
        self.save_data()
        self.history[-1] = self.metadata.copy()
        return self.data
