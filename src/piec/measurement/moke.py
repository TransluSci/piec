"""Instrument-independent optical hysteresis acquisition and averaging."""
import threading
import time
import numpy as np
import pandas as pd

from .experiment import Experiment
from ..analysis.utilities import create_measurement_filename, metadata_and_data_to_csv


def _triangle_cycle_fields(field_min, field_max, points_per_cycle):
    """Build one HysteresisLoop triangle cycle: 0 -> max -> 0 -> min -> 0."""
    vertices = np.array([0.0, float(field_max), 0.0, float(field_min), 0.0])
    phase = np.linspace(0.0, 4.0, points_per_cycle, endpoint=False)
    return np.interp(phase, np.arange(5), vertices)


class MOKE(Experiment):
    """One or more field loops from a field controller and optical detector.

    Both stepped and continuous modes sweep a bipolar triangle waveform:
    0 -> field_max -> 0 -> field_min -> 0 per cycle.
    Stepped acquisition sets each field point, waits dwell_time (and optional
    field_tolerance convergence on a gaussmeter), and reads optical voltage.
    Continuous acquisition sweeps the triangle waveform at cycle_period and
    samples the detector and optional gaussmeter at sample_rate.
    """
    mtype = 'moke'

    def __init__(self, field_controller, dmm, gaussmeter=None, *, geometry='longitudinal', gaussmeter_channel=1,
                 field_min=-1000.0, field_max=1000.0, cycles=1, points_per_cycle=200,
                 discard_cycles=0, dwell_time=0.01, field_tolerance=None,
                 settle_timeout=10.0, initial_hold=0.0, mode='stepped',
                 cycle_period=1.0, sample_rate=10000,
                 save_dir='scratch', on_update=None):
        self.field_controller, self.dmm, self.gaussmeter = field_controller, dmm, gaussmeter
        self.geometry = geometry.lower()
        self.field_min, self.field_max = float(field_min), float(field_max)
        self.cycles, self.points_per_cycle, self.discard_cycles = cycles, points_per_cycle, discard_cycles
        self.dwell_time, self.field_tolerance = float(dwell_time), field_tolerance
        self.settle_timeout, self.initial_hold = float(settle_timeout), float(initial_hold)
        self.mode = mode
        self.cycle_period = cycle_period if mode == 'continuous' else None
        self.sample_rate = sample_rate if mode == 'continuous' else None
        self.field_source = 'measured' if gaussmeter is not None else 'estimated'
        self.gaussmeter_channel = gaussmeter_channel if gaussmeter is not None else None
        self._on_update = on_update
        self._cancel, self._pause = threading.Event(), threading.Event()
        self._instruments = ('field_controller', 'dmm') + (('gaussmeter',) if gaussmeter is not None else ())
        self.status = 'ready'
        self._validate()
        self._reset_data()
        super().__init__(save_dir=save_dir)

    def _shared_daq(self):
        """Return the shared DAQ instance when field_controller and dmm use the same board."""
        fc_daq = getattr(self.field_controller, 'daq', None)
        dmm_daq = getattr(self.dmm, 'daq', None)
        if fc_daq is None or fc_daq is not dmm_daq:
            return None
        if self.gaussmeter is not None and getattr(self.gaussmeter, 'daq', None) is not fc_daq:
            return None
        if not (callable(getattr(self.field_controller, 'start_triangle_waveform', None))
                and callable(getattr(fc_daq, 'read_AI_scan', None))):
            return None
        return fc_daq

    def _validate(self):
        if self.geometry not in ('longitudinal', 'polar', 'transverse'):
            raise ValueError('Unknown MOKE geometry')
        if self.mode not in ('stepped', 'continuous'):
            raise ValueError('mode must be stepped or continuous')
        if self.dmm is None:
            raise ValueError('MOKE requires a DMM')
        if not np.isfinite([self.field_min, self.field_max]).all() or self.field_min >= 0 or self.field_max <= 0:
            raise ValueError('Require finite bipolar field limits with field_min < 0 < field_max')
        for name, minimum in [('cycles', 1), ('points_per_cycle', 8), ('discard_cycles', 0)]:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f'{name} must be an integer >= {minimum}')
        if (not np.isfinite([self.dwell_time, self.settle_timeout, self.initial_hold]).all()
                or self.dwell_time < 0 or self.initial_hold < 0 or self.settle_timeout <= 0):
            raise ValueError('Dwell/initial hold must be nonnegative and settle timeout positive')
        if self.field_tolerance is not None:
            if (not np.isfinite(self.field_tolerance) or self.field_tolerance <= 0
                    or self.gaussmeter is None):
                raise ValueError('Positive field tolerance requires a gaussmeter')
            if self.mode != 'stepped':
                raise ValueError('Field settling tolerance applies only to stepped acquisition')
        limits = getattr(self.field_controller, 'field', None)
        if limits is not None and (limits[0] > self.field_min or limits[1] < self.field_max):
            raise ValueError('Requested field exceeds configured output limits')
        if self.gaussmeter is not None and self.gaussmeter_channel not in self.gaussmeter.channel:
            raise ValueError(f'Unavailable gaussmeter channel: {self.gaussmeter_channel}')
        if self.mode == 'continuous':
            if not np.isfinite(self.sample_rate) or self.sample_rate <= 0:
                raise ValueError('Sample rate must be positive')
            if self.cycle_period is None or not np.isfinite(self.cycle_period) or self.cycle_period <= 0:
                raise ValueError('Continuous acquisition requires a positive cycle period')
            if not np.isfinite(self.cycle_period * self.sample_rate) or self.cycle_period * self.sample_rate < 20:
                raise ValueError('Continuous acquisition needs at least 20 samples per cycle')

    def _reset_data(self):
        self.filename = None
        self.average_filename = None
        for name in ('actual_sample_rate', 'actual_cycle_period'):
            self.__dict__.pop(name, None)
        self.data = pd.DataFrame()
        self._latest = pd.DataFrame()
        self._average = pd.DataFrame()
        self._chunks = []
        self._received = 0
        self._paused_seconds = 0.0
        self.completed_cycles = 0
        self.acquired_cycles = 0
        self._cycle_grid = _triangle_cycle_fields(self.field_min, self.field_max, self.points_per_cycle)
        self._phase_grid = np.linspace(0.0, 1.0, self.points_per_cycle, endpoint=False)
        self._sum_field = np.zeros(self.points_per_cycle)
        self._sum_sig = np.zeros(self.points_per_cycle)
        self._sum2_sig = np.zeros(self.points_per_cycle)
        self._count = np.zeros(self.points_per_cycle, dtype=int)

    @property
    def average_data(self):
        return self._average.copy()

    @property
    def latest_cycle(self):
        return self._latest.copy()

    def request_stop(self):
        self._cancel.set()

    def request_pause(self):
        self._pause.set()

    def request_resume(self):
        self._pause.clear()

    def _wait_if_paused(self):
        if self._pause.is_set() and not self._cancel.is_set():
            before = time.monotonic()
            self.status = 'paused'
            self._notify(pd.DataFrame())
            while self._pause.is_set() and not self._cancel.wait(0.05):
                pass
            self._paused_seconds += time.monotonic() - before
            self.status = 'running'
        return self._cancel.is_set()

    def safe_close(self):
        """Zero only the selected source; do not reset shared input hardware."""
        self.field_controller.set_field(0.0)

    def _notify(self, live):
        if self._on_update:
            self._on_update({'live': live.copy(), 'latest': self.latest_cycle,
                             'average': self.average_data, 'cycles': self.completed_cycles,
                             'status': self.status})

    def _accept_cycle(self, frame):
        """Record one completed 0 -> +H -> 0 -> -H -> 0 cycle and update the closed-loop average."""
        index = self.acquired_cycles
        self.acquired_cycles += 1
        frame = frame.copy()
        frame['cycle'] = index
        frame['included'] = index >= self.discard_cycles
        self._latest = frame
        if index < self.discard_cycles or len(frame) < 4:
            return
        sample_phase = np.linspace(0.0, 1.0, len(frame), endpoint=False)
        interp_field = np.interp(self._phase_grid, sample_phase, frame['field (Oe)'].to_numpy())
        interp_sig = np.interp(self._phase_grid, sample_phase, frame['signal (V)'].to_numpy())
        valid = np.isfinite(interp_field) & np.isfinite(interp_sig)
        self._sum_field[valid] += interp_field[valid]
        self._sum_sig[valid] += interp_sig[valid]
        self._sum2_sig[valid] += interp_sig[valid] ** 2
        self._count[valid] += 1
        self.completed_cycles += 1
        mean_field = np.divide(self._sum_field, self._count,
                               out=self._cycle_grid.copy(), where=self._count > 0)
        mean_sig = np.divide(self._sum_sig, self._count,
                             out=np.full(self._count.shape, np.nan), where=self._count > 0)
        variance = np.divide(self._sum2_sig - self._count * np.nan_to_num(mean_sig) ** 2,
                             self._count - 1, out=np.full(self._count.shape, np.nan), where=self._count > 1)
        self._average = pd.DataFrame({
            'field (Oe)': mean_field,
            'signal (V)': mean_sig,
            'signal std (V)': np.sqrt(np.maximum(variance, 0.0)),
            'cycles': self._count.copy(),
        })

    def _wait_interval(self, duration):
        remaining = duration
        while remaining > 0:
            if self._wait_if_paused():
                return True
            before = time.monotonic()
            if self._cancel.wait(min(0.05, remaining)):
                return True
            remaining -= time.monotonic() - before
        return self._wait_if_paused()

    def _settled_field(self, requested):
        if self._wait_interval(self.dwell_time):
            return None
        deadline = time.monotonic() + self.settle_timeout
        paused_seconds = self._paused_seconds
        while True:
            deadline += self._paused_seconds - paused_seconds
            paused_seconds = self._paused_seconds
            field = (float(self.gaussmeter.get_field(channel=self.gaussmeter_channel))
                     if self.gaussmeter is not None else float(requested))
            if not np.isfinite(field):
                raise ValueError('Nonfinite magnetic field reading')
            if self.field_tolerance is None or abs(field - requested) <= self.field_tolerance:
                return field
            if time.monotonic() >= deadline:
                raise TimeoutError(f'Field did not settle within {self.field_tolerance} Oe of {requested} Oe')
            if self._wait_interval(0.02):
                return None

    def _stepped(self):
        fields = self._cycle_grid
        start = time.monotonic()
        total_cycles = self.cycles + self.discard_cycles
        for cycle_idx in range(total_cycles):
            rows = []
            for i, requested in enumerate(fields):
                if self._wait_if_paused():
                    break
                self.field_controller.set_field(float(requested))
                field = self._settled_field(requested)
                if field is None:
                    break
                signal = float(self.dmm.get_voltage())
                if not np.isfinite(signal):
                    raise ValueError('Nonfinite optical reading')
                rows.append({
                    'time (s)': time.monotonic() - start,
                    'requested field (Oe)': float(requested),
                    'field (Oe)': field,
                    'signal (V)': signal,
                    'cycle': cycle_idx,
                    'included': cycle_idx >= self.discard_cycles,
                })
                frame = pd.DataFrame([rows[-1]], index=[self._received])
                self._chunks.append(frame)
                self._received += 1
                if i % max(1, len(fields) // 10) == 0:
                    self._notify(pd.DataFrame(rows))
            if len(rows) == len(fields):
                frame = pd.DataFrame(rows, index=range(self._received - len(rows), self._received))
                self._accept_cycle(frame)
                self._notify(frame)
            if self._cancel.is_set():
                break

    def _daq_continuous(self, daq):
        """Hardware-paced continuous triangle output and synchronized AI scan on a shared DAQ."""
        channels = [self.dmm.ai_channel]
        if self.gaussmeter is not None:
            channels.append(self.gaussmeter.ai_channel)
        samples_per_cycle = max(20, int(round(self.cycle_period * self.sample_rate)))
        total_cycles = self.cycles + self.discard_cycles
        total_points = samples_per_cycle * total_cycles
        try:
            self.actual_cycle_period = self.field_controller.start_triangle_waveform(
                self.field_min, self.field_max, self.cycle_period, sample_rate=self.sample_rate
            )
            scan = daq.read_AI_scan(channels, total_points, self.sample_rate)
            self.actual_sample_rate = scan.attrs.get('sample_rate', self.sample_rate)
            times = scan['Time'].to_numpy()
            signal = scan.iloc[:, 1].to_numpy()
            indices = np.arange(len(times))
            phase = (indices % samples_per_cycle) * (4.0 / samples_per_cycle)
            vertices = np.array([0.0, self.field_max, 0.0, self.field_min, 0.0])
            requested = np.interp(phase, np.arange(5), vertices)
            field = (self.gaussmeter.field_from_voltage(scan.iloc[:, 2].to_numpy())
                     if self.gaussmeter is not None else requested)
            frame = pd.DataFrame({
                'time (s)': times,
                'requested field (Oe)': requested,
                'field (Oe)': field,
                'signal (V)': signal,
                'cycle': indices // samples_per_cycle,
                'included': (indices // samples_per_cycle) >= self.discard_cycles,
            }, index=indices)
            self._received = len(frame)
            self._chunks.append(frame)
            for c in range(len(frame) // samples_per_cycle):
                self._accept_cycle(frame.iloc[c * samples_per_cycle:(c + 1) * samples_per_cycle])
            self._notify(frame)
        finally:
            self.field_controller.stop_ramp()

    def _continuous(self):
        daq = self._shared_daq()
        if daq is not None:
            self._daq_continuous(daq)
            return
        run_start = time.monotonic()
        samples_per_cycle = max(20, int(round(self.cycle_period * self.sample_rate)))
        cycle_fields = _triangle_cycle_fields(self.field_min, self.field_max, samples_per_cycle)
        dt = self.cycle_period / samples_per_cycle
        for cycle_idx in range(self.cycles + self.discard_cycles):
            if self._wait_if_paused():
                break
            rows = []
            cycle_start = time.monotonic()
            for i, requested in enumerate(cycle_fields):
                if self._cancel.is_set():
                    break
                self.field_controller.set_field(float(requested))
                field = (float(self.gaussmeter.get_field(channel=self.gaussmeter_channel))
                         if self.gaussmeter is not None else float(requested))
                signal = float(self.dmm.get_voltage())
                if not np.isfinite([field, signal]).all():
                    raise ValueError('Nonfinite reading during continuous sweep')
                rows.append({
                    'time (s)': time.monotonic() - run_start,
                    'requested field (Oe)': float(requested),
                    'field (Oe)': field,
                    'signal (V)': signal,
                    'cycle': cycle_idx,
                    'included': cycle_idx >= self.discard_cycles,
                })
                target_time = cycle_start + (i + 1) * dt
                wait = target_time - time.monotonic()
                if wait > 0 and self._cancel.wait(wait):
                    break
            if len(rows) == len(cycle_fields) and not self._cancel.is_set():
                frame = pd.DataFrame(rows, index=range(self._received, self._received + len(rows)))
                self._received += len(frame)
                self._chunks.append(frame)
                self.actual_cycle_period = frame['time (s)'].iloc[-1] - frame['time (s)'].iloc[0] + dt
                self.actual_sample_rate = len(frame) / self.actual_cycle_period
                self._accept_cycle(frame)
                self._notify(frame)

    def _finalize_data(self):
        self.data = pd.concat(self._chunks) if self._chunks else pd.DataFrame()

    def save_data(self):
        self._update_metadata()
        if self.data.empty:
            return
        self.filename = create_measurement_filename(self.save_dir, self.mtype, self.geometry)
        metadata_and_data_to_csv(self.metadata, self.data, self.filename)
        if not self._average.empty:
            self.average_filename = self.filename[:-4] + '_average.csv'
            metadata = self.metadata.copy()
            metadata['processed'] = True
            metadata['raw_file'] = self.filename
            metadata_and_data_to_csv(metadata, self._average, self.average_filename)

    def run_experiment(self, save=True):
        """Acquire and save; always zero output, preserving partial data on error."""
        self._validate()
        self._reset_data()
        self.status = 'running'
        try:
            if not self._cancel.is_set():
                self.field_controller.set_field(0.0)
                if self.initial_hold > 0:
                    if self._settled_field(0.0) is not None:
                        self._wait_interval(self.initial_hold)
                if self.mode == 'continuous':
                    self._continuous()
                else:
                    self._stepped()
            self.status = 'stopped' if self._cancel.is_set() else 'complete'
        except BaseException:
            self.status = 'failed'
            raise
        finally:
            try:
                self.safe_close()
            except Exception:
                self.status = 'shutdown_failed'
                raise
            finally:
                self._finalize_data()
                if save:
                    self.save_data()
                else:
                    self._update_metadata()
                self._update_history()
                self._cancel.clear()
                self._pause.clear()
        return self.data
