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

    def apply_voltage(self, v, t=0.0):
        """Return current in Amperes produced by an applied voltage ``v`` (V)."""
        current = np.asarray(v, dtype=float) / self.resistance
        return float(current) if np.ndim(v) == 0 else current

    def apply_current(self, i, t=0.0):
        """Return voltage in Volts produced by an applied current ``i`` (A)."""
        voltage = np.asarray(i, dtype=float) * self.resistance
        return float(voltage) if np.ndim(i) == 0 else voltage


Resistor = OhmicResistor
