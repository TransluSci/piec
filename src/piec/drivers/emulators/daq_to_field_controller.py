"""Use a DAQ analog output to command an external field controller."""
import numpy as np

from ..field_controller import FieldController


class DaqFieldController(FieldController):
    def __init__(self, daq_instance, ao_channel, gain=100.0, offset=0.0, output_limits=(-10, 10)):
        self._initialize_common_state(check_params=False, verbose=False)
        if ao_channel not in daq_instance.ao_channel:
            raise ValueError(f'Unavailable analog output: {ao_channel}')
        low, high = output_limits
        if not any(vmin <= low < high <= vmax for vmin, vmax in daq_instance.ao_range):
            raise ValueError('Output limits exceed the DAQ voltage range')
        if not np.isfinite([low, high, gain, offset]).all() or gain == 0:
            raise ValueError('Require finite output limits, nonzero gain and finite offset')
        self.daq, self.ao_channel = daq_instance, ao_channel
        self._field_setpoint = None
        self._ramp_end = None
        self.gain, self.offset = gain, offset
        self.field = tuple(sorted((gain * low + offset, gain * high + offset)))
        if not np.isfinite(self.field).all():
            raise ValueError('Calibrated field limits must be finite')
        self._output_for_field(0.0)

    def idn(self):
        return f'DAQ field controller AO{self.ao_channel} ({self.daq.idn()})'

    def _output_for_field(self, fields):
        fields = np.asarray(fields, dtype=float)
        if not np.isfinite(fields).all() or np.any(fields < self.field[0]) or np.any(fields > self.field[1]):
            raise ValueError('Requested field exceeds configured DAQ output limits')
        return (fields - self.offset) / self.gain

    def set_field(self, field):
        voltage = float(self._output_for_field(field))
        self.stop_ramp()
        self.daq.write_AO(ao_channel=self.ao_channel, data=voltage)
        self._field_setpoint = float(field)

    def _has_hardware_waveform(self):
        method = getattr(type(self.daq), 'write_AO_scan', None)
        return callable(method) and not getattr(method, '_is_optional', False)

    def start_triangle_waveform(self, field_min, field_max, cycle_period, sample_rate=None):
        """Start a continuous hardware-paced triangle waveform (0 -> max -> 0 -> min -> 0)."""
        if not np.isfinite([field_min, field_max, cycle_period]).all() or field_min >= field_max or cycle_period <= 0:
            raise ValueError('Require finite increasing field limits and positive cycle period')
        low_rate, high_rate = self.daq.ao_sample_rate
        rate = min(high_rate, 10_000) if sample_rate is None else float(sample_rate)
        rate = float(np.clip(rate, low_rate, high_rate))
        points = max(8, int(round(cycle_period * rate)))
        if points >= 1_000_000:
            points = 999_996
            rate = points / cycle_period
        # Build one cycle: 0 -> field_max -> 0 -> field_min -> 0 (match HysteresisLoop / LabVIEW)
        vertices = np.array([0.0, float(field_max), 0.0, float(field_min), 0.0])
        fields = np.interp(np.linspace(0.0, 4.0, points, endpoint=False), np.arange(5), vertices)
        volts = self._output_for_field(fields)
        self.stop_ramp()
        self._field_setpoint = None
        self._ramp_end = float('inf')
        if self._has_hardware_waveform():
            actual_rate = self.daq.write_AO_scan(
                ao_channel=self.ao_channel, data=volts, sample_rate=int(round(rate)),
            )
        else:
            self.daq.write_AO(ao_channel=self.ao_channel, data=volts)
            actual_rate = int(round(rate))
        if actual_rate is None:
            actual_rate = int(round(rate))
        if not np.isfinite(actual_rate) or actual_rate <= 0:
            raise ValueError('DAQ returned an invalid waveform output rate')
        return points / actual_rate

    def stop_ramp(self):
        """Stop or release a running waveform so a new field setpoint can be commanded."""
        if self._ramp_end is not None:
            if self._has_hardware_waveform():
                self.daq.stop_output()
            self._ramp_end = None
