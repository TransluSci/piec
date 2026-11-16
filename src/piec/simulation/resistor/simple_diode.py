"""Level-3 nonlinear Shockley diode simulation."""
import numpy as np
from .resistor import ResistiveMaterial


class SimpleDiode(ResistiveMaterial):
    """Nonlinear diode following the Shockley equation: I = Is * (exp(V / (n * Vt)) - 1)."""

    def __init__(
        self,
        saturation_current=1e-9,
        ideality=1.5,
        thermal_voltage=0.02585,
        *,
        parameter_dict=None,
        name="simple_diode",
    ):
        """Initialize diode parameters; dictionary values override scalar arguments."""
        super().__init__(parameter_dict=parameter_dict, name=name)
        self.saturation_current = float(
            self.parameter_dict.setdefault('saturation_current', saturation_current)
        )
        self.ideality = float(self.parameter_dict.setdefault('ideality', ideality))
        self.thermal_voltage = float(
            self.parameter_dict.setdefault('thermal_voltage', thermal_voltage)
        )
        if self.saturation_current <= 0 or self.ideality <= 0 or self.thermal_voltage <= 0:
            raise ValueError('saturation_current, ideality, and thermal_voltage must be positive')
        self.output_voltage = np.array([])
        self.t = np.array([])

    def set_voltage(self, v):
        """Apply DC voltage ``v`` (V) and solve Shockley diode current."""
        self._voltage = float(v)
        self._current = float(self.voltage_response(self._voltage)[0])

    def set_current(self, i):
        """Apply DC current ``i`` (A) and solve Shockley diode voltage."""
        self._current = float(i)
        self._voltage = float(self.current_response(self._current)[0])

    def get_voltage(self):
        """Return terminal voltage in Volts."""
        return float(self._voltage)

    def get_current(self):
        """Return terminal current in Amperes."""
        return float(self._current)

    def get_resistance(self, angle=None, field=None):
        """Return static chord or zero-bias small-signal resistance in Ohms."""
        if self._current != 0:
            return float(self._voltage / self._current)
        return float(self.ideality * self.thermal_voltage / self.saturation_current)

    def voltage_response(self, v, t=0.0):
        """Return ``(current_A, time_s)`` for applied voltage ``v`` (V)."""
        exponent = np.clip(
            np.asarray(v, dtype=float) / (self.ideality * self.thermal_voltage),
            -100.0,
            40.0,
        )
        current = self.saturation_current * np.expm1(exponent)
        return (float(current) if np.ndim(v) == 0 else current), t

    def current_response(self, i, t=0.0):
        """Return ``(voltage_V, time_s)`` for applied current ``i`` (A) above ``-Is``."""
        i_arr = np.asarray(i, dtype=float)
        if np.any(i_arr <= -self.saturation_current):
            raise ValueError('Current must exceed -saturation_current for Shockley diode inversion')
        voltage = self.ideality * self.thermal_voltage * np.log1p(i_arr / self.saturation_current)
        return (float(voltage) if np.ndim(i) == 0 else voltage), t

    def apply_waveform(self, v, t):
        """Apply voltage waveform ``v(t)`` and record the voltage response across the diode."""
        p = getattr(self, 'prep_points', 0)
        self.output_voltage = np.array(v[p:])
        self.t = np.array(t[p:]) - (t[p] if len(t) > p else 0.0)

    def get_waveform(self):
        """Return ``(output_voltage_V, time_s)`` recorded from the last applied waveform."""
        return self.output_voltage, self.t

    get_voltage_response = get_waveform