"""Level-3 arctan hysteresis MOKE sample model."""
import numpy as np
from .moke import MOKEMaterial


class ArctanMOKE(MOKEMaterial):
    """Ferromagnetic sample with an ideal noiseless arctan hysteresis loop."""

    def __init__(
        self,
        *,
        coercivity=100.0,
        switching_width=30.0,
        bias=0.0,
        offset=0.3,
        sensitivity=0.02,
        parameter_dict=None,
        name="virtual_moke_sample",
    ):
        super().__init__(parameter_dict=parameter_dict, name=name)
        self.coercivity = self.parameter_dict.get('coercivity', coercivity)
        self.switching_width = self.parameter_dict.get('switching_width', switching_width)
        self.bias = self.parameter_dict.get('bias', bias)
        self.offset = self.parameter_dict.get('offset', offset)
        self.sensitivity = self.parameter_dict.get('sensitivity', sensitivity)
        if (
            not np.isfinite([self.coercivity, self.switching_width, self.bias]).all()
            or self.coercivity < 0
            or self.switching_width <= 0
        ):
            raise ValueError('Require finite coercivity >= 0 and switching width > 0')
        self._magnetization = 0.0

    def _branch_m(self, field, sign):
        """Evaluate the ascending (sign=+1) or descending (sign=-1) arctan branch."""
        return float((2.0 / np.pi) * np.arctan(
            (field - self.bias - sign * self.coercivity) / self.switching_width
        ))

    def set_field(self, field):
        """Apply magnetic field in Oe and advance along the arctan hysteresis branch."""
        value = float(field)
        if not np.isfinite(value):
            raise ValueError('Field must be finite')
        if value > self._field:
            self._magnetization = max(self._magnetization, self._branch_m(value, +1.0))
        elif value < self._field:
            self._magnetization = min(self._magnetization, self._branch_m(value, -1.0))
        self._magnetization = float(np.clip(self._magnetization, -1.0, 1.0))
        self._field = value

    def get_field(self):
        """Return the current applied magnetic field in Oe."""
        return float(self._field)

    def get_magnetization(self):
        """Return normalized magnetization M/Ms in [-1, 1]."""
        return float(self._magnetization)

    def get_voltage(self):
        """Return simulated MOKE photodetector voltage in Volts."""
        return float(self.offset + self.sensitivity * self._magnetization)