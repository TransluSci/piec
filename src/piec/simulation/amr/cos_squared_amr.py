"""Level-3 cos^2(theta - phi) Anisotropic Magnetoresistance (AMR) sample model."""
import numpy as np
from .amr import AMRMaterial


class CosSquaredAMR(AMRMaterial):
    """AMR sample following R(theta) = R_perp + (R_par - R_perp) * cos^2(theta - phi)."""

    def __init__(
        self,
        r_base=100.0,
        amr_ratio=0.02,
        phi_offset=0.0,
        *,
        parameter_dict=None,
        name="virtual_magnetic_sample",
    ):
        super().__init__(parameter_dict=parameter_dict, name=name)
        self.r_base = float(self.parameter_dict.setdefault('r_base', r_base))
        self.amr_ratio = float(self.parameter_dict.setdefault('amr_ratio', amr_ratio))
        self.phi_offset = float(self.parameter_dict.setdefault('phi_offset', phi_offset))

    def apply_current(self, i=1e-6, angle=0.0, field=0.0):
        """Return terminal voltage (V) for sense current ``i`` (A) at ``(angle, field)``."""
        theta = np.radians(angle)
        phi = np.radians(self.phi_offset)
        r_perp = self.r_base
        r_par = self.r_base * (1.0 + self.amr_ratio)
        resistance = r_perp + (r_par - r_perp) * (np.cos(theta - phi) ** 2)
        noise = np.random.normal(0, self.r_base * 0.0001)
        return float(i * (resistance + noise))
