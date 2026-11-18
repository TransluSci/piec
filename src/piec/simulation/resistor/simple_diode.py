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

    def apply_voltage(self, v, t=0.0):
        """Return diode current in Amperes for applied voltage ``v`` (V)."""
        exponent = np.clip(
            np.asarray(v, dtype=float) / (self.ideality * self.thermal_voltage),
            -100.0,
            40.0,
        )
        current = self.saturation_current * np.expm1(exponent)
        return float(current) if np.ndim(v) == 0 else current

    def apply_current(self, i, t=0.0):
        """Return diode voltage in Volts for applied current ``i`` (A) above ``-Is``."""
        i_arr = np.asarray(i, dtype=float)
        if np.any(i_arr <= -self.saturation_current):
            raise ValueError('Current must exceed -saturation_current for Shockley diode inversion')
        voltage = self.ideality * self.thermal_voltage * np.log1p(i_arr / self.saturation_current)
        return float(voltage) if np.ndim(i) == 0 else voltage
