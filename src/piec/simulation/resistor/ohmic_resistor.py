"""Level-3 ideal Ohmic resistor simulation (V = I * R)."""
from .resistor import ResistiveMaterial


class OhmicResistor(ResistiveMaterial):
    """Ideal linear Ohmic resistor: I = V / R."""

    def __init__(self, resistance=1e3, *, parameter_dict=None, name="resistor"):
        """Initialize resistance in Ohms; dictionary values override scalar arguments."""
        super().__init__(parameter_dict=parameter_dict, name=name)
        self.resistance = self.parameter_dict.setdefault('resistance', resistance)

    def _compute_current(self, v, t=0.0):
        """Return current (A) produced by an applied voltage (V)."""
        return v / self.resistance

    def _compute_voltage(self, i, t=0.0):
        """Return voltage (V) produced by an applied current (A)."""
        return i * self.resistance


Resistor = OhmicResistor
