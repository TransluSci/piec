"""Level-3 ideal Ohmic resistor simulation (V = I * R)."""
import numpy as np
from .resistor import ResistiveMaterial


class OhmicResistor(ResistiveMaterial):
    """Ideal linear Ohmic resistor: I = V / R."""

    def __init__(self, resistance=1e3, *, parameter_dict=None, name="resistor"):
        """Initialize resistance in Ohms; dictionary values override scalar arguments."""
        super().__init__(parameter_dict=parameter_dict, name=name)
        self.resistance = float(self.parameter_dict.setdefault('resistance', resistance))
        if self.resistance <= 0:
            raise ValueError('resistance must be positive')
        self.output_voltage = np.array([])
        self.t = np.array([])

    def set_voltage(self, v):
        """Apply DC voltage ``v`` (V) and update ``V`` / ``I = V / R``."""
        self._voltage = float(v)
        self._current = self._voltage / self.resistance

    def set_current(self, i):
        """Apply DC current ``i`` (A) and update ``I`` / ``V = I * R``."""
        self._current = float(i)
        self._voltage = self._current * self.resistance

    def get_voltage(self):
        """Return terminal voltage in Volts."""
        return float(self._voltage)

    def get_current(self):
        """Return terminal current in Amperes."""
        return float(self._current)

    def get_resistance(self, angle=None, field=None):
        """Return sample resistance in Ohms."""
        return float(self.resistance)

    def voltage_response(self, v, t=0.0):
        """Return ``(current_A, time_s)`` produced by an applied voltage ``v`` (V)."""
        return v / self.resistance, t

    def current_response(self, i, t=0.0):
        """Return ``(voltage_V, time_s)`` produced by an applied current ``i`` (A)."""
        return i * self.resistance, t

    def apply_waveform(self, v, t):
        """Apply voltage waveform ``v(t)`` and record the voltage response across the resistor."""
        p = getattr(self, 'prep_points', 0)
        self.output_voltage = np.array(v[p:])
        self.t = np.array(t[p:]) - (t[p] if len(t) > p else 0.0)

    def get_waveform(self):
        """Return ``(output_voltage_V, time_s)`` recorded from the last applied waveform."""
        return self.output_voltage, self.t

    get_voltage_response = get_waveform


Resistor = OhmicResistor