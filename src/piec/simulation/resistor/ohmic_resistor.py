"""Level-3 ideal Ohmic resistor simulation (V = I * R)."""
import numpy as np
from .resistor import ResistiveMaterial


class OhmicResistor(ResistiveMaterial):
    """Ideal linear Ohmic resistor: I = V / R."""

    def __init__(self, resistance=1e3, *, parameter_dict=None, name="resistor"):
        """Initialize resistance in Ohms; dictionary values override scalar arguments."""
        super().__init__(parameter_dict=parameter_dict, name=name)
        self.resistance = self.parameter_dict.setdefault('resistance', resistance)
        self.output_voltage = np.array([])
        self.t = np.array([])
        self.prep_points = 0

    def voltage_response(self, v, t=0.0):
        """Return current (A) produced by an applied voltage (V)."""
        return v / self.resistance, t

    def current_response(self, i, t=0.0):
        """Return voltage (V) produced by an applied current (A)."""
        return i * self.resistance, t

    def apply_waveform(self, v, t):
        """Apply voltage waveform and record the voltage response across the resistor."""
        p = getattr(self, 'prep_points', 0)
        self.output_voltage = np.array(v[p:])
        self.t = np.array(t[p:]) - (t[p] if len(t) > p else 0.0)

    def get_voltage_response(self):
        """Return (output_voltage, time) as measured across the resistor."""
        return self.output_voltage, self.t


Resistor = OhmicResistor
