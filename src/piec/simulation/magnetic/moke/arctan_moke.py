"""Level-3 arctan hysteresis MOKE sample model."""
import numpy as np
from .moke import MOKEMaterial


class ArctanMOKE(MOKEMaterial):
    """Ferromagnetic sample with an ideal noiseless arctan hysteresis loop."""

    def __init__(
        self,
        coercivity=100.0,
        switching_width=30.0,
        bias=0.0,
        offset=0.3,
        sensitivity=0.02,
        *,
        parameter_dict=None,
        name="virtual_moke_sample",
    ):
        super().__init__(parameter_dict=parameter_dict, name=name)
        self.coercivity = float(self.parameter_dict.setdefault('coercivity', coercivity))
        self.switching_width = float(self.parameter_dict.setdefault('switching_width', switching_width))
        self.bias = float(self.parameter_dict.setdefault('bias', bias))
        self.offset = float(self.parameter_dict.setdefault('offset', offset))
        self.sensitivity = float(self.parameter_dict.setdefault('sensitivity', sensitivity))
        if (
            not np.isfinite([self.coercivity, self.switching_width, self.bias]).all()
            or self.coercivity < 0
            or self.switching_width <= 0
        ):
            raise ValueError('Require finite coercivity >= 0 and switching width > 0')
        self._field = 0.0
        self._magnetization = 0.0

    def _branch_m(self, field, sign):
        """Evaluate the ascending (sign=+1) or descending (sign=-1) arctan branch."""
        return float((2.0 / np.pi) * np.arctan(
            (field - self.bias - sign * self.coercivity) / self.switching_width
        ))

    def apply_field(self, field):
        """Apply magnetic field in Oe, update hysteresis state, and return detector voltage (V)."""
        value = float(field)
        if not np.isfinite(value):
            raise ValueError('Field must be finite')
        if value > self._field:
            self._magnetization = max(self._magnetization, self._branch_m(value, +1.0))
        elif value < self._field:
            self._magnetization = min(self._magnetization, self._branch_m(value, -1.0))
        self._magnetization = float(np.clip(self._magnetization, -1.0, 1.0))
        self._field = value
        return float(self.offset + self.sensitivity * self._magnetization)
