"""Level-3 ideal noiseless arctan hysteresis model for MOKE."""
import numpy as np
from .hysteretic_magnetic_material import HystereticMagneticMaterial


class ArctanMOKE(HystereticMagneticMaterial):
    """Ferromagnetic sample with an ideal noiseless arctan hysteresis loop.

    The ascending and descending branches follow:
        M_up(H)   = (2 / pi) * arctan((H - bias - coercivity) / switching_width)
        M_down(H) = (2 / pi) * arctan((H - bias + coercivity) / switching_width)
    """

    def __init__(self, *, coercivity=100.0, switching_width=30.0, bias=0.0,
                 offset=0.3, sensitivity=0.02,
                 parameter_dict=None, name="virtual_magnetic_sample"):
        super().__init__(parameter_dict=parameter_dict, name=name)
        self.coercivity = self.parameter_dict.get('coercivity', coercivity)
        self.switching_width = self.parameter_dict.get('switching_width', switching_width)
        self.bias = self.parameter_dict.get('bias', bias)
        self.offset = self.parameter_dict.get('offset', offset)
        self.sensitivity = self.parameter_dict.get('sensitivity', sensitivity)
        if (not np.isfinite([self.coercivity, self.switching_width, self.bias]).all()
                or self.coercivity < 0 or self.switching_width <= 0):
            raise ValueError('Require finite coercivity >= 0 and switching width > 0')

    def _branch_m(self, field, sign):
        """Evaluate the ascending (sign=+1) or descending (sign=-1) arctan branch."""
        return float((2.0 / np.pi) * np.arctan(
            (field - self.bias - sign * self.coercivity) / self.switching_width
        ))

    def _update_magnetization(self, new_field, prev_field):
        if new_field > prev_field:
            return max(self._magnetization, self._branch_m(new_field, +1.0))
        if new_field < prev_field:
            return min(self._magnetization, self._branch_m(new_field, -1.0))
        return self._magnetization

    def _compute_moke_voltage(self):
        return float(self.offset + self.sensitivity * self._magnetization)


class MagneticSample(ArctanMOKE):
    """Compatibility wrapper adding AMR transport for VirtualStepper/VirtualLockin."""

    def __init__(self, r_base=100.0, amr_ratio=0.02, phi_offset=0.0, **kwargs):
        super().__init__(**kwargs)
        self.current_angle = 0.0
        self.r_base = self.parameter_dict.setdefault('r_base', r_base)
        self.amr_ratio = self.parameter_dict.setdefault('amr_ratio', amr_ratio)
        self.phi_offset = self.parameter_dict.setdefault('phi_offset', phi_offset)

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
