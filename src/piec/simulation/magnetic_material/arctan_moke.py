"""Level-3 ideal noiseless arctan MOKE and AMR magnetic sample model."""
import numpy as np
from .magnetic_material import MagneticMaterial


class ArctanMOKE(MagneticMaterial):
    """Ferromagnetic sample with an ideal noiseless arctan hysteresis loop.

    The ascending and descending branches follow:
        M_up(H)   = (2 / pi) * arctan((H - bias - coercivity) / switching_width)
        M_down(H) = (2 / pi) * arctan((H - bias + coercivity) / switching_width)
    """

    def __init__(self, r_base=100.0, amr_ratio=0.02, phi_offset=0.0, *,
                 coercivity=100.0, switching_width=30.0, bias=0.0,
                 offset=0.3, sensitivity=0.02,
                 parameter_dict=None, name="virtual_magnetic_sample"):
        super().__init__(parameter_dict=parameter_dict, name=name)
        self.r_base = self.parameter_dict.setdefault('r_base', r_base)
        self.amr_ratio = self.parameter_dict.setdefault('amr_ratio', amr_ratio)
        self.phi_offset = self.parameter_dict.setdefault('phi_offset', phi_offset)
        self.coercivity = self.parameter_dict.get('coercivity', coercivity)
        self.switching_width = self.parameter_dict.get('switching_width', switching_width)
        self.bias = self.parameter_dict.get('bias', bias)
        self.offset = self.parameter_dict.get('offset', offset)
        self.sensitivity = self.parameter_dict.get('sensitivity', sensitivity)
        if (not np.isfinite([self.coercivity, self.switching_width, self.bias]).all()
                or self.coercivity < 0 or self.switching_width <= 0):
            raise ValueError('Require finite coercivity >= 0 and switching width > 0')
        self._magnetization = 0.0

    def _branch_m(self, field, sign):
        """Evaluate the ascending (sign=+1) or descending (sign=-1) arctan branch."""
        return float((2.0 / np.pi) * np.arctan(
            (field - self.bias - sign * self.coercivity) / self.switching_width
        ))

    def set_field(self, field):
        """Update applied field in Oe and advance along the arctan hysteresis branch."""
        value = float(field)
        if not np.isfinite(value):
            raise ValueError('Field must be finite')
        if value > self._current_field:
            self._magnetization = max(self._magnetization, self._branch_m(value, +1.0))
        elif value < self._current_field:
            self._magnetization = min(self._magnetization, self._branch_m(value, -1.0))
        self._current_field = value

    def get_magnetization(self):
        """Return normalized magnetization M/Ms in [-1, 1]."""
        return float(self._magnetization)

    def get_moke_voltage(self):
        """Return the ideal noiseless MOKE optical detector voltage in Volts."""
        return float(self.offset + self.sensitivity * self._magnetization)

    def get_resistance(self, angle=None, field=None):
        """Calculate AMR resistance: R = R_perp + (R_par - R_perp) * cos^2(theta - phi)."""
        theta = np.radians(angle if angle is not None else self.current_angle)
        phi = np.radians(self.phi_offset)
        r_perp = self.r_base
        r_par = self.r_base * (1 + self.amr_ratio)
        resistance = r_perp + (r_par - r_perp) * (np.cos(theta - phi) ** 2)
        noise = np.random.normal(0, self.r_base * 0.0001)
        return resistance + noise

    def get_voltage_response(self, current_v=1.0):
        """Return simulated AMR lock-in voltage."""
        return self.get_resistance() * 1e-6


MagneticSample = ArctanMOKE
