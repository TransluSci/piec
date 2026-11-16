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
        self.r_base = self.parameter_dict.setdefault('r_base', r_base)
        self.amr_ratio = self.parameter_dict.setdefault('amr_ratio', amr_ratio)
        self.phi_offset = self.parameter_dict.setdefault('phi_offset', phi_offset)

    def set_field(self, field):
        """Apply magnetic field in Oe."""
        value = float(field)
        if not np.isfinite(value):
            raise ValueError('Field must be finite')
        self._field = value

    def get_field(self):
        """Return the current applied magnetic field in Oe."""
        return float(self._field)

    def set_angle(self, angle):
        """Set the sample orientation angle in degrees."""
        self._angle = float(angle)

    def set_voltage(self, v):
        """Map an applied electromagnet drive voltage (1 V = 10,000 Oe) to field."""
        self._voltage = float(v)
        self.set_field(self._voltage * 10000.0)

    def set_current(self, i):
        """Map an applied electromagnet drive current (1 A = 10,000 Oe) to field."""
        self._current = float(i)
        self.set_field(self._current * 10000.0)

    def get_voltage(self):
        """Return terminal/field-monitor voltage in Volts."""
        return float(self._voltage)

    def get_resistance(self, angle=None, field=None):
        """Calculate AMR resistance: R = R_perp + (R_par - R_perp) * cos^2(theta - phi)."""
        theta = np.radians(angle if angle is not None else self._angle)
        phi = np.radians(self.phi_offset)
        r_perp = self.r_base
        r_par = self.r_base * (1 + self.amr_ratio)
        resistance = r_perp + (r_par - r_perp) * (np.cos(theta - phi) ** 2)
        noise = np.random.normal(0, self.r_base * 0.0001)
        return float(resistance + noise)


MagneticSample = CosSquaredAMR